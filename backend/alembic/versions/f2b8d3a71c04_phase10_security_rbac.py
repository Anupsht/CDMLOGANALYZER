"""Phase 10: security, RBAC, sessions, cases, audit columns

Revision ID: f2b8d3a71c04
Revises: e7a41c92bf05
Create Date: 2026-09-22

Adds authentication columns to ``users`` (password hash, lockout state),
the ``auth_sessions`` and ``cases`` tables, and ``ip``/``result`` columns
to the append-only ``audit_logs`` table. Existing role strings are
normalized to uppercase (``service`` stays the non-interactive account).
"""

from alembic import op
import sqlalchemy as sa

revision = "f2b8d3a71c04"
down_revision = "e7a41c92bf05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- users: authentication columns -----------------------------------
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET role = UPPER(role)")

    # ---- server-side sessions ---------------------------------------------
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])

    # ---- cases --------------------------------------------------------------
    op.create_table(
        "cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="MEDIUM"),
        sa.Column(
            "machine_id",
            sa.String(length=36),
            sa.ForeignKey("machines.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("transaction_ref", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_machine_id", "cases", ["machine_id"])
    op.create_index("ix_cases_transaction_ref", "cases", ["transaction_ref"])

    # ---- audit trail: who / from where / outcome -----------------------------
    op.add_column("audit_logs", sa.Column("ip", sa.String(length=64), nullable=True))
    op.add_column(
        "audit_logs",
        sa.Column("result", sa.String(length=16), nullable=False, server_default="success"),
    )


def downgrade() -> None:
    op.drop_column("audit_logs", "result")
    op.drop_column("audit_logs", "ip")
    op.drop_index("ix_cases_transaction_ref", table_name="cases")
    op.drop_index("ix_cases_machine_id", table_name="cases")
    op.drop_index("ix_cases_status", table_name="cases")
    op.drop_table("cases")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "password_hash")
