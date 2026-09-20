"""Phase 4 hardware/cash-flow tables (universal, model-independent).

Populated by :mod:`app.analysis.hardware` from normalized transaction
events. Every row that derives from a log line carries the raw evidence
pointer (``log_file_id`` + ``line_number`` + ``raw_text``) — diagnoses
never exist without inspectable evidence.

Design rules:
* nothing here is model-specific — the extraction patterns live in each
  model's ``hardware.yaml``;
* missing values stay ``None`` / ``UNKNOWN`` — they are never invented;
* a ``FaultAssessment`` states observed facts + hedged hypotheses, never
  component-level root causes.
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
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    pass

class CashMovement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One cash-lifecycle state transition of a transaction.

    Lifecycle states (universal): UNKNOWN, INSERTED, ACCEPTED, VALIDATED,
    COUNTED, ESCROW, CONFIRMED, TRANSPORTING, STORED, REJECTED, RETURNED,
    JAMMED, UNKNOWN_LOCATION.
    """

    __tablename__ = "cash_movements"
    __table_args__ = (
        Index("ix_cash_movements_txn", "transaction_id"),
        Index("ix_cash_movements_to_state", "to_state"),
    )

    transaction_id: Mapped[str] = mapped_column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    note_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    from_state: Mapped[str] = mapped_column(String(24), nullable=False)
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_event: Mapped[str] = mapped_column(String(48), nullable=False)

    # 0.0..1.0 — direct universal mapping vs. inferred transition.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Per-note metadata *when the log carries it*; missing fields stay
    # "UNKNOWN" (never guessed).
    note_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Evidence: the normalized event this transition was derived from.
    log_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True)
    line_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class SensorEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A sensor transition (previous → new state) with expectation context."""

    __tablename__ = "sensor_events"
    __table_args__ = (Index("ix_sensor_events_txn", "transaction_id"),)

    transaction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True)
    sensor: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Expectation context when one existed (transport/gate command).
    expected_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actual_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Delay relative to the end of the expectation window, when late.
    abnormal_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)

    log_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True)
    line_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class MotorEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One motor run: start (+ optional stop / timeout classification)."""

    __tablename__ = "motor_events"
    __table_args__ = (Index("ix_motor_events_txn", "transaction_id"),)

    transaction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True)
    motor: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timeout_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Transport association when the motor is a configured transport motor.
    transport_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sensor_transitions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)

    log_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True)
    line_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_line_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stop_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class GateEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A gate or shutter command and its observed position outcome."""

    __tablename__ = "gate_events"
    __table_args__ = (
        Index("ix_gate_events_txn", "transaction_id"),
        Index("ix_gate_events_kind", "kind"),
    )

    transaction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # gate | shutter
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    command: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actual_state: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None = never observed
    transition_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timeout_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)

    log_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True)
    line_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    position_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TransportEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A cash transport run and its outcome classification."""

    __tablename__ = "transport_events"
    __table_args__ = (Index("ix_transport_events_txn", "transaction_id"),)

    transaction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # COMPLETED | TIMEOUT | MISSING_SENSOR_TRANSITION | REPEATED_MOVEMENT
    # | UNEXPECTED_STATE | UNKNOWN
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    timeout_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)

    log_file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("log_files.id", ondelete="SET NULL"), nullable=True)
    line_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class FaultAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Evidence-based fault/jam assessment for one transaction.

    ``classification``: CONFIRMED_JAM | PROBABLE_JAM | POSSIBLE_JAM |
    NO_EVIDENCE_OF_JAM | INSUFFICIENT_DATA.
    ``statement`` contains observed facts and hedged hypotheses only —
    never an unsupported component-level conclusion.
    """

    __tablename__ = "fault_assessments"
    __table_args__ = (
        Index("ix_fault_assessments_txn", "transaction_id"),
        Index("ix_fault_assessments_classification", "classification"),
    )

    transaction_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True)
    subject_kind: Mapped[str] = mapped_column(String(24), nullable=False)  # transport|motor|gate|shutter|sensor|transaction
    subject_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    analysis_window: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
