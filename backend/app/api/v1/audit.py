"""Phase 10 — read access to the audit trail (ADMIN / SUPERVISOR)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.rbac import require_permission
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    id: int
    actor: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    detail: dict | None = None
    request_id: str | None = None
    ip: str | None = None
    result: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AuditEntryOut])
def list_audit(
    action: str | None = Query(default=None, description="Exact action, e.g. auth.login"),
    action_prefix: str | None = Query(default=None, description="e.g. 'auth.' for all auth events"),
    actor: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    result: str | None = Query(default=None, description="success | failure"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission("audit:read")),
) -> list[AuditEntryOut]:
    query = session.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if action_prefix:
        query = query.filter(AuditLog.action.like(f"{action_prefix}%"))
    if actor:
        query = query.filter(AuditLog.actor == actor)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if result:
        query = query.filter(AuditLog.result == result)
    rows = query.order_by(AuditLog.id.desc()).limit(limit).offset(offset).all()
    return [AuditEntryOut.model_validate(r) for r in rows]
