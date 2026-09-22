"""Phase 8: ai_explanations table

Revision ID: c3f8b62a91d4
Revises: d41f9a6c8e27
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "c3f8b62a91d4"
down_revision = "d41f9a6c8e27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_explanations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("generator", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("digest_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("safety_notes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_explanations_txn", "ai_explanations", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_explanations_txn", table_name="ai_explanations")
    op.drop_table("ai_explanations")
