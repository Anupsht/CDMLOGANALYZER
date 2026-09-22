"""Maintenance / investigation cases (Phase 10).

Technicians open a case from a failed transaction or a machine flag;
supervisors close or review it. Cases reference evidence by id — they never
contain analysis conclusions themselves.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Case(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    __tablename__ = "cases"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # OPEN | IN_REVIEW | CLOSED
    status: Mapped[str] = mapped_column(String(16), default="OPEN", nullable=False, index=True)
    # LOW | MEDIUM | HIGH
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM", nullable=False)
    machine_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # business transaction id (e.g. T-8803), not the UUID — human-facing
    transaction_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Case {self.title} [{self.status}]>"
