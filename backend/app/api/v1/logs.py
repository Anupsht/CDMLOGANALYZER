"""Log upload / query endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.logging import log_operation
from app.models.log_file import LogLine
from app.schemas.log_file import (
    LogFileCreateResult,
    LogFileOut,
    LogFileStatusOut,
    LogLineOut,
    SourceDetectionOut,
)
from app.schemas.common import ListResponse
from app.services.audit_service import audit_service
from app.services.upload_service import upload_service
from app.tasks import get_task_queue
from app.tasks.queue import TASK_PROCESS_UPLOAD

router = APIRouter(prefix="/logs", tags=["logs"])

logger = logging.getLogger(__name__)


def _to_out(row) -> LogFileOut:
    """Convert a LogFile row to the API schema (source expanded)."""
    from sqlalchemy import inspect as sa_inspect

    # Column attributes only — relationship objects are populated explicitly
    # below so ORM objects never leak into the response schema.
    data = {attr.key: getattr(row, attr.key) for attr in sa_inspect(row).mapper.column_attrs}
    out = LogFileOut.model_validate(data)
    if row.log_source is not None:
        out.log_source = SourceDetectionOut(
            code=row.log_source.code,
            name=row.log_source.name,
            confidence=row.source_confidence,
            method=row.detection_method,
        )
    if row.machine_model is not None:
        out.machine_model_code = row.machine_model.code
    return out


@router.post("/upload", response_model=LogFileCreateResult, status_code=201)
async def upload_log(
    file: UploadFile = File(..., description="Log file (.txt, .log, .csv, .json) or ZIP archive"),
    machine_id: str | None = Form(default=None),
    model_code: str | None = Form(default=None, description="Machine model code, e.g. P2600N"),
    session: Session = Depends(get_db),
) -> LogFileCreateResult:
    """Accept a log file or archive, store it safely, and start processing."""
    row = upload_service.create_upload(
        session, file, machine_id=machine_id, model_code=model_code
    )
    audit_service.record(
        session,
        action="upload.created",
        entity_type="log_file",
        entity_id=row.id,
        detail={
            "log_filename": row.original_filename,
            "size_bytes": row.size_bytes,
            "checksum": row.checksum_sha256,
            "duplicate_of": row.duplicate_of_id,
        },
    )
    session.commit()

    # Kick off background processing (pipeline updates status progressively).
    get_task_queue().enqueue(TASK_PROCESS_UPLOAD, row.id)
    log_operation(
        logging.INFO,
        operation="api.upload",
        message=f"Upload accepted: {row.original_filename}",
        file_id=row.id,
    )

    # With the eager queue the pipeline already finished — reload the row so
    # the response reflects the final status.
    session.expire(row)
    result = LogFileCreateResult.model_validate(_to_out(row))
    result.is_duplicate = row.duplicate_of_id is not None
    return result


@router.get("", response_model=ListResponse[LogFileOut])
def list_logs(
    status: str | None = Query(default=None, description="Filter by processing status"),
    source: str | None = Query(default=None, description="Filter by detected log source code"),
    machine_id: str | None = Query(default=None),
    file_role: str | None = Query(default=None, description="upload | extracted"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ListResponse[LogFileOut]:
    items, total = upload_service.list(
        session,
        status=status,
        source=source,
        machine_id=machine_id,
        file_role=file_role,
        limit=limit,
        offset=offset,
    )
    return ListResponse(
        items=[_to_out(row) for row in items], total=total, limit=limit, offset=offset
    )


@router.get("/{file_id}", response_model=LogFileOut)
def get_log(file_id: str, session: Session = Depends(get_db)) -> LogFileOut:
    row = upload_service.get(session, file_id)
    out = _to_out(row)
    return out


@router.get("/{file_id}/status", response_model=LogFileStatusOut)
def get_log_status(file_id: str, session: Session = Depends(get_db)) -> LogFileStatusOut:
    """Live processing status, including per-file status for archives."""
    row = upload_service.get(session, file_id)

    def build(item) -> LogFileStatusOut:
        return LogFileStatusOut(
            id=item.id,
            original_filename=item.original_filename,
            status=item.status,
            status_message=item.status_message,
            line_count=item.line_count,
            processing_started_at=item.processing_started_at,
            processing_finished_at=item.processing_finished_at,
            files=[build(child) for child in item.children],
        )

    return build(row)


@router.get("/{file_id}/lines", response_model=ListResponse[LogLineOut])
def get_log_lines(
    file_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ListResponse[LogLineOut]:
    """Raw stored lines (evidence trace). Original text is never modified."""
    row = upload_service.get(session, file_id)
    query = session.query(LogLine).filter(LogLine.log_file_id == row.id)
    total = query.count()
    lines = query.order_by(LogLine.line_number.asc()).offset(offset).limit(limit).all()
    return ListResponse(items=lines, total=total, limit=limit, offset=offset)
