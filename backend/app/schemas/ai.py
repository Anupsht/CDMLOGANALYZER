"""Phase 8 API schemas — AI digest / explanation / vendor report."""

from __future__ import annotations

from pydantic import BaseModel


class AIDigestOut(BaseModel):
    """The structured AI input (transaction summary, events, cash, host,
    hardware, rule results, root-cause candidates, evidence)."""

    model_config = {"from_attributes": True}

    transaction: dict
    machine: dict | None
    normalized_events: list[dict]
    cash_states: dict
    host_events: list[dict]
    error_events: list[dict]
    hardware_events: dict
    rule_results: list[dict]
    engine_report: dict
    root_cause_candidates: list[dict]
    evidence: list[dict]
    bounds: dict
    note: str
    digest_sha256: str


class AIExplanationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    transaction_id: str
    provider: str
    generator: str
    model_name: str | None = None
    digest_sha256: str
    created_at: str | None = None
    payload: dict
    safety_notes: list | None = None
    digest: dict | None = None


class VendorReportOut(BaseModel):
    model_config = {"from_attributes": True}

    generated_at: str
    report_kind: str
    system: str
    machine: dict
    transaction: dict
    problem: dict
    timeline: list[dict]
    errors: list[dict]
    hardware_state: dict
    cash_state: dict
    host_state: dict
    analysis: dict
    evidence: list[dict]
    vendor_questions: list
    recommended_actions: list
    traceability: dict
