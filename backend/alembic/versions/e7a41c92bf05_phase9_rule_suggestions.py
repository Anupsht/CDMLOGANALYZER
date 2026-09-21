"""Phase 9: rule_suggestions table

Revision ID: e7a41c92bf05
Revises: c3f8b62a91d4
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "e7a41c92bf05"
down_revision = "c3f8b62a91d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("pattern_type", sa.String(length=48), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("pattern_stats", sa.JSON(), nullable=True),
        sa.Column("draft_rule", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reviewed_by", sa.String(length=96), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("source_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["source_transaction_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rule_suggestions_status", "rule_suggestions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_rule_suggestions_status", table_name="rule_suggestions")
    op.drop_table("rule_suggestions")
