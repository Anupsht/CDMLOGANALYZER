"""cash lifecycle + hardware analysis tables

Revision ID: c7d21e5a8f40
Revises: e160ec93b2c1
Create Date: 2026-09-20 09:05:12.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c7d21e5a8f40'
down_revision = 'e160ec93b2c1'
branch_labels = None
depends_on = None


def _uuid_pk(name: str) -> sa.Column:
    return sa.Column('id', sa.String(length=36), nullable=False)


def upgrade() -> None:
    op.create_table('cash_movements',
    sa.Column('transaction_id', sa.String(length=36), nullable=False),
    sa.Column('note_id', sa.String(length=64), nullable=True),
    sa.Column('from_state', sa.String(length=24), nullable=False),
    sa.Column('to_state', sa.String(length=24), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('device', sa.String(length=64), nullable=True),
    sa.Column('evidence_event', sa.String(length=48), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('note_info', sa.JSON(), nullable=True),
    sa.Column('log_file_id', sa.String(length=36), nullable=True),
    sa.Column('line_number', sa.BigInteger(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_cash_movements_transaction_id_transactions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['log_file_id'], ['log_files.id'], name=op.f('fk_cash_movements_log_file_id_log_files'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cash_movements'))
    )
    op.create_index(op.f('ix_cash_movements_txn'), 'cash_movements', ['transaction_id'], unique=False)
    op.create_index(op.f('ix_cash_movements_to_state'), 'cash_movements', ['to_state'], unique=False)

    op.create_table('sensor_events',
    sa.Column('transaction_id', sa.String(length=36), nullable=True),
    sa.Column('sensor', sa.String(length=64), nullable=False),
    sa.Column('previous_state', sa.String(length=32), nullable=True),
    sa.Column('new_state', sa.String(length=32), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('expected_state', sa.String(length=32), nullable=True),
    sa.Column('actual_state', sa.String(length=32), nullable=True),
    sa.Column('abnormal_duration_ms', sa.BigInteger(), nullable=True),
    sa.Column('device', sa.String(length=64), nullable=True),
    sa.Column('log_file_id', sa.String(length=36), nullable=True),
    sa.Column('line_number', sa.BigInteger(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_sensor_events_transaction_id_transactions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['log_file_id'], ['log_files.id'], name=op.f('fk_sensor_events_log_file_id_log_files'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sensor_events'))
    )
    op.create_index(op.f('ix_sensor_events_txn'), 'sensor_events', ['transaction_id'], unique=False)

    op.create_table('motor_events',
    sa.Column('transaction_id', sa.String(length=36), nullable=True),
    sa.Column('motor', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('stopped_at', sa.DateTime(), nullable=True),
    sa.Column('duration_ms', sa.BigInteger(), nullable=True),
    sa.Column('timeout_ms', sa.BigInteger(), nullable=True),
    sa.Column('timed_out', sa.Boolean(), nullable=False),
    sa.Column('transport_name', sa.String(length=64), nullable=True),
    sa.Column('sensor_transitions', sa.JSON(), nullable=True),
    sa.Column('device', sa.String(length=64), nullable=True),
    sa.Column('log_file_id', sa.String(length=36), nullable=True),
    sa.Column('line_number', sa.BigInteger(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('stop_line_number', sa.BigInteger(), nullable=True),
    sa.Column('stop_raw_text', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_motor_events_transaction_id_transactions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['log_file_id'], ['log_files.id'], name=op.f('fk_motor_events_log_file_id_log_files'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_motor_events'))
    )
    op.create_index(op.f('ix_motor_events_txn'), 'motor_events', ['transaction_id'], unique=False)

    op.create_table('gate_events',
    sa.Column('transaction_id', sa.String(length=36), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('command', sa.String(length=32), nullable=True),
    sa.Column('expected_state', sa.String(length=32), nullable=True),
    sa.Column('actual_state', sa.String(length=32), nullable=True),
    sa.Column('transition_ms', sa.BigInteger(), nullable=True),
    sa.Column('timeout_ms', sa.BigInteger(), nullable=True),
    sa.Column('timed_out', sa.Boolean(), nullable=False),
    sa.Column('state_mismatch', sa.Boolean(), nullable=False),
    sa.Column('device', sa.String(length=64), nullable=True),
    sa.Column('log_file_id', sa.String(length=36), nullable=True),
    sa.Column('line_number', sa.BigInteger(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('position_evidence', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_gate_events_transaction_id_transactions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['log_file_id'], ['log_files.id'], name=op.f('fk_gate_events_log_file_id_log_files'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gate_events'))
    )
    op.create_index(op.f('ix_gate_events_txn'), 'gate_events', ['transaction_id'], unique=False)
    op.create_index(op.f('ix_gate_events_kind'), 'gate_events', ['kind'], unique=False)

    op.create_table('transport_events',
    sa.Column('transaction_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('timeout_ms', sa.BigInteger(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('device', sa.String(length=64), nullable=True),
    sa.Column('log_file_id', sa.String(length=36), nullable=True),
    sa.Column('line_number', sa.BigInteger(), nullable=True),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_transport_events_transaction_id_transactions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['log_file_id'], ['log_files.id'], name=op.f('fk_transport_events_log_file_id_log_files'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transport_events'))
    )
    op.create_index(op.f('ix_transport_events_txn'), 'transport_events', ['transaction_id'], unique=False)

    op.create_table('fault_assessments',
    sa.Column('transaction_id', sa.String(length=36), nullable=True),
    sa.Column('subject_kind', sa.String(length=24), nullable=False),
    sa.Column('subject_name', sa.String(length=64), nullable=True),
    sa.Column('classification', sa.String(length=32), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('analysis_window', sa.JSON(), nullable=True),
    sa.Column('assessed_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_fault_assessments_transaction_id_transactions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fault_assessments'))
    )
    op.create_index(op.f('ix_fault_assessments_txn'), 'fault_assessments', ['transaction_id'], unique=False)
    op.create_index(op.f('ix_fault_assessments_classification'), 'fault_assessments', ['classification'], unique=False)


def downgrade() -> None:
    op.drop_table('fault_assessments')
    op.drop_table('transport_events')
    op.drop_table('gate_events')
    op.drop_table('motor_events')
    op.drop_table('sensor_events')
    op.drop_table('cash_movements')
