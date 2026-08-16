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
    current_risk: float
    simulated_risk: float
    risk_reduction: float
    affected_zones: List[int]

class RecommendationActionRequest(BaseModel):
    reason: Optional[str] = None
