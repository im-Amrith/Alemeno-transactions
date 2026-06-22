import json
import logging

from groq import Groq
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

from app.config import settings

logger = logging.getLogger(__name__)

VALID_CATEGORIES = [
    "Food", "Shopping", "Travel", "Transport",
    "Utilities", "Cash Withdrawal", "Entertainment", "Other",
]

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


class LLMCallFailed(Exception):
    """Raised after all retries are exhausted for a single LLM call."""


def _extract_json(text: str):
    """Groq sometimes wraps JSON in markdown fences; strip them before parsing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


@retry(
    stop=stop_after_attempt(settings.llm_max_retries),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((json.JSONDecodeError, ValueError, ConnectionError, TimeoutError, Exception)),
    reraise=True,
)
def _call_groq(prompt: str, system: str) -> str:
    client = get_client()
    completion = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=2000,
    )
    return completion.choices[0].message.content


def classify_batch(rows: list[dict]) -> dict:
    """Classify a batch of transactions (each needs row_key + merchant + notes + amount).

    `row_key` must be a value the caller can use to map results back to its own
    rows (e.g. a stable dataframe index) - txn_id is NOT used for this because
    several rows in the source data have a missing/blank txn_id, and using it
    as a dict key would collide multiple rows onto the same key.

    Returns a dict mapping row_key -> category string.
    Raises LLMCallFailed if all retries are exhausted - caller should mark the
    batch as llm_failed and continue, not crash the whole job.
    """
    system = (
        "You are a financial transaction classifier. Given a JSON list of "
        "transactions, assign exactly one category to each from this fixed list: "
        f"{', '.join(VALID_CATEGORIES)}. "
        "Respond with ONLY a JSON array of objects: "
        '[{"row_key": <same row_key value you were given, unchanged>, "category": "..."}]. '
        "No prose, no markdown fences. Every input row_key must appear exactly once in your output."
    )
    payload = [
        {
            "row_key": r.get("row_key"),
            "merchant": r.get("merchant"),
            "notes": r.get("notes"),
            "amount": r.get("amount"),
        }
        for r in rows
    ]
    prompt = json.dumps(payload)

    try:
        raw = _call_groq(prompt, system)
        parsed = _extract_json(raw)
        result = {}
        for item in parsed:
            cat = item.get("category")
            if cat not in VALID_CATEGORIES:
                cat = "Other"
            result[item.get("row_key")] = cat
        return result
    except Exception as exc:
        logger.warning("Classification batch failed after retries: %s", exc)
        raise LLMCallFailed(str(exc)) from exc


def generate_narrative_summary(stats: dict) -> dict:
    """Single LLM call producing the structured narrative summary.

    `stats` should contain precomputed totals so the LLM only has to narrate,
    not do arithmetic: total_spend_inr, total_spend_usd, top_merchants,
    anomaly_count, currency_breakdown, category_breakdown.
    """
    system = (
        "You are a financial analyst writing a short structured summary. "
        "Respond with ONLY a JSON object with these exact keys: "
        '"total_spend_inr" (number), "total_spend_usd" (number), '
        '"top_merchants" (array of up to 3 strings), '
        '"anomaly_count" (integer), '
        '"narrative" (2-3 sentence plain-English summary of spending patterns), '
        '"risk_level" (one of "low", "medium", "high"). '
        "No prose, no markdown fences. Use the provided stats as ground truth; "
        "do not recompute totals yourself."
    )
    prompt = json.dumps(stats)

    try:
        raw = _call_groq(prompt, system)
        parsed = _extract_json(raw)
        return parsed
    except Exception as exc:
        logger.warning("Narrative summary call failed after retries: %s", exc)
        raise LLMCallFailed(str(exc)) from exc
