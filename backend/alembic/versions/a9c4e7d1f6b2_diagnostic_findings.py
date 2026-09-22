"""diagnostic findings

Revision ID: a9c4e7d1f6b2
Revises: c7d21e5a8f40
Create Date: 2026-09-20 10:12:44.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a9c4e7d1f6b2'
down_revision = 'c7d21e5a8f40'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('diagnostic_findings',
    sa.Column('transaction_id', sa.String(length=36), nullable=False),
    sa.Column('finding_id', sa.String(length=96), nullable=False),
    sa.Column('rule_id', sa.String(length=96), nullable=False),
    sa.Column('diagnosis_class', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=True),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('confidence', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('interpretation', sa.Text(), nullable=False),
    sa.Column('possible_causes', sa.JSON(), nullable=True),
    sa.Column('recommended_action', sa.Text(), nullable=True),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('cash_states', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_diagnostic_findings_transaction_id_transactions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_diagnostic_findings'))
    )
    op.create_index(op.f('ix_diagnostic_findings_txn'), 'diagnostic_findings', ['transaction_id'], unique=False)
    op.create_index(op.f('ix_diagnostic_findings_class'), 'diagnostic_findings', ['diagnosis_class'], unique=False)


def downgrade() -> None:
    op.drop_table('diagnostic_findings')
