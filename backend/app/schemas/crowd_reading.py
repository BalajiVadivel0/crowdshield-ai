"""
Pydantic schemas for CrowdReading.

These define the validated input (CrowdReadingCreate) and serialised
output (CrowdReadingResponse) contracts for crowd measurement data.

Design intent:
- Validation is intentionally minimal — catch clearly wrong values only.
- Business logic (e.g. computing congestion_score) lives in the service layer.
- The Risk Engine reads CrowdReadingResponse objects; it does not write them.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CrowdReadingCreate(BaseModel):
    """
    Input schema for creating a new crowd reading.

    Accepted sources:
    - Simulation engine (CrowdSimulationService)
    - Future: vision pipeline ingestion endpoint
    """

    event_id: int = Field(..., description="ID of the live event being monitored.")
    zone_id: int = Field(..., description="ID of the spatial zone within the venue.")
    timestamp: datetime = Field(..., description="UTC timestamp of this measurement.")

    # Core measurements
    person_count: int = Field(
        ..., ge=0, description="Estimated number of persons detected in the zone."
    )
    density_percent: float = Field(
        ..., ge=0.0, le=100.0, description="Crowd density as % of zone capacity."
    )
    average_speed: float = Field(
        ..., ge=0.0, description="Mean movement speed of persons in the zone (m/s)."
    )
    dominant_direction: Optional[str] = Field(
        default=None,
        description="Primary crowd movement direction. One of: N, NE, E, SE, S, SW, W, NW, CONFLICTED.",
    )

    # Derived crowd metrics
    crowd_growth_rate: Optional[float] = Field(
        default=None,
        description="% change in person_count per minute relative to the prior reading. "
        "None when no previous reading exists for this zone.",
    )
    congestion_score: float = Field(
        ..., ge=0.0, le=100.0, description="Composite congestion level (0 = clear, 100 = severe)."
    )

    # Danger indicators
    surge_indicator: bool = Field(
        default=False,
        description="True when crowd_growth_rate exceeds the surge threshold.",
    )
    reverse_flow_indicator: bool = Field(
        default=False,
        description="True when dominant_direction is CONFLICTED (opposing flows detected).",
    )
    bottleneck_indicator: bool = Field(
        default=False,
        description="True when density is high and speed is critically low.",
    )


class CrowdReadingResponse(CrowdReadingCreate):
    """
    Output schema for a persisted crowd reading.

    Extends CrowdReadingCreate with the database-assigned id.
    Consumed by the Risk Engine and all downstream services.
    """

    id: int = Field(..., description="Database primary key.")

    model_config = {"from_attributes": True}
