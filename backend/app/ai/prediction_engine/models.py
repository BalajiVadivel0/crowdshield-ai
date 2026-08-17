"""
Prediction Engine Models.

Defines the output contracts for the deterministic near-term risk forecaster.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.ai.risk_engine.models import RiskLevel, RiskType


class TrendDirection(str, Enum):
    """Simple deterministic trend classification."""
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    WORSENING = "WORSENING"


class ForecastPoint(BaseModel):
    """
    A prediction at a specific time horizon.
    """
    horizon_minutes: int = Field(description="Minutes into the future.")
    predicted_score: float = Field(ge=0.0, le=100.0, description="Predicted risk score (0-100).")
    predicted_level: RiskLevel = Field(description="Categorical risk level.")
    predicted_risk_type: RiskType = Field(description="Predicted dominant risk condition.")


class SupportingMetrics(BaseModel):
    """
    Preserved context for UI and recommendation engines.
    """
    current_score: float
    score_trend_slope: float = Field(description="Risk points per minute.")
    density_trend_slope: float = Field(description="Density % per minute.")
    speed_trend_slope: float = Field(description="Speed m/s per minute.")
    current_risk_type: RiskType


class PredictionResult(BaseModel):
    """
    Structured result of a near-term risk forecast.
    """
    event_id: int
    zone_id: int
    generated_at: datetime = Field(description="When this prediction was made (UTC).")
    
    # 0 to 100 confidence scale
    confidence: float = Field(ge=0.0, le=100.0)
    
    trend_direction: TrendDirection
    
    forecasts: List[ForecastPoint] = Field(description="Predictions for different time horizons (e.g. 5, 10, 15).")
    
    time_to_critical_minutes: Optional[float] = Field(
        default=None,
        description="Estimated minutes until CRITICAL risk threshold is crossed. None if stable or improving."
    )
    
    explanation: str = Field(description="Human-readable explanation of the trend and forecast.")
    
    supporting_metrics: Optional[SupportingMetrics] = Field(
        default=None,
        description="Internal metrics supporting the prediction."
    )


class PropagationResult(BaseModel):
    """
    Structured result of a single step of crowd propagation between two zones.
    """
    source_zone_id: str = Field(description="The zone generating outward pressure.")
    destination_zone_id: str = Field(description="The downstream zone receiving flow.")
    estimated_flow: float = Field(description="Estimated number of people transferring (flow rate per tick).")
    propagation_time: float = Field(description="Simulation tick or horizon minutes where this flow occurs.")
    source_pressure: float = Field(description="Calculated pressure of the source zone before distribution.")
    destination_pressure_change: float = Field(description="The corresponding increase in pressure/density at the destination.")
    reason: str = Field(description="Explainable string detailing why the flow was generated and bounded.")
