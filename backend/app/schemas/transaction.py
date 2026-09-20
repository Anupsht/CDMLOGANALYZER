"""Transaction API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TransactionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    transaction_id: str
    machine_id: str | None = None
    machine_model_id: str | None = None
    model_code: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    amount: float | None = None
    currency: str | None = None
    status: str
    correlation_confidence: float
    correlation_method: str | None = None
    source_file_id: str | None = None
    created_at: datetime


class TransactionDetailOut(TransactionOut):
    stages_confirmed: list[str] = []
    complete: bool = False


class RawEvidenceOut(BaseModel):
    file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None


class TimelineEntryOut(BaseModel):
    timestamp: datetime | None = None
    event: str
    stage: str | None = None
    device: str | None = None
    severity: str = "INFO"
    source: str | None = None
    detail: dict | list | None = None
    not_confirmed: bool = False
    raw: RawEvidenceOut | None = None


class TimelineOut(BaseModel):
    transaction: TransactionOut
    entries: list[TimelineEntryOut]
    not_confirmed_stages: list[TimelineEntryOut]
    stages_confirmed: list[str]
    stages_not_confirmed: list[str] = []
    complete: bool
