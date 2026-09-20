"""Phase 5 diagnostic findings (universal).

Rows are produced by the data-driven diagnostic engine
(:mod:`app.analysis.diagnostics`) from the Phase 2–4 evidence picture.
Every finding carries its evidence as JSON references into the raw logs
(file id + line number + raw text) — findings without evidence are never
produced.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DiagnosticFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "diagnostic_findings"
    __table_args__ = (
        Index("ix_diagnostic_findings_txn", "transaction_id"),
        Index("ix_diagnostic_findings_class", "diagnosis_class"),
    )

    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[str] = mapped_column(String(96), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(96), nullable=False)
    # HOST_FAILURE | HARDWARE_FAILURE | COMMUNICATION_FAILURE |
    # APPLICATION_FAILURE | CASH_EXCEPTION | REQUIREMENT_VIOLATION |
    # NO_FAILURE | INSUFFICIENT_DATA
    diagnosis_class: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)  # LOW..VERY_HIGH

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    possible_causes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Evidence refs: normalized events (kind=event with file/line/raw),
    # cash transitions, sensor/motor/gate/shutter/transport records,
    # Phase 4 fault classifications, reconciliation issues.
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cash_states: Mapped[list | None] = mapped_column(JSON, nullable=True)
