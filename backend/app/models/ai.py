"""Phase 8 — stored AI explanations (audit trail for the explanation layer).

Every generated explanation is persisted with its provider, digest hash and
safety notes so vendor reports can reference a stable artifact. Explanations
are never inputs to the deterministic analysis — they are an explanation
layer only.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIExplanation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_explanations"
    __table_args__ = (
        Index("ix_ai_explanations_txn", "transaction_id"),
    )

    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    # deterministic-rules-composer | openai-compatible-llm | …
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    # deterministic | external-llm
    generator: Mapped[str] = mapped_column(String(32), nullable=False, default="deterministic")
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    digest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # full validated explanation payload (app.ai.safety shape)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    safety_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
