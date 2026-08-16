"""
Zone model.

A Zone is a named spatial subdivision within a Venue/Event (e.g. Gate A, Stage
Area, VIP Section). Crowd readings, risk assessments, and routing graph nodes
are all keyed by zone_id.

Fields:
    id          — Primary key.
    event_id    — FK to the owning Event (required).
    name        — Display label for the zone (e.g. "Zone A", "Main Stage").
    capacity    — Maximum safe occupancy (persons). Used by crowd metrics to
                  compute density_percent.
    status      — ACTIVE / CLOSED / RESTRICTED.
    created_at  — UTC creation timestamp.
"""

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class ZoneStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RESTRICTED = "RESTRICTED"


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, index=True)

    # Every zone belongs to exactly one event
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)

    name = Column(String(200), nullable=False)
    capacity = Column(Integer, nullable=False, default=500)
    status = Column(
        Enum(ZoneStatus),
        nullable=False,
        default=ZoneStatus.ACTIVE,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        nullable=False,
    )

    # Relationships
    event = relationship("Event", back_populates="zones")
