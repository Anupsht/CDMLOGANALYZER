"""Machine model registry endpoints (registry-driven, never hard-coded)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.registry import model_registry
from app.schemas.machine import MachineModelOut
from app.schemas.model import ModelToggleResponse
from app.services.machine_service import machine_service

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[MachineModelOut])
def list_models(session: Session = Depends(get_db)) -> list[MachineModelOut]:
    """All registered machine models (adapter registry + DB state)."""
    entries = machine_service.list_models(session)
    return [MachineModelOut(**entry) for entry in entries]


@router.get("/{model_id}", response_model=MachineModelOut)
def get_model(model_id: str, session: Session = Depends(get_db)) -> MachineModelOut:
    """Model detail; ``{model_id}`` is the model code (e.g. ``P2600N``)."""
    for entry in machine_service.list_models(session):
        if entry["code"].upper() == model_id.upper():
            return MachineModelOut(**entry)
    from app.core.errors import NotFoundError

    raise NotFoundError(f"Machine model not found: {model_id}")


@router.post("/{model_id}/enable", response_model=ModelToggleResponse)
def enable_model(model_id: str, session: Session = Depends(get_db)) -> ModelToggleResponse:
    result = model_registry.enable_model(model_id, session)
    session.commit()
    return ModelToggleResponse(**result)


@router.post("/{model_id}/disable", response_model=ModelToggleResponse)
def disable_model(model_id: str, session: Session = Depends(get_db)) -> ModelToggleResponse:
    result = model_registry.disable_model(model_id, session)
    session.commit()
    return ModelToggleResponse(**result)
