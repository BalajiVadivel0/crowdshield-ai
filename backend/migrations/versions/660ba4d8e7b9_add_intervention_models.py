"""Add intervention models

Revision ID: 660ba4d8e7b9
Revises: b2c9e1f5a8d7
Create Date: 2026-08-15 22:50:12.330550

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '660ba4d8e7b9'
down_revision: Union[str, Sequence[str], None] = 'b2c9e1f5a8d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'interventions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('zone_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('PROPOSED', 'SIMULATING', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'ACTIVATED', 'COMPLETED', 'CANCELLED', name='interventionstatus'), nullable=False),
        sa.Column('before_risk_score', sa.Float(), nullable=False),
        sa.Column('after_risk_score', sa.Float(), nullable=True),
        sa.Column('risk_reduction', sa.Float(), nullable=True),
        sa.Column('affected_zones', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_interventions_event_id'), 'interventions', ['event_id'], unique=False)
    op.create_index(op.f('ix_interventions_id'), 'interventions', ['id'], unique=False)
    op.create_index(op.f('ix_interventions_status'), 'interventions', ['status'], unique=False)
    op.create_index(op.f('ix_interventions_zone_id'), 'interventions', ['zone_id'], unique=False)

    op.create_table(
        'intervention_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('intervention_id', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['intervention_id'], ['interventions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_intervention_actions_id'), 'intervention_actions', ['id'], unique=False)
    op.create_index(op.f('ix_intervention_actions_intervention_id'), 'intervention_actions', ['intervention_id'], unique=False)

    op.create_table(
        'intervention_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('intervention_id', sa.Integer(), nullable=False),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('simulation_scenario_used', sa.String(length=100), nullable=True),
        sa.Column('expected_effect', sa.Text(), nullable=True),
        sa.Column('decision_reason', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['intervention_id'], ['interventions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_intervention_results_approved_by_user_id'), 'intervention_results', ['approved_by_user_id'], unique=False)
    op.create_index(op.f('ix_intervention_results_id'), 'intervention_results', ['id'], unique=False)
    op.create_index(op.f('ix_intervention_results_intervention_id'), 'intervention_results', ['intervention_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_intervention_results_intervention_id'), table_name='intervention_results')
    op.drop_index(op.f('ix_intervention_results_id'), table_name='intervention_results')
    op.drop_index(op.f('ix_intervention_results_approved_by_user_id'), table_name='intervention_results')
    op.drop_table('intervention_results')
    
    op.drop_index(op.f('ix_intervention_actions_intervention_id'), table_name='intervention_actions')
    op.drop_index(op.f('ix_intervention_actions_id'), table_name='intervention_actions')
    op.drop_table('intervention_actions')
    
    op.drop_index(op.f('ix_interventions_zone_id'), table_name='interventions')
    op.drop_index(op.f('ix_interventions_status'), table_name='interventions')
    op.drop_index(op.f('ix_interventions_id'), table_name='interventions')
    op.drop_index(op.f('ix_interventions_event_id'), table_name='interventions')
    op.drop_table('interventions')
    op.execute('DROP TYPE interventionstatus')
