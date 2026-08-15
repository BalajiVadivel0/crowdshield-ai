"""
CrowdReading model.

Represents a single crowd measurement snapshot for a specific event
zone at a specific point in time. This is the primary data contract
consumed by the Risk Engine.

Note: event_id and zone_id are plain integer foreign keys. The FK
constraints will be added once the Event and Zone models are introduced
by the shared integration task. For now, integrity is enforced at the
service layer.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.core.database import Base


class CrowdReading(Base):
    """
    Persisted crowd measurement for a single zone at a single timestamp.

    Fields:
        event_id            — The live event this reading belongs to.
        zone_id             — The spatial zone within the venue.
        timestamp           — UTC datetime of the measurement.
        person_count        — Estimated number of persons in the zone.
        density_percent     — Crowd density as a percentage of zone capacity (0–100).
        average_speed       — Mean movement speed of detected persons (m/s, ≥ 0).
        dominant_direction  — Primary movement direction (N/NE/E/SE/S/SW/W/NW/CONFLICTED).
        crowd_growth_rate   — Percentage change in person_count per minute vs prior reading.
        congestion_score    — Composite congestion level (0–100). Derived, not raw sensor data.
        surge_indicator     — True when crowd_growth_rate exceeds the surge threshold.
        reverse_flow_indicator — True when movement direction is CONFLICTED.
        bottleneck_indicator   — True when density is high and speed is critically low.
    """

    __tablename__ = "crowd_readings"

    id = Column(Integer, primary_key=True, index=True)

    # --- Identifiers ---
    event_id = Column(Integer, nullable=False, index=True)
    zone_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # --- Core measurements ---
    person_count = Column(Integer, nullable=False)
    density_percent = Column(Float, nullable=False)     # 0.0 – 100.0

    # --- Movement ---
    average_speed = Column(Float, nullable=False)       # m/s, >= 0.0
    dominant_direction = Column(String(16), nullable=True)

    # --- Derived crowd metrics ---
    crowd_growth_rate = Column(Float, nullable=True)    # % per minute; None for first reading
    congestion_score = Column(Float, nullable=False)    # 0.0 – 100.0

    # --- Danger indicators ---
    surge_indicator = Column(Boolean, nullable=False, default=False)
    reverse_flow_indicator = Column(Boolean, nullable=False, default=False)
    bottleneck_indicator = Column(Boolean, nullable=False, default=False)
