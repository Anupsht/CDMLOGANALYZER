"""Phase 10 — maintenance / investigation cases.

Technicians open a case tied to evidence (machine / transaction reference);
supervisors review and close it. Every transition is audited.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.errors import NotFoundError, ValidationError
from app.core.rbac import require_permission
from app.models.case import Case
from app.models.machine import Machine
from app.models.user import User
from app.services.audit_service import audit_service

router = APIRouter(prefix="/cases", tags=["cases"])

_CASE_STATUSES = ("OPEN", "IN_REVIEW", "CLOSED")
_PRIORITIES = ("LOW", "MEDIUM", "HIGH")


class CaseIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: str = "MEDIUM"
    machine_id: str | None = None
    transaction_ref: str | None = Field(default=None, max_length=64)


class CaseUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = None
    priority: str | None = None


class CaseOut(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str
    priority: str
    machine_id: str | None = None
    transaction_ref: str | None = None
    created_by: str | None = None
    closed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


def _out(case: Case) -> CaseOut:
    return CaseOut.model_validate(case)


def _validated_choice(value: str | None, allowed: tuple[str, ...], label: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in allowed:
        raise ValidationError(f"{label} must be one of: {', '.join(allowed)}.")
    return normalized


@router.get("", response_model=list[CaseOut])
def list_cases(
    status: str | None = Query(default=None),
    machine_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[CaseOut]:
    query = session.query(Case)
    if status:
        query = query.filter(Case.status == _validated_choice(status, _CASE_STATUSES, "Status"))
    if machine_id:
        query = query.filter(Case.machine_id == machine_id)
    return [
        _out(c)
        for c in query.order_by(Case.created_at.desc()).limit(limit).all()
    ]


@router.post("", response_model=CaseOut, status_code=201)
def create_case(
    payload: CaseIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission("cases:create")),
) -> CaseOut:
    priority = _validated_choice(payload.priority, _PRIORITIES, "Priority") or "MEDIUM"
    machine_id = payload.machine_id
    if machine_id and session.get(Machine, machine_id) is None:
        raise NotFoundError(f"Machine not found: {machine_id}")
    case = Case(
        title=payload.title.strip(),
        description=payload.description,
        status="OPEN",
        priority=priority,
        machine_id=machine_id,
        transaction_ref=payload.transaction_ref,
        created_by=user.username,
    )
    session.add(case)
    session.flush()
    audit_service.record(
        session,
        action="case.created",
        entity_type="case",
        entity_id=case.id,
        actor=user.username,
        detail={"title": case.title, "priority": case.priority, "transaction_ref": case.transaction_ref},
    )
    return _out(case)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(
    case_id: str,
    session: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> CaseOut:
    case = session.get(Case, case_id)
    if case is None:
        raise NotFoundError(f"Case not found: {case_id}")
    return _out(case)


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: str,
    payload: CaseUpdateIn,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission("cases:update")),
) -> CaseOut:
    case = session.get(Case, case_id)
    if case is None:
        raise NotFoundError(f"Case not found: {case_id}")
    detail: dict = {}
    if payload.title is not None:
        case.title = payload.title.strip()
        detail["title"] = case.title
    if payload.description is not None:
        case.description = payload.description
    if payload.priority is not None:
        case.priority = _validated_choice(payload.priority, _PRIORITIES, "Priority")
        detail["priority"] = case.priority
    if payload.status is not None:
        new_status = _validated_choice(payload.status, _CASE_STATUSES, "Status")
        case.status = new_status
        detail["status"] = new_status
        case.closed_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) if new_status == "CLOSED" else None
        )
    session.flush()
    audit_service.record(
        session,
        action="case.updated",
        entity_type="case",
        entity_id=case.id,
        actor=user.username,
        detail=detail,
    )
    return _out(case)
