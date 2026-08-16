"""Merge heads

Revision ID: 5ff9588e1bb6
Revises: c3d4e5f6a7b8, f413e263c99d
Create Date: 2026-08-16 10:51:19.686673

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ff9588e1bb6'
down_revision: Union[str, Sequence[str], None] = ('c3d4e5f6a7b8', 'f413e263c99d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
