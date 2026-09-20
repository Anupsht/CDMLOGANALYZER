"""Universal normalized event model.

``NORMALIZED_EVENTS`` is the *complete* vocabulary the universal engine
understands. Model adapters map their raw messages onto these codes via
``events.yaml``. Codes that cannot be established with confidence are
explicitly ``UNKNOWN`` / ``UNMAPPED`` — inventing events is prohibited.

Confidence semantics (Phase 3 contract):
* an event only exists if a model config pattern matched real raw text;
* ``UNMAPPED`` marks recognized-but-unmappable lines;
* ``UNKNOWN`` marks lines where even the message itself is unclear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.models.log_file import LogLine

# ---------------------------------------------------------------------------
# Universal event vocabulary
# ---------------------------------------------------------------------------

TRANSACTION_STARTED = "TRANSACTION_STARTED"
CASH_INSERTED = "CASH_INSERTED"  # notes entered the accept path
CASH_ACCEPTED = "CASH_ACCEPTED"  # acceptance confirmed (escrow in)
CASH_COUNTING_COMPLETED = "CASH_COUNTING_COMPLETED"
VALIDATION_PASSED = "VALIDATION_PASSED"
VALIDATION_FAILED = "VALIDATION_FAILED"
HOST_REQUEST = "HOST_REQUEST"
HOST_RESPONSE = "HOST_RESPONSE"
HOST_DECLINED = "HOST_DECLINED"
CASH_STORED = "CASH_STORED"
CASH_RETURNED = "CASH_RETURNED"
CASH_REJECTED = "CASH_REJECTED"
TRANSACTION_COMPLETED = "TRANSACTION_COMPLETED"
TRANSACTION_FAILED = "TRANSACTION_FAILED"
DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
SENSOR_CHANGED = "SENSOR_CHANGED"
MOTOR_STARTED = "MOTOR_STARTED"
MOTOR_STOPPED = "MOTOR_STOPPED"
RECEIPT_PRINTED = "RECEIPT_PRINTED"
NOTE_RECYCLED = "NOTE_RECYCLED"
ERROR = "ERROR"
UNMAPPED = "UNMAPPED"  # line understood structurally, semantics not mapped
UNKNOWN = "UNKNOWN"  # cannot even establish the line semantics

NORMALIZED_EVENTS: tuple[str, ...] = (
    TRANSACTION_STARTED,
    CASH_INSERTED,
    CASH_ACCEPTED,
    CASH_COUNTING_COMPLETED,
    VALIDATION_PASSED,
    VALIDATION_FAILED,
    HOST_REQUEST,
    HOST_RESPONSE,
    HOST_DECLINED,
    CASH_STORED,
    CASH_RETURNED,
    CASH_REJECTED,
    TRANSACTION_COMPLETED,
    TRANSACTION_FAILED,
    DEVICE_UNAVAILABLE,
    SENSOR_CHANGED,
    MOTOR_STARTED,
    MOTOR_STOPPED,
    RECEIPT_PRINTED,
    NOTE_RECYCLED,
    ERROR,
    UNMAPPED,
    UNKNOWN,
)

SEVERITIES: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_DEFAULT_SEVERITY = {
    ERROR: "ERROR",
    DEVICE_UNAVAILABLE: "WARNING",
    VALIDATION_FAILED: "WARNING",
    HOST_DECLINED: "WARNING",
    CASH_REJECTED: "WARNING",
    TRANSACTION_FAILED: "ERROR",
    UNMAPPED: "DEBUG",
    UNKNOWN: "DEBUG",
}


def default_severity(event: str) -> str:
    return _DEFAULT_SEVERITY.get(event, "INFO")


# Correlation key names (universal; extracted patterns are per-model config).
CORRELATION_KEYS: tuple[str, ...] = (
    "txn_id",
    "session_id",
    "journal_seq",
    "amount",
    "currency",
    "host_ref",
    "machine_sn",
)


@dataclass
class NormalizedEvent:
    """One model-specific message mapped into the universal event model.

    ``raw`` keeps the evidence pointer (never None for real events):
    original file, line number and verbatim raw text live on the linked
    :class:`app.models.log_file.LogLine` row.
    """

    model_code: str
    source_code: str
    event: str
    timestamp: datetime | None
    device: str | None = None
    severity: str = "INFO"
    detail: dict[str, Any] = field(default_factory=dict)
    keys: dict[str, Any] = field(default_factory=dict)  # correlation keys
    raw: "LogLine | None" = None  # evidence link

    @property
    def line_number(self) -> int | None:
        return self.raw.line_number if self.raw is not None else None

    @property
    def raw_text(self) -> str:
        return self.raw.raw_text if self.raw is not None else ""

    @property
    def log_file_id(self) -> str | None:
        return self.raw.log_file_id if self.raw is not None else None

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<NormalizedEvent {self.event} model={self.model_code} src={self.source_code} "
            f"ts={self.timestamp} line={self.line_number}>"
        )
