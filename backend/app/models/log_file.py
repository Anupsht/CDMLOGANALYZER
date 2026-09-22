"""Log ingestion models: sources, uploaded/extracted files, raw log lines.

``log_files`` stores both original uploads (``file_role='upload'``) and
files extracted from ZIP archives (``file_role='extracted'``, with
``parent_file_id`` and ``original_path`` recording provenance).

``log_lines`` stores the immutable raw text of every line so future
phases can trace any derived transaction/event back to original
evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, BigIntegerPrimaryKeyMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.machine import Machine, MachineModel

# Processing lifecycle (section 12 of the Phase 1 spec; CORRELATING added in Phase 3).
PROCESSING_STATUSES = (
    "UPLOADED",
    "VALIDATING",
    "EXTRACTING",
    "IDENTIFYING",
    "PARSING",
    "CORRELATING",
    "COMPLETED",
    "PARTIAL",
    "FAILED",
)

# Terminal vs in-flight statuses.
TERMINAL_STATUSES = ("COMPLETED", "PARTIAL", "FAILED")

FILE_ROLES = ("upload", "extracted")

TEXT_FILE_TYPES = ("txt", "log", "csv", "json")


class LogSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Registry of known log source types (eCAT, CIM, Keeper, …)."""

    __tablename__ = "log_sources"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    log_files: Mapped[list["LogFile"]] = relationship(back_populates="log_source")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LogSource {self.code}>"


class LogFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An uploaded file or a file extracted from an uploaded archive."""

    __tablename__ = "log_files"

    # ---- identity & storage ----
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Path relative to the storage root (uploads/original/… or uploads/extracted/…)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)  # txt|log|csv|json|zip
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # upload | extracted
    file_role: Mapped[str] = mapped_column(String(16), default="upload", nullable=False, index=True)
    # For extracted files: the ZIP they came from and their path inside it.
    parent_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("log_files.id", ondelete="CASCADE"), nullable=True, index=True
    )
    original_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ---- fleet links (optional at upload time) ----
    machine_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    machine_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machine_models.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ---- identification results ----
    log_source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("log_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    detection_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Phase 6: ranked model-detection candidates + per-signal evidence.
    detection_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parser_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ---- processing state ----
    status: Mapped[str] = mapped_column(String(16), default="UPLOADED", nullable=False, index=True)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Soft duplicate reference: first upload with the same checksum.
    duplicate_of_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True
    )

    # ---- relationships ----
    machine: Mapped["Machine | None"] = relationship(back_populates="log_files")
    machine_model: Mapped["MachineModel | None"] = relationship()
    log_source: Mapped[LogSource | None] = relationship(back_populates="log_files")
    parent: Mapped["LogFile | None"] = relationship(
        remote_side="LogFile.id",
        foreign_keys="LogFile.parent_file_id",
        backref="children",
    )
    lines: Mapped[list["LogLine"]] = relationship(
        back_populates="log_file", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LogFile {self.original_filename} ({self.status})>"


class LogLine(BigIntegerPrimaryKeyMixin, Base):
    """A single raw log line — the immutable evidence record."""

    __tablename__ = "log_lines"
    __table_args__ = (
        UniqueConstraint("log_file_id", "line_number", name="uq_log_lines_file_line"),
    )

    log_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("log_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Normalized preliminary structure produced by the parser.
    normalized_data: Mapped[dict | None] = mapped_column("normalized_data", JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    log_file: Mapped[LogFile] = relationship(back_populates="lines")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LogLine file={self.log_file_id} line={self.line_number}>"
