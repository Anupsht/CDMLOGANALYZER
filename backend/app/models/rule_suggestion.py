"""Phase 9 — rule suggestions (human-in-the-loop workflow, spec §7).

Patterns detected by the analytics module can be recorded as *suggestions*.
The workflow is strictly manual:

    Pattern → Suggested Rule → Human Review → Approval → Production

"Production" is **never** automatic: the diagnostics engine reads only
``config/diagnostics/rules.yaml`` (+ per-model overlays). An APPROVED
suggestion is an instruction for a human to adapt and copy the draft rule
into that YAML (the existing YAML-only swap path). Nothing in
``app/analysis/`` imports this module.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# SUGGESTED → UNDER_REVIEW → APPROVED → INCORPORATED (manual YAML edit)
#                      └→ REJECTED
STATUSES = ("SUGGESTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "INCORPORATED")


class RuleSuggestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rule_suggestions"
    __table_args__ = (Index("ix_rule_suggestions_status", "status"),)

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(48), nullable=False)
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # supporting stats/evidence snapshot from the pattern detection
    pattern_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # draft rule mirroring the diagnostics rules.yaml shape (INERT)
    draft_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="SUGGESTED")
    reviewed_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    review_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
