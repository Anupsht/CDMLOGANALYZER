"""Phase 9 analytics API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TrendsOut(BaseModel):
    bucket: str
    window_days: int
    points: list[dict]
    note: str


class OverviewOut(BaseModel):
    model_config = {"from_attributes": True}

    window_days: int
    transactions: dict
    failures: int
    errors: int
    jams: int
    sensor_faults: int
    cash_exceptions: int
    host_failures: int
    hardware_errors: int
    device_unavailable_events: int
    automatic_resets: int


class ErrorAnalyticsOut(BaseModel):
    window_days: int
    errors: list[dict]
    note: str


class PatternsOut(BaseModel):
    window_days: int
    patterns: list[dict]
    thresholds: dict
    note: str


class CrossMachineOut(BaseModel):
    window_days: int
    machines: list[dict]
    by_location: list[dict]
    by_model: list[dict]
    by_software_version: list[dict]
    note: str


class MaintenanceOut(BaseModel):
    recent_days: int
    baseline_days: int
    machines: list[dict]
    thresholds: dict
    note: str


class InsightsOut(BaseModel):
    window_days: int
    machines_with_most_problems: list[dict]
    errors_increasing: list[dict]
    model_highest_failure_rate: dict | None
    faults_preceding_failure: list[dict]
    machines_to_investigate_first: list
    note: str


class RuleSuggestionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    title: str
    pattern_type: str
    rationale: str | None
    pattern_stats: dict | None
    draft_rule: dict | None
    status: str
    reviewed_by: str | None
    review_note: str | None
    source_transaction_id: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RuleSuggestionCreate(BaseModel):
    title: str
    pattern_type: str
    rationale: str | None = None
    pattern_stats: dict | None = None
    draft_rule: dict | None = None
    source_transaction_id: str | None = None


class RuleSuggestionUpdate(BaseModel):
    status: str
    reviewed_by: str | None = None
    review_note: str | None = None
