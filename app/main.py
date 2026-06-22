import os
import uuid
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, Base, engine
from app.models import Job, Transaction, JobSummary, JobStatus
from app.schemas import (
    JobUploadResponse, JobStatusResponse, JobResultsResponse,
    JobOut, TransactionOut,
)
from app.celery_app import celery_app

app = FastAPI(title="AI-Powered Transaction Processing Pipeline")

os.makedirs(settings.upload_dir, exist_ok=True)


@app.on_event("startup")
def on_startup():
    # Tables are also managed by Alembic migrations (see alembic/versions).
    # create_all is kept as a safety net for first-run convenience.
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/jobs/upload", response_model=JobUploadResponse)
def upload_job(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    job_id = uuid.uuid4()
    dest_path = os.path.join(settings.upload_dir, f"{job_id}.csv")

    contents = file.file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    with open(dest_path, "wb") as f:
        f.write(contents)

    job = Job(id=job_id, filename=file.filename, status=JobStatus.pending)
    db.add(job)
    db.commit()

    celery_app.send_task("worker.tasks.process_job", args=[str(job_id), dest_path])

    return JobUploadResponse(job_id=job_id, status=job.status.value)


@app.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    summary_dict = None
    if job.status == JobStatus.completed and job.summary:
        summary_dict = {
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "top_merchants": job.summary.top_merchants,
            "anomaly_count": job.summary.anomaly_count,
            "risk_level": job.summary.risk_level,
        }

    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        error_message=job.error_message,
        summary=summary_dict,
    )


@app.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
def get_job_results(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.completed:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not completed yet (status={job.status.value})",
        )

    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    anomalies = [t for t in transactions if t.is_anomaly]

    breakdown = {}
    for t in transactions:
        cat = t.category or "Uncategorised"
        breakdown[cat] = breakdown.get(cat, 0) + (t.amount or 0)

    narrative = None
    if job.summary:
        narrative = {
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "top_merchants": job.summary.top_merchants,
            "anomaly_count": job.summary.anomaly_count,
            "narrative": job.summary.narrative,
            "risk_level": job.summary.risk_level,
        }

    return JobResultsResponse(
        job_id=job.id,
        status=job.status.value,
        transactions=[TransactionOut.model_validate(t) for t in transactions],
        anomalies=[TransactionOut.model_validate(t) for t in anomalies],
        category_breakdown=breakdown,
        narrative_summary=narrative,
    )


@app.get("/jobs", response_model=list[JobOut])
def list_jobs(
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Job)
    if status:
        try:
            status_enum = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        q = q.filter(Job.status == status_enum)
    jobs = q.order_by(Job.created_at.desc()).all()
    return jobs
