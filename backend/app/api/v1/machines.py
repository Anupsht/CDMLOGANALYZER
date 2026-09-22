"""Machine fleet endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.rbac import require_permission
from app.schemas.common import ListResponse
from app.schemas.dashboard import MachineHealthMetrics
from app.schemas.machine import MachineCreate, MachineOut
from app.services.audit_service import audit_service
from app.services.dashboard_service import dashboard_service
from app.services.machine_service import machine_service

router = APIRouter(
    prefix="/machines", tags=["machines"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=ListResponse[MachineOut])
def list_machines(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ListResponse[MachineOut]:
    items, total = machine_service.list(session, limit=limit, offset=offset)
    return ListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=MachineOut,
    status_code=201,
    dependencies=[Depends(require_permission("machines:write"))],
)
def create_machine(payload: MachineCreate, session: Session = Depends(get_db)) -> MachineOut:
    machine = machine_service.create(session, payload)
    audit_service.record(
        session,
        action="machine.created",
        entity_type="machine",
        entity_id=machine.id,
        detail={"serial_number": machine.serial_number},
    )
    session.commit()
    session.refresh(machine)
    return machine


@router.get("/{machine_id}", response_model=MachineOut)
def get_machine(machine_id: str, session: Session = Depends(get_db)) -> MachineOut:
    return machine_service.get(session, machine_id)


@router.get("/{machine_id}/health", response_model=MachineHealthMetrics)
def get_machine_health(
    machine_id: str,
    window_days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_db),
) -> MachineHealthMetrics:
    """Raw per-machine health counters (Phase 7).

    Evidence-based counters only — the frontend computes a configurable,
    explicitly non-definitive score from these numbers.
    """
    try:
        metrics = dashboard_service.machine_health(
            session, machine_id, window_days=window_days
        )
    except LookupError as exc:
        from app.core.errors import NotFoundError

        raise NotFoundError(str(exc)) from exc
    return MachineHealthMetrics.model_validate(metrics)
