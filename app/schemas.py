import uuid
from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel


class JobOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    row_count_raw: Optional[int] = None
    row_count_clean: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class JobUploadResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class JobStatusResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    row_count_raw: Optional[int] = None
    row_count_clean: Optional[int] = None
    error_message: Optional[str] = None
    summary: Optional[dict] = None


class TransactionOut(BaseModel):
    txn_id: Optional[str]
    date: Optional[str]
    merchant: Optional[str]
    amount: Optional[float]
    currency: Optional[str]
    status: Optional[str]
    category: Optional[str]
    account_id: Optional[str]
    notes: Optional[str]
    is_anomaly: bool
    anomaly_reason: Optional[str]
    llm_category: Optional[str]
    llm_failed: bool

    class Config:
        from_attributes = True


class JobResultsResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    transactions: List[TransactionOut]
    anomalies: List[TransactionOut]
    category_breakdown: dict
    narrative_summary: Optional[dict] = None
