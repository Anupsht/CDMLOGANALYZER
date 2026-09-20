"""Machine fleet endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.common import ListResponse
from app.schemas.machine import MachineCreate, MachineOut
from app.services.audit_service import audit_service
from app.services.machine_service import machine_service

router = APIRouter(prefix="/machines", tags=["machines"])


@router.get("", response_model=ListResponse[MachineOut])
def list_machines(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> ListResponse[MachineOut]:
    items, total = machine_service.list(session, limit=limit, offset=offset)
    return ListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=MachineOut, status_code=201)
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
