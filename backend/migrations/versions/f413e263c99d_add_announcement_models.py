"""add_announcement_models

Revision ID: f413e263c99d
Revises: c566d1625055
Create Date: 2026-08-15 23:11:36.824128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f413e263c99d'
down_revision: Union[str, Sequence[str], None] = 'c566d1625055'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'announcements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('zone_id', sa.Integer(), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('priority', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='announcementpriority'), nullable=False),
        sa.Column('channel', sa.Enum('MOBILE_APP', 'SOCIAL_MEDIA', 'PUBLIC_PA', 'SMS', name='announcementchannel'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_announcements_event_id'), 'announcements', ['event_id'], unique=False)
    op.create_index(op.f('ix_announcements_id'), 'announcements', ['id'], unique=False)
    op.create_index(op.f('ix_announcements_zone_id'), 'announcements', ['zone_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_announcements_zone_id'), table_name='announcements')
    op.drop_index(op.f('ix_announcements_id'), table_name='announcements')
    op.drop_index(op.f('ix_announcements_event_id'), table_name='announcements')
    op.drop_table('announcements')
    op.execute('DROP TYPE announcementpriority')
    op.execute('DROP TYPE announcementchannel')
