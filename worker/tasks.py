import logging

import pandas as pd

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Job, Transaction, JobSummary, JobStatus
from worker.cleaning import clean_dataframe, detect_anomalies
from worker.llm import classify_batch, generate_narrative_summary, LLMCallFailed
from app.config import settings

logger = logging.getLogger(__name__)


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _clean_value(v):
    """Coerce pandas NaN/NaT to None; pass through everything else unchanged.

    Defense-in-depth: clean_dataframe() should already have done this, but a
    raw NaN float silently corrupts SQLAlchemy's bulk-insert type inference
    for text columns, so every value going into Transaction() is sanitised
    here too rather than trusting upstream cleaning alone.
    """
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


@celery_app.task(name="worker.tasks.process_job", bind=True)
def process_job(self, job_id: str, csv_path: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = JobStatus.processing
        db.commit()

        # --- a) Data cleaning ---
        raw_df = pd.read_csv(csv_path, dtype=str)
        job.row_count_raw = len(raw_df)
        db.commit()

        clean_df = clean_dataframe(raw_df)

        # --- b) Anomaly detection ---
        clean_df = detect_anomalies(clean_df)
        job.row_count_clean = len(clean_df)
        db.commit()

        # --- c) LLM classification (batched, only for rows missing a real category) ---
        # Use the dataframe index as a stable row_key for matching results back -
        # txn_id is unreliable here since several rows have it missing/blank,
        # and using it as a dict key would collide multiple rows onto one entry.
        needs_category = clean_df[clean_df["category"] == "Uncategorised"]
        category_map = {}
        llm_failed_row_keys = set()

        rows_for_llm = [
            {"row_key": idx, **row.to_dict()}
            for idx, row in needs_category.iterrows()
        ]
        for batch in _chunked(rows_for_llm, settings.classification_batch_size):
            try:
                batch_result = classify_batch(batch)
                category_map.update(batch_result)
            except LLMCallFailed:
                for r in batch:
                    llm_failed_row_keys.add(r.get("row_key"))
                logger.warning(
                    "Classification batch of %d rows marked llm_failed for job %s",
                    len(batch), job_id,
                )

        # --- Persist transactions ---
        for idx, row in clean_df.iterrows():
            txn_id = row["txn_id"]
            needs_llm = row["category"] == "Uncategorised"
            llm_category = category_map.get(idx) if needs_llm else None
            # Failed if this row needed classification but never got a category back,
            # whether because its batch raised LLMCallFailed or the LLM's response
            # simply omitted this row_key.
            llm_failed = needs_llm and llm_category is None
            txn = Transaction(
                job_id=job.id,
                txn_id=_clean_value(txn_id),
                date=_clean_value(row["date"]),
                merchant=_clean_value(row["merchant"]),
                amount=_clean_value(row["amount"]),
                currency=_clean_value(row["currency"]),
                status=_clean_value(row["status"]),
                category=_clean_value(llm_category or row["category"]),
                account_id=_clean_value(row["account_id"]),
                notes=_clean_value(row["notes"]),
                is_anomaly=bool(row["is_anomaly"]),
                anomaly_reason=_clean_value(row["anomaly_reason"]),
                llm_category=_clean_value(llm_category),
                llm_failed=bool(llm_failed),
            )
            db.add(txn)
        db.commit()

        # Apply LLM classification results back onto the dataframe itself - the
        # Transaction rows above already got the corrected category, but clean_df
        # still holds the original pre-classification values. Without this update,
        # every stat computed below (category_breakdown, narrative stats) would be
        # calculated against stale "Uncategorised" rows even though those rows were
        # successfully classified.
        for idx, cat in category_map.items():
            clean_df.at[idx, "category"] = cat

        # --- d) LLM narrative summary (single call, ground-truth stats precomputed) ---
        inr_total = float(clean_df.loc[clean_df["currency"] == "INR", "amount"].sum())
        usd_total = float(clean_df.loc[clean_df["currency"] == "USD", "amount"].sum())
        top_merchants = (
            clean_df.groupby("merchant")["amount"].sum()
            .sort_values(ascending=False)
            .head(3)
            .index.tolist()
        )
        anomaly_count = int(clean_df["is_anomaly"].sum())
        category_breakdown = clean_df.groupby("category")["amount"].sum().to_dict()

        stats = {
            "total_spend_inr": inr_total,
            "total_spend_usd": usd_total,
            "top_merchants": top_merchants,
            "anomaly_count": anomaly_count,
            "category_breakdown": category_breakdown,
        }

        narrative_data = {
            "total_spend_inr": inr_total,
            "total_spend_usd": usd_total,
            "top_merchants": top_merchants,
            "anomaly_count": anomaly_count,
            "narrative": None,
            "risk_level": None,
        }
        try:
            llm_summary = generate_narrative_summary(stats)
            narrative_data.update(llm_summary)
        except LLMCallFailed:
            narrative_data["narrative"] = (
                "Narrative generation failed after retries; showing computed stats only."
            )
            narrative_data["risk_level"] = "unknown"

        summary = JobSummary(
            job_id=job.id,
            total_spend_inr=narrative_data.get("total_spend_inr", inr_total),
            total_spend_usd=narrative_data.get("total_spend_usd", usd_total),
            top_merchants=narrative_data.get("top_merchants", top_merchants),
            anomaly_count=narrative_data.get("anomaly_count", anomaly_count),
            narrative=narrative_data.get("narrative"),
            risk_level=narrative_data.get("risk_level"),
        )
        db.add(summary)

        job.status = JobStatus.completed
        from datetime import datetime, timezone
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.failed
            job.error_message = str(exc)
            db.commit()
    finally:
        db.close()
