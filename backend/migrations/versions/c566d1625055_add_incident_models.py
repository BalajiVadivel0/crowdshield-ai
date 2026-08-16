"""add_incident_models

Revision ID: c566d1625055
Revises: 3dc36667b90d
Create Date: 2026-08-15 23:06:04.391913

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c566d1625055'
down_revision: Union[str, Sequence[str], None] = '3dc36667b90d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'incident_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('zone_id', sa.Integer(), nullable=True),
        sa.Column('incident_type', sa.Enum('CROWD_CONGESTION', 'BLOCKED_ROUTE', 'MEDICAL_EMERGENCY', 'CROWD_PANIC', 'FALL', 'SECURITY_ISSUE', 'OTHER', name='incidenttype'), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('severity', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='incidentseverity'), nullable=False),
        sa.Column('status', sa.Enum('OPEN', 'ACKNOWLEDGED', 'INVESTIGATING', 'RESOLVED', 'REJECTED', name='incidentstatus'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incident_reports_event_id'), 'incident_reports', ['event_id'], unique=False)
    op.create_index(op.f('ix_incident_reports_id'), 'incident_reports', ['id'], unique=False)
    op.create_index(op.f('ix_incident_reports_user_id'), 'incident_reports', ['user_id'], unique=False)
    op.create_index(op.f('ix_incident_reports_zone_id'), 'incident_reports', ['zone_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_incident_reports_zone_id'), table_name='incident_reports')
    op.drop_index(op.f('ix_incident_reports_user_id'), table_name='incident_reports')
    op.drop_index(op.f('ix_incident_reports_id'), table_name='incident_reports')
    op.drop_index(op.f('ix_incident_reports_event_id'), table_name='incident_reports')
    op.drop_table('incident_reports')
    op.execute('DROP TYPE incidenttype')
    op.execute('DROP TYPE incidentseverity')
    op.execute('DROP TYPE incidentstatus')
