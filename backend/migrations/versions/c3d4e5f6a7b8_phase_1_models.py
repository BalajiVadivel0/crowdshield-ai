"""phase 1 models

Revision ID: c3d4e5f6a7b8
Revises: b2c9e1f5a8d7
Create Date: 2026-08-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c9e1f5a8d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create events table
    op.create_table('events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('PLANNED', 'ACTIVE', 'COMPLETED', 'CANCELLED', name='eventstatus'), nullable=False),
        sa.Column('venue_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_events_id'), 'events', ['id'], unique=False)
    op.create_index(op.f('ix_events_name'), 'events', ['name'], unique=False)
    op.create_index(op.f('ix_events_status'), 'events', ['status'], unique=False)
    op.create_index(op.f('ix_events_venue_id'), 'events', ['venue_id'], unique=False)

    # 2. Create zones table
    op.create_table('zones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('ACTIVE', 'CLOSED', 'RESTRICTED', name='zonestatus'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_zones_id'), 'zones', ['id'], unique=False)
    op.create_index(op.f('ix_zones_event_id'), 'zones', ['event_id'], unique=False)
    op.create_index(op.f('ix_zones_status'), 'zones', ['status'], unique=False)

    # 3. Create risk_assessments table
    op.create_table('risk_assessments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('zone_id', sa.Integer(), nullable=False),
        sa.Column('crowd_reading_id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('risk_level', sa.String(length=20), nullable=False),
        sa.Column('risk_type', sa.String(length=40), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('density_risk', sa.Float(), nullable=False),
        sa.Column('growth_risk', sa.Float(), nullable=False),
        sa.Column('movement_conflict_risk', sa.Float(), nullable=False),
        sa.Column('speed_reduction_risk', sa.Float(), nullable=False),
        sa.Column('surge_signal', sa.Boolean(), nullable=False),
        sa.Column('reverse_flow_signal', sa.Boolean(), nullable=False),
        sa.Column('bottleneck_signal', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['crowd_reading_id'], ['crowd_readings.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.ForeignKeyConstraint(['zone_id'], ['zones.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_risk_assessments_id'), 'risk_assessments', ['id'], unique=False)
    op.create_index(op.f('ix_risk_assessments_event_id'), 'risk_assessments', ['event_id'], unique=False)
    op.create_index(op.f('ix_risk_assessments_zone_id'), 'risk_assessments', ['zone_id'], unique=False)
    op.create_index(op.f('ix_risk_assessments_crowd_reading_id'), 'risk_assessments', ['crowd_reading_id'], unique=False)
    op.create_index(op.f('ix_risk_assessments_timestamp'), 'risk_assessments', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_risk_assessments_timestamp'), table_name='risk_assessments')
    op.drop_index(op.f('ix_risk_assessments_crowd_reading_id'), table_name='risk_assessments')
    op.drop_index(op.f('ix_risk_assessments_zone_id'), table_name='risk_assessments')
    op.drop_index(op.f('ix_risk_assessments_event_id'), table_name='risk_assessments')
    op.drop_index(op.f('ix_risk_assessments_id'), table_name='risk_assessments')
    op.drop_table('risk_assessments')
    
    op.drop_index(op.f('ix_zones_status'), table_name='zones')
    op.drop_index(op.f('ix_zones_event_id'), table_name='zones')
    op.drop_index(op.f('ix_zones_id'), table_name='zones')
    op.drop_table('zones')
    
    op.drop_index(op.f('ix_events_venue_id'), table_name='events')
    op.drop_index(op.f('ix_events_status'), table_name='events')
    op.drop_index(op.f('ix_events_name'), table_name='events')
    op.drop_index(op.f('ix_events_id'), table_name='events')
    op.drop_table('events')
