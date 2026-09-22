"""Audit trail service."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.context import current_actor, current_ip
from app.core.logging import current_request_id
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    def record(
        self,
        session: Session,
        *,
        action: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str | None = None,
        detail: dict[str, Any] | None = None,
        result: str = "success",
        ip: str | None = None,
    ) -> AuditLog:
        # Phase 10: actor/ip default to the request context when the call
        # site does not pass them explicitly (pipeline tasks stay "system").
        resolved_actor = actor or current_actor() or "system"
        entry = AuditLog(
            actor=resolved_actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            result=result or "success",
            ip=ip or current_ip(),
            request_id=current_request_id() if current_request_id() != "-" else None,
        )
        session.add(entry)
        session.flush()
        logger.info(
            "Audit event",
            extra={
                "operation": "audit.record",
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )
        return entry


audit_service = AuditService()
