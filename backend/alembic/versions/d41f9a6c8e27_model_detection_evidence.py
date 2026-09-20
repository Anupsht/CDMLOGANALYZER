"""model detection evidence

Revision ID: d41f9a6c8e27
Revises: a9c4e7d1f6b2
Create Date: 2026-09-20 11:02:18.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd41f9a6c8e27'
down_revision = 'a9c4e7d1f6b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('log_files', sa.Column('detection_evidence', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('log_files', 'detection_evidence')
