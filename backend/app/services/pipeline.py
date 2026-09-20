"""Upload processing pipeline.

    UPLOAD → VALIDATE → STORE → EXTRACT → IDENTIFY FILES
           → IDENTIFY LOG SOURCE → SELECT PARSER → PARSE → STORE RAW DATA

Phase 1 scope only: raw storage + identification + generic parsing.
Transaction correlation and diagnosis are later phases.

The pipeline runs inside a background task (Celery worker, or the
in-process inline queue when Redis is not configured). Status updates
are committed per stage so ``GET /api/logs/{id}/status`` reflects live
progress.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ArchiveError
from app.core.registry import model_registry
from app.database.session import database
from app.models.log_file import LogFile, LogLine, LogSource
from app.parsers.base import FileContext
from app.parsers.registry import parser_registry
from app.services import audit_service, detection_service, upload_service
from app.services.zip_service import zip_extractor
from app.utils.file_storage import FileStorage

logger = logging.getLogger(__name__)

# Extensions considered processable logs; anything else extracted from a
# ZIP is preserved for evidence but not parsed. (.jou = GRG journal log.)
PROCESSABLE_EXTENSIONS = {"txt", "log", "csv", "json", "jou"}

_LINE_BATCH = 1000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def run_pipeline(file_id: str) -> dict:
    """Process an uploaded file end-to-end. Returns a status summary."""
    settings = get_settings()
    storage = FileStorage(settings.storage_dir)
    started = _utcnow()

    session = database.get_session()
    try:
        row = session.get(LogFile, file_id)
        if row is None:
            raise RuntimeError(f"Pipeline started for unknown file: {file_id}")
        if row.is_terminal:
            return summarize(row)  # idempotent re-runs

        logger.info(
            "Pipeline started",
            extra={"operation": "pipeline.start", "file_id": file_id, "log_filename": row.original_filename},
        )

        try:
            _validate(session, row, storage)
            children = _extract(session, row, storage)
            results = []
            for child in children:
                try:
                    results.append(_identify_and_parse(session, child, storage))
                except Exception as exc:
                    logger.exception(
                        "File processing failed", extra={"operation": "pipeline.file", "file_id": child.id}
                    )
                    _set_status(session, child, "FAILED", f"{type(exc).__name__}: {exc}")
                    results.append(False)

            # Overall status for the upload (parent for ZIPs).
            if all(results):
                final = "COMPLETED"
            elif any(results):
                final = "PARTIAL"
            else:
                final = "FAILED"
            processed = sum(1 for ok in results if ok)
            _set_status(
                session,
                row,
                final,
                f"{processed}/{len(results)} file(s) processed successfully",
            )
            row.processing_finished_at = _utcnow()
            session.commit()

            audit_service.record(
                session,
                action="upload.processed",
                entity_type="log_file",
                entity_id=row.id,
                detail={"status": final, "files": len(results)},
            )
            session.commit()
            logger.info(
                "Pipeline finished",
                extra={
                    "operation": "pipeline.finish",
                    "file_id": file_id,
                    "status": final,
                    "files": len(results),
                    "duration_ms": (_utcnow() - started).total_seconds() * 1000,
                },
            )
            row_final = session.get(LogFile, file_id)
            return summarize(row_final)
        except ArchiveError as exc:
            _fail(session, row, str(exc))
            return summarize(row)
        except Exception as exc:
            logger.exception("Pipeline crashed", extra={"operation": "pipeline.crash", "file_id": file_id})
            _fail(session, row, f"{type(exc).__name__}: {exc}")
            return summarize(row)
    finally:
        session.close()


def summarize(row: LogFile | None) -> dict:
    if row is None:
        return {"id": None, "status": "FAILED", "status_message": "unknown file"}
    return {
        "id": row.id,
        "status": row.status,
        "status_message": row.status_message,
        "line_count": row.line_count,
    }


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------


def _set_status(session: Session, row: LogFile, status: str, message: str | None = None) -> None:
    row.status = status
    if message is not None:
        row.status_message = message
    session.commit()


def _fail(session: Session, row: LogFile, message: str) -> None:
    """Mark failed even if the session is dirty."""
    session.rollback()
    fresh = session.get(LogFile, row.id)
    if fresh is not None:
        fresh.status = "FAILED"
        fresh.status_message = message
        fresh.processing_finished_at = _utcnow()
        session.commit()


def _validate(session: Session, row: LogFile, storage: FileStorage) -> None:
    _set_status(session, row, "VALIDATING")
    row.processing_started_at = row.processing_started_at or _utcnow()
    session.commit()

    if not upload_service.verify_integrity(row):
        raise RuntimeError(
            "Stored file failed integrity validation (missing, truncated, or checksum mismatch)."
        )


def _extract(session: Session, row: LogFile, storage: FileStorage) -> list[LogFile]:
    """EXTRACT stage: for ZIPs, materialize children. Returns process targets."""
    if row.file_type != "zip":
        return [row]

    _set_status(session, row, "EXTRACTING")
    zip_path = storage.resolve(row.file_path)
    members = zip_extractor.extract(zip_path)  # original zip is never modified

    children: list[LogFile] = []
    for member in members:
        file_id = str(uuid.uuid4())
        rel_path, size, checksum = storage.save_bytes(
            member.data,
            subdir="extracted",
            file_id=file_id,
            original_filename=member.filename,
        )
        ext = member.filename.rpartition(".")[2].lower() if "." in member.filename else ""
        child = LogFile(
            id=file_id,
            original_filename=member.filename,
            stored_filename=storage.stored_name(file_id, member.filename),
            file_path=rel_path,
            file_type=ext or "bin",
            size_bytes=size,
            checksum_sha256=checksum,
            file_role="extracted",
            parent_file_id=row.id,
            original_path=member.original_path,
            machine_id=row.machine_id,
            machine_model_id=row.machine_model_id,
            status="UPLOADED",
        )
        session.add(child)
        children.append(child)
    session.commit()
    logger.info(
        "Extraction complete",
        extra={"operation": "pipeline.extract", "file_id": row.id, "children": len(children)},
    )
    return children


def _identify_and_parse(session: Session, row: LogFile, storage: FileStorage) -> bool:
    """IDENTIFY + PARSE stages for a single (stored) file."""
    # Non-log payloads extracted from archives are preserved, not parsed.
    if row.file_type not in PROCESSABLE_EXTENSIONS:
        _set_status(
            session,
            row,
            "COMPLETED",
            "Stored for evidence only (not a recognized log format).",
        )
        return True
    if row.file_type == "zip":
        _set_status(session, row, "COMPLETED", "Nested archive stored; recursive extraction is a future phase.")
        return True

    _set_status(session, row, "IDENTIFYING")
    path = storage.resolve(row.file_path)
    ctx = FileContext.from_path(
        path, hints={"original_path": row.original_path, "log_file_id": row.id}
    )
    if row.original_filename:
        ctx.filename = row.original_filename

    # ---- log source identification ----
    detection = detection_service.detect(ctx)
    source_row = _get_or_create_source(session, detection.source_code)
    row.log_source_id = source_row.id
    row.source_confidence = detection.confidence
    row.detection_method = detection.method
    session.commit()

    # ---- machine model detection (registry-driven, never hard-coded) ----
    if row.machine_model_id is None:
        adapters = [
            adapter for adapter in model_registry if model_registry.is_enabled(adapter.code)
        ]
        model_code, confidence, method = detection_service.detect_model(ctx, adapters)
        if model_code:
            from app.models.machine import MachineModel

            model_row = (
                session.query(MachineModel).filter(MachineModel.code == model_code).one_or_none()
            )
            if model_row is not None and model_row.is_active:
                row.machine_model_id = model_row.id
                logger.info(
                    "Model detected",
                    extra={
                        "operation": "pipeline.model_detect",
                        "file_id": row.id,
                        "model_code": model_code,
                        "confidence": confidence,
                        "method": method,
                    },
                )
    session.commit()

    # ---- parser selection ----
    _set_status(session, row, "PARSING")
    adapter = model_registry.get_model(
        row.machine_model.code if row.machine_model else ""
    )
    preferred: list[str] = []
    if adapter is not None:
        hint = adapter.get_parser(ctx)
        preferred = [hint.code] if hint is not None else []
    parser = parser_registry.select(ctx, preferred_codes=preferred)

    result = parser.parse_file(ctx)
    _store_lines(session, row, result, source_code=source_row.code)

    row.parser_code = parser.code
    row.parser_version = parser.version
    row.line_count = len(result.lines)

    if result.errors:
        error_sample = "; ".join(result.errors[:3])
        _set_status(
            session,
            row,
            "PARTIAL",
            f"Parsed with {len(result.errors)} line error(s): {error_sample}",
        )
    else:
        _set_status(
            session,
            row,
            "COMPLETED",
            f"Parsed {row.line_count} line(s) with {parser.code}@{parser.version}",
        )
    return row.status != "FAILED"


def _get_or_create_source(session: Session, code: str) -> LogSource:
    source = session.query(LogSource).filter(LogSource.code == code).one_or_none()
    if source is None:
        source = LogSource(
            code=code,
            name=code.upper(),
            description="Registered automatically during detection.",
        )
        session.add(source)
        session.flush()
    return source


def _store_lines(session: Session, row: LogFile, result, *, source_code: str) -> None:
    batch: list[LogLine] = []
    for parsed in result.lines:
        # Prefer the *detected* source; fall back to the parser's own type.
        line_source = (
            source_code
            if source_code and source_code != "unknown"
            else (parsed.source or source_code)
        )
        batch.append(
            LogLine(
                log_file_id=row.id,
                line_number=parsed.line_number,
                raw_text=parsed.raw_text,
                timestamp=parsed.timestamp,
                source=line_source,
                level=parsed.level,
                normalized_data=parsed.normalized or None,
            )
        )
        if len(batch) >= _LINE_BATCH:
            session.add_all(batch)
            session.commit()
            batch.clear()
    if batch:
        session.add_all(batch)
        session.commit()
