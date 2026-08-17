"""
RiskAssessmentRecord model.

Persists the full output of one RiskEngine.evaluate() call so that:
  1. Clients can query the latest risk status for any zone.
  2. PredictionEngine can access historical risk time-series without
     storing raw crowd readings redundantly.

NOTE: The existing `RiskAssessment` in app/ai/risk_engine/models.py is a
Pydantic model (pure data contract). This SQLAlchemy model is the persistence
layer only — the mapping between them is handled by the ingestion service.

Fields:
    id                    — Primary key.
    event_id              — FK to events.id (matches CrowdReading.event_id).
    zone_id               — FK to zones.id (matches CrowdReading.zone_id).
    crowd_reading_id      — FK to crowd_readings.id (the source measurement).
    timestamp             — UTC timestamp of the source CrowdReading.

    risk_score            — Composite score (0–100).
    risk_level            — LOW / MEDIUM / HIGH / CRITICAL.
    risk_type             — Dominant condition classification.
    explanation           — Human-readable breakdown from RiskEngine.

    density_risk          — Normalised feature (0–100).
    growth_risk           — Normalised feature (0–100).
    movement_conflict_risk — Normalised feature (0–100).
    speed_reduction_risk  — Normalised feature (0–100).

    surge_signal          — Boolean: surge_indicator from source reading.
    reverse_flow_signal   — Boolean: reverse_flow_indicator from source reading.
    bottleneck_signal     — Boolean: bottleneck_indicator from source reading.

    created_at            — When this record was inserted.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class RiskAssessmentRecord(Base):
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, index=True)

    # Context identifiers
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False, index=True)
    crowd_reading_id = Column(
        Integer, ForeignKey("crowd_readings.id"), nullable=False, index=True
    )

    # Source timestamp (from the CrowdReading) — used by PredictionEngine for history
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # Core risk output
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String(20), nullable=False)     # LOW / MEDIUM / HIGH / CRITICAL
    risk_type = Column(String(40), nullable=False)      # STABLE / CROWD_CRUSH / etc.
    explanation = Column(Text, nullable=False)

    # Feature components (0–100 each)
    density_risk = Column(Float, nullable=False)
    growth_risk = Column(Float, nullable=False)
    movement_conflict_risk = Column(Float, nullable=False)
    speed_reduction_risk = Column(Float, nullable=False)

    # Boolean signals forwarded from source reading
    surge_signal = Column(Boolean, nullable=False, default=False)
    reverse_flow_signal = Column(Boolean, nullable=False, default=False)
    bottleneck_signal = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        nullable=False,
    )

    # Relationships
    event = relationship("Event", foreign_keys=[event_id])
    zone = relationship("Zone", foreign_keys=[zone_id])
    crowd_reading = relationship("CrowdReading", foreign_keys=[crowd_reading_id])
