"""
Schemas for event-level Crowd Intelligence.

These represent the aggregated, venue-wide picture of crowd safety
produced by combining Risk and Prediction engine outputs across all zones.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.ai.risk_engine.models import RiskLevel, RiskType
from app.ai.prediction_engine.models import TrendDirection


class PropagationStatus(str, Enum):
    NONE = "NONE"
    DEVELOPING = "DEVELOPING"
    ELEVATED = "ELEVATED"
    SEVERE = "SEVERE"


class ZoneSummary(BaseModel):
    """
    A lightweight summary of a single zone's current and future state.
    """
    zone_id: int
    
    # Current State
    current_score: float = Field(description="Current risk score (0-100).")
    current_level: RiskLevel
    current_risk_type: RiskType
    
    # Physical metrics
    person_count: int
    density_percent: float
    average_speed: float
    congestion_score: float
    
    # Active danger signals
    surge_active: bool
    reverse_flow_active: bool
    bottleneck_active: bool
    
    # Future State
    trend: TrendDirection
    confidence: float
    predicted_5m_score: float
    predicted_10m_score: float
    predicted_15m_score: float
    
    time_to_critical: Optional[float] = None
    
    # Priority rank (lower number = higher urgency)
    urgency_score: float = Field(description="Internal score used for ranking priority.")

    # Incident Intelligence Signals
    active_incidents: int = 0
    incident_types: List[str] = Field(default_factory=list)
    highest_incident_severity: Optional[str] = None


class EventCrowdIntelligence(BaseModel):
    """
    The venue-wide safety snapshot.
    """
    event_id: int
    generated_at: datetime
    
    # Overall Event Status
    overall_risk_score: float = Field(description="Event-wide risk score (0-100).")
    overall_risk_level: RiskLevel
    event_trend: TrendDirection
    
    # Highest Urgency Zone Info
    highest_risk_zone: Optional[int]
    highest_risk_type: Optional[RiskType]
    
    # Venue physical totals
    total_people: int
    average_density: float
    highest_density: float
    average_speed: float
    
    # Counters
    congestion_zone_count: int
    critical_zone_count: int
    high_risk_zone_count: int
    worsening_zone_count: int
    
    # Cross-zone patterns
    propagation_status: PropagationStatus
    event_flags: List[str] = Field(
        default_factory=list,
        description="Event-level string flags like CRITICAL_ZONE_PRESENT, MULTI_ZONE_CONGESTION."
    )
    
    # Zone detail
    zone_summaries: List[ZoneSummary]
    priority_zones: List[int] = Field(description="Ordered list of zone_ids requiring attention first.")
