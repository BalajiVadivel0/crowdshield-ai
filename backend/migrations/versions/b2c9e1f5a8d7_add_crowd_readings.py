"""Add crowd_readings table

Revision ID: b2c9e1f5a8d7
Revises: 43d8dd4324a1
Create Date: 2026-08-15 18:30:00.000000

Adds the crowd_readings table which stores time-series crowd measurement
snapshots used by the Crowd Intelligence & Risk pipeline.

Note: event_id and zone_id are plain integer columns at this stage.
Foreign key constraints to the events and zones tables will be added
in the migration that introduces those tables (shared integration task).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c9e1f5a8d7"
down_revision: Union[str, Sequence[str], None] = "43d8dd4324a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the crowd_readings table."""
    op.create_table(
        "crowd_readings",
        # Primary key
        sa.Column("id", sa.Integer(), nullable=False),
        # Identifiers (FK constraints deferred until Event/Zone models exist)
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("zone_id", sa.Integer(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        # Core measurements
        sa.Column("person_count", sa.Integer(), nullable=False),
        sa.Column("density_percent", sa.Float(), nullable=False),
        # Movement
        sa.Column("average_speed", sa.Float(), nullable=False),
        sa.Column("dominant_direction", sa.String(length=16), nullable=True),
        # Derived metrics
        sa.Column("crowd_growth_rate", sa.Float(), nullable=True),
        sa.Column("congestion_score", sa.Float(), nullable=False),
        # Danger indicators
        sa.Column("surge_indicator", sa.Boolean(), nullable=False),
        sa.Column("reverse_flow_indicator", sa.Boolean(), nullable=False),
        sa.Column("bottleneck_indicator", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Primary key index
    op.create_index(
        op.f("ix_crowd_readings_id"),
        "crowd_readings",
        ["id"],
        unique=False,
    )
    # Query patterns: "all readings for event X" and "all readings for zone Y"
    op.create_index(
        op.f("ix_crowd_readings_event_id"),
        "crowd_readings",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_crowd_readings_zone_id"),
        "crowd_readings",
        ["zone_id"],
        unique=False,
    )
    # Time-series queries: "readings for event X between T1 and T2"
    op.create_index(
        op.f("ix_crowd_readings_timestamp"),
        "crowd_readings",
        ["timestamp"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the crowd_readings table."""
    op.drop_index(op.f("ix_crowd_readings_timestamp"), table_name="crowd_readings")
    op.drop_index(op.f("ix_crowd_readings_zone_id"), table_name="crowd_readings")
    op.drop_index(op.f("ix_crowd_readings_event_id"), table_name="crowd_readings")
    op.drop_index(op.f("ix_crowd_readings_id"), table_name="crowd_readings")
    op.drop_table("crowd_readings")
