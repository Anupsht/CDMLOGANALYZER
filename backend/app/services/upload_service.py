"""Upload service: validation, storage, metadata, duplicate detection."""

from __future__ import annotations

import logging
import uuid

from fastapi import UploadFile
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError, UnsupportedFileTypeError, ValidationError
from app.models.log_file import LogFile
from app.models.machine import Machine, MachineModel
from app.utils.checksums import sha256_file
from app.utils.file_storage import FileStorage, sanitize_filename

logger = logging.getLogger(__name__)


class UploadService:
    def __init__(self, storage: FileStorage | None = None) -> None:
        self.storage = storage or FileStorage()

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------
    def create_upload(
        self,
        session: Session,
        upload: UploadFile,
        *,
        machine_id: str | None = None,
        model_code: str | None = None,
    ) -> LogFile:
        settings = get_settings()
        original_name = upload.filename or "unnamed"
        extension = self._extension_of(original_name)

        # 1) extension validation (settings store dotted forms: ".log", ".zip", …)
        allowed_no_dot = {e.lstrip(".").lower() for e in settings.allowed_extensions}
        if extension not in allowed_no_dot:
            raise UnsupportedFileTypeError(
                f"File type '{extension or '(none)'}' is not allowed. "
                f"Allowed: {', '.join(sorted(settings.allowed_extensions))}"
            )

        # 2) optional fleet links
        machine = None
        if machine_id:
            machine = session.get(Machine, machine_id)
            if machine is None:
                raise NotFoundError(f"Machine not found: {machine_id}")
        machine_model = None
        if model_code:
            machine_model = (
                session.query(MachineModel).filter(MachineModel.code == model_code.upper()).one_or_none()
            )
            if machine_model is None:
                raise NotFoundError(f"Unknown machine model: {model_code}")
        if machine_model is None and machine is not None:
            machine_model = machine.machine_model

        # 3) unique storage id + streaming save (validates size, checksums)
        file_id = str(uuid.uuid4())
        upload.file.seek(0)
        relative_path, size, checksum = self.storage.save_stream(
            upload.file,
            file_id=file_id,
            original_filename=original_name,
            max_bytes=settings.max_upload_size_bytes,
        )

        # 4) duplicate detection (same checksum among earlier uploads)
        duplicate_of = (
            session.query(LogFile)
            .filter(
                LogFile.checksum_sha256 == checksum,
                LogFile.file_role == "upload",
                LogFile.duplicate_of_id.is_(None),
            )
            .order_by(LogFile.created_at.asc())
            .first()
        )
        duplicate_of_id = duplicate_of.id if duplicate_of and duplicate_of.id != file_id else None

        # 5) metadata record
        row = LogFile(
            id=file_id,
            original_filename=sanitize_filename(original_name, max_length=255),
            stored_filename=self.storage.stored_name(file_id, original_name),
            file_path=relative_path,
            file_type=extension or "bin",
            mime_type=upload.content_type,
            size_bytes=size,
            checksum_sha256=checksum,
            file_role="upload",
            machine_id=machine.id if machine else None,
            machine_model_id=machine_model.id if machine_model else None,
            status="UPLOADED",
            duplicate_of_id=duplicate_of_id,
        )
        session.add(row)
        session.flush()

        logger.info(
            "Upload stored",
            extra={
                "operation": "upload.create",
                "file_id": row.id,
                "log_filename": row.original_filename,
                "size_bytes": size,
                "checksum": checksum[:12],
                "duplicate_of": duplicate_of_id,
            },
        )
        return row

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    def get(self, session: Session, file_id: str) -> LogFile:
        row = session.get(LogFile, file_id)
        if row is None:
            raise NotFoundError(f"Log file not found: {file_id}")
        return row

    def list(
        self,
        session: Session,
        *,
        status: str | None = None,
        source: str | None = None,
        machine_id: str | None = None,
        file_role: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LogFile], int]:
        query = session.query(LogFile)
        if status:
            query = query.filter(LogFile.status == status.upper())
        if machine_id:
            query = query.filter(LogFile.machine_id == machine_id)
        if file_role:
            query = query.filter(LogFile.file_role == file_role)
        if source:
            from app.models.log_file import LogSource

            query = query.join(LogSource, LogFile.log_source_id == LogSource.id).filter(
                LogSource.code == source.lower()
            )
        total = query.count()
        items = (
            query.order_by(sa_func.coalesce(LogFile.created_at, sa_func.now()).desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extension_of(filename: str) -> str:
        name = sanitize_filename(filename)
        return name.rpartition(".")[2].lower() if "." in name else ""

    def verify_integrity(self, row: LogFile) -> bool:
        """Recompute the checksum of a stored file (pipeline validation)."""
        try:
            path = self.storage.resolve(row.file_path)
        except Exception:
            return False
        if not path.exists() or path.stat().st_size != row.size_bytes:
            return False
        return sha256_file(path) == row.checksum_sha256


upload_service = UploadService()
