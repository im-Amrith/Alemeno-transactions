import pandas as pd
import pytest

from worker.cleaning import parse_date, parse_amount, clean_dataframe, detect_anomalies


def test_parse_date_formats():
    assert parse_date("04-09-2024") == "2024-09-04"
    assert parse_date("2024/02/05") == "2024-02-05"
    assert parse_date("2024-07-15") == "2024-07-15"
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date("not-a-date") is None


def test_parse_amount_strips_dollar_sign():
    assert parse_amount("$11325.79") == 11325.79
    assert parse_amount("10882.55") == 10882.55
    assert parse_amount(423.91) == 423.91
    assert parse_amount("") is None


def test_clean_dataframe_drops_exact_duplicates():
    df = pd.DataFrame([
        {"txn_id": "T1", "date": "04-09-2024", "merchant": "A", "amount": "10",
         "currency": "inr", "status": "success", "category": "", "account_id": "ACC1", "notes": ""},
        {"txn_id": "T1", "date": "04-09-2024", "merchant": "A", "amount": "10",
         "currency": "inr", "status": "success", "category": "", "account_id": "ACC1", "notes": ""},
    ])
    cleaned = clean_dataframe(df)
    assert len(cleaned) == 1


def test_clean_dataframe_normalises_fields():
    df = pd.DataFrame([
        {"txn_id": "T1", "date": "2024/02/05", "merchant": "Swiggy", "amount": "$100",
         "currency": "inr", "status": "success", "category": "", "account_id": "ACC1", "notes": ""},
    ])
    cleaned = clean_dataframe(df)
    row = cleaned.iloc[0]
    assert row["date"] == "2024-02-05"
    assert row["amount"] == 100.0
    assert row["currency"] == "INR"
    assert row["status"] == "SUCCESS"
    assert row["category"] == "Uncategorised"


def test_detect_anomalies_flags_statistical_outlier():
    df = pd.DataFrame([
        {"merchant": "A", "amount": 100.0, "currency": "INR", "account_id": "ACC1"},
        {"merchant": "B", "amount": 110.0, "currency": "INR", "account_id": "ACC1"},
        {"merchant": "C", "amount": 1000.0, "currency": "INR", "account_id": "ACC1"},  # >3x median
    ])
    flagged = detect_anomalies(df)
    assert flagged.iloc[2]["is_anomaly"] == True
    assert "3x" in flagged.iloc[2]["anomaly_reason"]
    assert flagged.iloc[0]["is_anomaly"] == False


def test_detect_anomalies_flags_usd_domestic_merchant():
    df = pd.DataFrame([
        {"merchant": "Swiggy", "amount": 500.0, "currency": "USD", "account_id": "ACC1"},
        {"merchant": "Amazon", "amount": 500.0, "currency": "USD", "account_id": "ACC1"},
    ])
    flagged = detect_anomalies(df)
    assert flagged.iloc[0]["is_anomaly"] == True
    assert "domestic" in flagged.iloc[0]["anomaly_reason"]
    assert flagged.iloc[1]["is_anomaly"] == False
