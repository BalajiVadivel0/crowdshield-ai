"""Add auth roles and timestamps

Revision ID: 3d6ea6ed83f4
Revises: 5ff9588e1bb6
Create Date: 2026-08-16 10:53:16.634371

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d6ea6ed83f4'
down_revision: Union[str, Sequence[str], None] = '5ff9588e1bb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safely add created_at and updated_at
    op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
    
    # Update existing roles
    op.execute("UPDATE users SET role = 'CITIZEN' WHERE role = 'viewer'")
    
    # To enforce nullable=False safely on old rows:
    op.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('created_at', existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column('updated_at', existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'created_at')
