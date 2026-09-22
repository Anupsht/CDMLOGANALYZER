"""Universal transaction tables (model-independent).

Populated by the universal correlation engine (:mod:`app.analysis`).
Every ``transaction_events`` row carries a raw evidence pointer
(``log_file_id`` + ``line_number`` + verbatim ``raw_text``) so any
reconstructed transaction can be traced back to original log lines.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import (
    Base,
    BigIntegerPrimaryKeyMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.log_file import LogFile
    from app.models.machine import Machine, MachineModel


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A correlated transaction reconstructed from one or more log sources."""

    __tablename__ = "transactions"

    # Business transaction id as found in the logs (or AUTO-<prefix>-<hash>
    # when correlation relied on secondary keys only).
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    machine_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    machine_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("machine_models.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # COMPLETED | DECLINED | FAILED | INCOMPLETE
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="INCOMPLETE", index=True)
    correlation_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    correlation_method: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # The upload batch (log_files row) this reconstruction came from.
    source_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True, index=True
    )

    machine: Mapped["Machine | None"] = relationship()
    machine_model: Mapped["MachineModel | None"] = relationship()
    events: Mapped[list["TransactionEvent"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionEvent.seq",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Transaction {self.transaction_id} ({self.status})>"


class TransactionEvent(BigIntegerPrimaryKeyMixin, Base):
    """One normalized event inside a transaction, with raw evidence link."""

    __tablename__ = "transaction_events"
    __table_args__ = (
        Index("ix_transaction_events_txn_seq", "transaction_id", "seq"),
    )

    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)  # chronological order

    event_code: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ---- raw evidence link (never modified) ----
    log_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    line_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    transaction: Mapped[Transaction] = relationship(back_populates="events")
    log_file: Mapped["LogFile | None"] = relationship()

    @property
    def event(self) -> str:
        """Universal-engine alias: the reconstructor reads ``.event``."""
        return self.event_code

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TransactionEvent {self.seq} {self.event_code}>"
