"""Log file / log line schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.log_file import PROCESSING_STATUSES


class SourceDetectionOut(BaseModel):
    code: str
    name: str | None = None
    confidence: float | None = None
    method: str | None = None


class LogFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    stored_filename: str
    file_type: str
    file_role: str
    size_bytes: int
    checksum_sha256: str
    mime_type: str | None = None
    status: str
    status_message: str | None = None
    parent_file_id: str | None = None
    original_path: str | None = None
    machine_id: str | None = None
    machine_model_id: str | None = None
    machine_model_code: str | None = None
    log_source: SourceDetectionOut | None = None
    parser_code: str | None = None
    parser_version: str | None = None
    line_count: int | None = None
    duplicate_of_id: str | None = None
    created_at: datetime
    updated_at: datetime
    processing_started_at: datetime | None = None
    processing_finished_at: datetime | None = None


class LogFileCreateResult(LogFileOut):
    """Response of the upload endpoint — includes duplicate detection info."""

    is_duplicate: bool = False
    duplicate_of_id: str | None = None


class LogFileStatusOut(BaseModel):
    id: str
    original_filename: str
    status: str
    status_message: str | None = None
    line_count: int | None = None
    processing_started_at: datetime | None = None
    processing_finished_at: datetime | None = None
    files: list["LogFileStatusOut"] = []


class LogLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    log_file_id: str
    line_number: int
    raw_text: str
    timestamp: datetime | None = None
    source: str | None = None
    level: str | None = None
    normalized_data: dict | list | None = None
    created_at: datetime


LogFileStatusOut.model_rebuild()
