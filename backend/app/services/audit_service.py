"""Audit trail service."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

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
        actor: str | None = "system",
        detail: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
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
