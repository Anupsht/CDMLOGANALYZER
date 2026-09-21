"""Phase 9 — historical analytics, patterns, cross-machine, maintenance.

Read-only aggregations plus the human-in-the-loop rule-suggestion workflow.
Nothing here mutates analysis data, and approving a suggestion never loads
it into the production rules engine (manual YAML promotion only).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import NotFoundError, ValidationError
from app.models.rule_suggestion import STATUSES, RuleSuggestion
from app.schemas.analytics import (
    CrossMachineOut,
    ErrorAnalyticsOut,
    InsightsOut,
    MaintenanceOut,
    OverviewOut,
    PatternsOut,
    RuleSuggestionCreate,
    RuleSuggestionOut,
    RuleSuggestionUpdate,
    TrendsOut,
)
from app.services.analytics_service import (
    cross_machine,
    error_analytics,
    insights,
    maintenance,
    overview,
    patterns,
    trends,
)
from app.services.audit_service import audit_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewOut)
def analytics_overview(
    window_days: int = Query(default=90, ge=1, le=730),
    session: Session = Depends(get_db),
) -> OverviewOut:
    """Historical counters over the window (spec §1)."""
    return OverviewOut.model_validate(overview(session, window_days=window_days))


@router.get("/trends", response_model=TrendsOut)
def analytics_trends(
    bucket: str = Query(default="daily", description="daily|weekly|monthly"),
    window_days: int = Query(default=90, ge=1, le=730),
    session: Session = Depends(get_db),
) -> TrendsOut:
    """Bucketed trend series (spec §5)."""
    return TrendsOut.model_validate(
        trends(session, bucket=bucket, window_days=window_days)
    )


@router.get("/errors", response_model=ErrorAnalyticsOut)
def analytics_errors(
    window_days: int = Query(default=90, ge=1, le=730),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> ErrorAnalyticsOut:
    """Per-error-code occurrence stats with preceding/following events (§4)."""
    return ErrorAnalyticsOut.model_validate(
        error_analytics(session, window_days=window_days, limit=limit)
    )


@router.get("/patterns", response_model=PatternsOut)
def analytics_patterns(
    window_days: int = Query(default=90, ge=1, le=730),
    session: Session = Depends(get_db),
) -> PatternsOut:
    """Detected patterns (spec §2) — advisory drafts, never auto-promoted."""
    return PatternsOut.model_validate(patterns(session, window_days=window_days))


@router.get("/cross-machine", response_model=CrossMachineOut)
def analytics_cross_machine(
    window_days: int = Query(default=90, ge=1, le=730),
    session: Session = Depends(get_db),
) -> CrossMachineOut:
    """Compare machines / locations / models / software versions (spec §3)."""
    return CrossMachineOut.model_validate(
        cross_machine(session, window_days=window_days)
    )


@router.get("/maintenance", response_model=MaintenanceOut)
def analytics_maintenance(
    recent_days: int = Query(default=7, ge=1, le=180),
    baseline_days: int = Query(default=30, ge=2, le=730),
    session: Session = Depends(get_db),
) -> MaintenanceOut:
    """Increasing-metric flags WATCH / WARNING / HIGH_RISK (spec §6).

    Heuristic triage flags on aggregate rates — never a component-failure
    declaration.
    """
    if recent_days >= baseline_days:
        raise ValidationError("recent_days must be smaller than baseline_days")
    return MaintenanceOut.model_validate(
        maintenance(session, recent_days=recent_days, baseline_days=baseline_days)
    )


@router.get("/insights", response_model=InsightsOut)
def analytics_insights(
    window_days: int = Query(default=90, ge=1, le=730),
    session: Session = Depends(get_db),
) -> InsightsOut:
    """Direct answers to the completion questions (spec §9)."""
    return InsightsOut.model_validate(insights(session, window_days=window_days))


# --------------------------------------------------------------------------- #
# §7 — rule suggestions (human review workflow)
# --------------------------------------------------------------------------- #


@router.get("/rule-suggestions", response_model=list[RuleSuggestionOut])
def list_rule_suggestions(
    status: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[RuleSuggestionOut]:
    query = session.query(RuleSuggestion)
    if status:
        if status not in STATUSES:
            raise ValidationError(f"invalid status: {status} (one of {STATUSES})")
        query = query.filter(RuleSuggestion.status == status)
    rows = query.order_by(RuleSuggestion.created_at.desc()).limit(200).all()
    return [RuleSuggestionOut.model_validate(r) for r in rows]


@router.post("/rule-suggestions", response_model=RuleSuggestionOut, status_code=201)
def create_rule_suggestion(
    payload: RuleSuggestionCreate, session: Session = Depends(get_db)
) -> RuleSuggestionOut:
    """Record a pattern as a suggested rule (status SUGGESTED — inert)."""
    row = RuleSuggestion(
        title=payload.title.strip()[:160] or "Suggested rule",
        pattern_type=payload.pattern_type,
        rationale=payload.rationale,
        pattern_stats=payload.pattern_stats,
        draft_rule=payload.draft_rule,
        status="SUGGESTED",
        source_transaction_id=payload.source_transaction_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    audit_service.record(
        session,
        action="rule_suggestion.created",
        entity_type="rule_suggestion",
        entity_id=row.id,
        detail={"pattern_type": row.pattern_type, "title": row.title},
    )
    session.commit()
    return RuleSuggestionOut.model_validate(row)


@router.patch("/rule-suggestions/{suggestion_id}", response_model=RuleSuggestionOut)
def update_rule_suggestion(
    suggestion_id: str,
    payload: RuleSuggestionUpdate,
    session: Session = Depends(get_db),
) -> RuleSuggestionOut:
    """Human review transition: UNDER_REVIEW / APPROVED / REJECTED / INCORPORATED.

    APPROVED does **not** activate anything — the diagnostics engine reads
    only config YAML. INCORPORATED marks that a human copied the draft into
    the YAML package.
    """
    row = session.get(RuleSuggestion, suggestion_id)
    if row is None:
        raise NotFoundError(f"Rule suggestion not found: {suggestion_id}")
    if payload.status not in STATUSES:
        raise ValidationError(f"invalid status: {payload.status} (one of {STATUSES})")
    if payload.status in ("APPROVED", "REJECTED", "INCORPORATED") and not payload.reviewed_by:
        raise ValidationError(f"{payload.status} requires reviewed_by (human reviewer)")
    previous = row.status
    row.status = payload.status
    row.reviewed_by = payload.reviewed_by
    row.review_note = payload.review_note
    session.commit()
    audit_service.record(
        session,
        action="rule_suggestion.reviewed",
        entity_type="rule_suggestion",
        entity_id=row.id,
        detail={"from": previous, "to": row.status, "reviewer": payload.reviewed_by},
    )
    session.commit()
    session.refresh(row)
    return RuleSuggestionOut.model_validate(row)
