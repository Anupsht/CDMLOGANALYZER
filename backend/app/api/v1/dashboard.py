"""Phase 7 technician-dashboard endpoints (read-only aggregates)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.dashboard import DashboardSummaryOut
from app.services.dashboard_service import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _parse_dt(value: str | None) -> datetime | None:
    """Accept ISO datetimes or plain dates (YYYY-MM-DD)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


@router.get("/summary", response_model=DashboardSummaryOut)
def dashboard_summary(
    machine_id: str | None = Query(default=None),
    model_code: str | None = Query(default=None),
    date_from: str | None = Query(default=None, description="ISO date/datetime"),
    date_to: str | None = Query(default=None, description="ISO date/datetime"),
    online_window_hours: int = Query(default=24, ge=1, le=720),
    session: Session = Depends(get_db),
) -> DashboardSummaryOut:
    """Aggregated counters for the dashboard header (evidence-based).

    Findings counters reuse the Phase-5 rules-engine classification stored
    in ``diagnostic_findings`` — no new interpretation happens here.
    """
    return DashboardSummaryOut.model_validate(
        dashboard_service.summary(
            session,
            machine_id=machine_id,
            model_code=model_code,
            start_from=_parse_dt(date_from),
            start_to=_parse_dt(date_to),
            online_window_hours=online_window_hours,
        )
    )
