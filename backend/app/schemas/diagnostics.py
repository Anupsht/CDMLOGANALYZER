"""Phase 5 diagnostic report API schemas."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.transaction import TransactionOut


class EvidenceRef(BaseModel):
    kind: str
    event: str | None = None
    timestamp: str | None = None
    device: str | None = None
    file_id: str | None = None
    line_number: int | None = None
    raw_text: str | None = None
    # cash / sensor / motor / transport / gate / shutter / fault / reconciliation refs
    transition: str | None = None
    sensor: str | None = None
    motor: str | None = None
    name: str | None = None
    outcome: str | None = None
    classification: str | None = None
    issue: str | None = None
    statement: str | None = None
    detail: dict | None = None


class FindingOut(BaseModel):
    model_config = {"from_attributes": True}

    finding_id: str
    rule_id: str
    diagnosis_class: str
    category: str | None = None
    severity: str
    confidence: str
    summary: str
    interpretation: str
    possible_causes: list | None = None
    recommended_action: str | None = None
    evidence: list | None = None
    cash_states: list | None = None


class DiagnosticReportOut(BaseModel):
    model_config = {"from_attributes": True}

    transaction: TransactionOut
    summary: str
    classification: str
    diagnosis_class: str
    severity: str
    confidence: str
    final_cash_state: str | None = None
    findings: list[FindingOut]
