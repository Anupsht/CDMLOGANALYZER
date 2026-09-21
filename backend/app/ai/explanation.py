"""Explanation orchestration (Phase 8): digest → provider → safety → store.

The generated explanation is persisted in ``ai_explanations`` so the
technician review step and the vendor report always reference a stable,
auditable artifact (provider + digest hash + payload).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.ai.digest import build_digest
from app.ai.provider import DeterministicComposer, get_provider
from app.ai.safety import validate_explanation
from app.core.errors import NotFoundError
from app.models.ai import AIExplanation
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)


class ExplanationService:
    def build_digest(self, session: Session, txn: Transaction) -> dict:
        return build_digest(session, txn)

    def generate(self, session: Session, txn: Transaction) -> dict:
        """Generate (and persist) an explanation for the transaction."""
        digest = self.build_digest(session, txn)

        provider = get_provider()
        safety_notes: list[str] = []
        fallback_note = None
        try:
            raw = provider.explain(digest)
        except Exception as exc:  # external LLM failure → deterministic fallback
            logger.warning(
                "AI provider failed — falling back to deterministic composer",
                extra={"operation": "ai.provider", "error": str(exc)},
            )
            fallback_note = f"provider '{provider.name}' failed ({type(exc).__name__}); deterministic fallback used"
            provider = DeterministicComposer()
            raw = provider.explain(digest)

        payload, safety_notes = validate_explanation(raw, digest)
        if fallback_note:
            safety_notes.insert(0, fallback_note)

        row = AIExplanation(
            transaction_id=txn.id,
            provider=provider.name,
            generator=getattr(provider, "generator", "deterministic"),
            model_name=getattr(provider, "model", None),
            digest_sha256=digest["digest_sha256"],
            payload=payload,
            safety_notes=safety_notes,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return self._out(row, digest, safety_notes)

    def latest(self, session: Session, txn: Transaction) -> dict | None:
        row = (
            session.query(AIExplanation)
            .filter(AIExplanation.transaction_id == txn.id)
            .order_by(AIExplanation.created_at.desc())
            .first()
        )
        if row is None:
            return None
        return self._out(row, None, row.safety_notes or [])

    def ensure(self, session: Session, txn: Transaction) -> dict:
        """Latest stored explanation, generating one if none exists."""
        existing = self.latest(session, txn)
        if existing is not None:
            return existing
        return self.generate(session, txn)

    def get_transaction(self, session: Session, txn_id: str) -> Transaction:
        txn = (
            session.query(Transaction)
            .filter(Transaction.transaction_id == txn_id)
            .first()
        )
        if txn is None:
            txn = session.get(Transaction, txn_id)
        if txn is None:
            raise NotFoundError(f"Transaction not found: {txn_id}")
        return txn

    def _out(self, row: AIExplanation, digest: dict | None, safety_notes: list[str]) -> dict:
        return {
            "id": row.id,
            "transaction_id": row.transaction_id,
            "provider": row.provider,
            "generator": row.generator,
            "model_name": row.model_name,
            "digest_sha256": row.digest_sha256,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "payload": row.payload,
            "safety_notes": safety_notes,
            "digest": digest,
        }


explanation_service = ExplanationService()
