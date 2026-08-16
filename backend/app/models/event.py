"""
Event model.

Represents a live crowd event (concert, festival, sporting match, etc.) held
at a Venue. Events are the top-level entity under which zones, crowd readings,
risk assessments, interventions, and incidents are grouped.

Fields:
    id          — Primary key.
    name        — Human-readable event name (required).
    description — Optional additional context.
    status      — Lifecycle state: PLANNED / ACTIVE / COMPLETED / CANCELLED.
    venue_id    — FK to the host venue (nullable for now; venue model is minimal).
    created_at  — UTC creation timestamp.
    updated_at  — UTC last-modified timestamp.
"""

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class EventStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(
        Enum(EventStatus),
        nullable=False,
        default=EventStatus.ACTIVE,
        index=True,
    )

    # Optional FK to Venue; nullable so existing venue-less test data still works.
    venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
        nullable=False,
    )

    # Relationships
    venue = relationship("Venue", foreign_keys=[venue_id])
    zones = relationship("Zone", back_populates="event", cascade="all, delete-orphan")
