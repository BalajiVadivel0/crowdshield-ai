from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field

from app.ai.recommendation_engine.models import Recommendation, ActionType, RecommendationPriority, TriggeringCondition
from app.models.recommendation import RecommendationStatus

class RecommendationResponse(Recommendation):
    id: int = Field(description="Database ID")
    status: RecommendationStatus = Field(description="Current status of the recommendation")
    created_at: datetime = Field(description="Time of generation")
    expires_at: Optional[datetime] = Field(default=None, description="Time of expiration")
    
    class Config:
        orm_mode = True

class RecommendationSimulationResponse(BaseModel):
    recommendation_id: int
    simulated: bool
    baseline_peak_network_risk: Optional[float] = None
    scenario_peak_network_risk: Optional[float] = None
    risk_reduction_delta: Optional[float] = None
    risk_reduction_percentage: Optional[float] = None
    critical_zone_count: Optional[int] = None
    high_risk_zone_count: Optional[int] = None
    scenario_score: Optional[float] = None
    simulation_horizon_minutes: Optional[int] = None
    affected_zones: Optional[List[int]] = None
    explanation: Optional[str] = None

class RecommendationActionRequest(BaseModel):
    reason: Optional[str] = None
