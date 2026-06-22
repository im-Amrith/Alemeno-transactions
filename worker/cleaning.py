import re
from datetime import datetime

import pandas as pd

REQUIRED_COLUMNS = [
    "txn_id", "date", "merchant", "amount", "currency",
    "status", "category", "account_id", "notes",
]

DOMESTIC_ONLY_MERCHANTS = {"swiggy", "ola", "irctc"}

# Order matters: try the most specific/unambiguous patterns first.
_DATE_FORMATS = [
    "%Y-%m-%d",   # ISO 8601, e.g. 2024-07-15
    "%Y/%m/%d",   # e.g. 2024/02/05
    "%d-%m-%Y",   # e.g. 04-09-2024
]


def parse_date(raw: str) -> str | None:
    """Normalise a mixed-format date string to ISO 8601 (YYYY-MM-DD)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None  # unparseable - left null rather than guessed


def parse_amount(raw) -> float | None:
    """Strip currency symbols/whitespace and coerce to float."""
    if pd.isna(raw):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = re.sub(r"[^0-9.\-]", "", str(raw))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all required cleaning steps and return a fresh, cleaned dataframe.

    Steps (per assignment spec):
      - normalise dates to ISO 8601
      - strip currency symbols from amount
      - uppercase status
      - uppercase currency (normalises 'inr' -> 'INR' casing too)
      - fill missing category with 'Uncategorised'
      - drop exact duplicate rows
    """
    df = df.copy()

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Drop exact duplicate rows first (on raw values, before mutation)
    df = df.drop_duplicates(keep="first").reset_index(drop=True)

    df["date"] = df["date"].apply(parse_date)
    df["amount"] = df["amount"].apply(parse_amount)
    df["currency"] = df["currency"].apply(
        lambda v: v.strip().upper() if isinstance(v, str) and v.strip() else None
    )
    df["status"] = df["status"].apply(
        lambda v: v.strip().upper() if isinstance(v, str) and v.strip() else None
    )
    df["category"] = df["category"].apply(
        lambda v: v.strip() if isinstance(v, str) and v.strip() else "Uncategorised"
    )
    df["txn_id"] = df["txn_id"].apply(
        lambda v: v.strip() if isinstance(v, str) and v.strip() else None
    )
    df["merchant"] = df["merchant"].apply(
        lambda v: v.strip() if isinstance(v, str) and v.strip() else None
    )
    df["notes"] = df["notes"].apply(
        lambda v: v.strip() if isinstance(v, str) and v.strip() else None
    )

    return df


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Flag statistical outliers (>3x account median) and domestic-currency mismatches.

    A row can carry both reasons; they are joined with '; '.
    """
    df = df.copy()
    df["is_anomaly"] = False
    df["anomaly_reason"] = None

    # Rule 1: amount > 3x account median (median computed per account_id, on valid amounts)
    medians = df.groupby("account_id")["amount"].median()
    for idx, row in df.iterrows():
        reasons = []
        acc_median = medians.get(row["account_id"])
        if acc_median and row["amount"] and row["amount"] > 3 * acc_median:
            reasons.append("amount exceeds 3x account median")

        merchant_lower = str(row["merchant"]).strip().lower() if row["merchant"] else ""
        if row["currency"] == "USD" and merchant_lower in DOMESTIC_ONLY_MERCHANTS:
            reasons.append("USD currency on domestic-only merchant")

        if reasons:
            df.at[idx, "is_anomaly"] = True
            df.at[idx, "anomaly_reason"] = "; ".join(reasons)

    return df
