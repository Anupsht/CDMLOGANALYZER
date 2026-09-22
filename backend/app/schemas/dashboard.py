"""Phase 7 dashboard & machine-health API schemas.

Read-only aggregates for the technician dashboard. The health score itself
is computed client-side from configurable weights — the backend only ever
reports raw, evidence-based counters and never a "diagnosis".
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FleetStatus(BaseModel):
    total: int
    online: int
    offline: int
    window_hours: int
    note: str = (
        "online = machine logged activity within the window "
        "(or status 'online'); offline = no recent logged activity"
    )


class TransactionCounts(BaseModel):
    total: int
    completed: int
    declined: int
    failed: int
    incomplete: int


class FindingCounts(BaseModel):
    """Distinct-transaction counts per diagnostic class/rule (Phase 5 data)."""

    hardware_errors: int
    possible_jams: int
    confirmed_jams: int
    cash_exceptions: int
    host_failures: int


class ModelBreakdownEntry(BaseModel):
    model_code: str
    transactions: int
    completed: int
    failed: int
    declined: int
    incomplete: int


class DashboardSummaryOut(BaseModel):
    generated_at: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    fleet: FleetStatus
    transactions: TransactionCounts
    findings: FindingCounts
    models: list[ModelBreakdownEntry]


class MachineHealthMetrics(BaseModel):
    """Raw per-machine counters. The score is computed client-side."""

    machine_id: str
    serial_number: str
    name: str | None = None
    model_code: str | None = None
    location: str | None = None
    status: str
    window_days: int
    window_start: datetime | None = None
    transactions_total: int
    completed: int
    declined: int
    failed: int
    incomplete: int
    failure_rate: float
    jam_transactions: int
    jam_frequency: float
    hardware_error_transactions: int
    sensor_abnormalities: int
    device_unavailable_events: int
    recovery_reset_events: int
    last_activity_at: datetime | None = None
    note: str = (
        "counters are evidence-based; any score derived from them is a "
        "heuristic prioritisation aid, not a diagnosis"
    )
