"""Hardware timeline API schemas (Phase 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.transaction import TransactionOut


class EvidenceRef(BaseModel):
    file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None


class CashMovementOut(BaseModel):
    model_config = {"from_attributes": True}

    note_id: str | None = None
    from_state: str
    to_state: str
    timestamp: datetime | None = None
    device: str | None = None
    evidence_event: str
    confidence: float
    note_info: dict | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None


class SensorEventOut(BaseModel):
    model_config = {"from_attributes": True}

    sensor: str
    previous_state: str | None = None
    new_state: str | None = None
    timestamp: datetime | None = None
    expected_state: str | None = None
    actual_state: str | None = None
    abnormal_duration_ms: int | None = None
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    detail: dict | None = None


class MotorEventOut(BaseModel):
    model_config = {"from_attributes": True}

    motor: str
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    duration_ms: int | None = None
    timeout_ms: int | None = None
    timed_out: bool
    transport_name: str | None = None
    sensor_transitions: list | None = None
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    stop_line_number: int | None = None
    stop_raw_text: str | None = None


class GateEventOut(BaseModel):
    model_config = {"from_attributes": True}

    kind: str  # gate | shutter
    name: str
    command: str | None = None
    expected_state: str | None = None
    actual_state: str | None = None
    transition_ms: int | None = None
    timeout_ms: int | None = None
    timed_out: bool
    state_mismatch: bool
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    position_evidence: dict | None = None


class TransportEventOut(BaseModel):
    model_config = {"from_attributes": True}

    name: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    outcome: str
    timeout_ms: int | None = None
    detail: dict | None = None
    device: str | None = None
    log_file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None


class FaultAssessmentOut(BaseModel):
    model_config = {"from_attributes": True}

    subject_kind: str
    subject_name: str | None = None
    classification: str
    statement: str
    evidence: list | None = None
    analysis_window: dict | None = None
    assessed_at: datetime | None = None


class TimelineEntryHwOut(BaseModel):
    timestamp: datetime | None = None
    kind: str  # transaction | cash | sensor | motor | gate | shutter | transport | fault
    name: str | None = None
    event: str
    device: str | None = None
    severity: str = "INFO"
    detail: dict | list | None = None
    raw: EvidenceRef | None = None


class HardwareTimelineOut(BaseModel):
    """Transaction → Cash → Device → Sensor/Motor/Gate → Fault → Final state."""

    transaction: TransactionOut
    final_cash_state: str
    cash_movements: list[CashMovementOut]
    sensor_events: list[SensorEventOut]
    motor_events: list[MotorEventOut]
    gate_events: list[GateEventOut]
    shutter_events: list[GateEventOut]
    transport_events: list[TransportEventOut]
    faults: list[FaultAssessmentOut]
    timeline: list[TimelineEntryHwOut]
    extras: dict[str, Any] | None = None
