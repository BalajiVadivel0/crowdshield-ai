"""
Pydantic schemas for the Authority Intervention & Approval Backend.

Defines the API contracts for creating, updating, and viewing interventions.
"""

from datetime import datetime
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    actor_user_id: Optional[int] = None
    actor_role: Optional[str] = None
    action: str
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    reason: Optional[str] = None
    metadata_: Optional[dict] = None

    class Config:
        from_attributes = True

from app.models.intervention import InterventionStatus


# --- Shared / Nested Models ---

class InterventionActionSchema(BaseModel):
    id: Optional[int] = None
    action_type: str = Field(..., description="The type of action recommended.")
    description: str = Field(..., description="Human-readable details of the action.")

    class Config:
        from_attributes = True


class InterventionResultSchema(BaseModel):
    id: Optional[int] = None
    approved_by_user_id: int
    approved_at: datetime
    simulation_scenario_used: Optional[str] = None
    expected_effect: Optional[str] = None
    decision_reason: str

    class Config:
        from_attributes = True


# --- Creation (AI Proposed) ---

class InterventionActionCreate(BaseModel):
    action_type: str
    description: str


class InterventionCreate(BaseModel):
    """
    Payload to create a new PROPOSED intervention.
    Called by the AI recommendation engine layer.
    """
    event_id: int
    zone_id: Optional[int] = None
    before_risk_score: float
    affected_zones: List[int] = Field(default_factory=list)
    actions: List[InterventionActionCreate] = Field(..., min_length=1)
    
    # Optional simulation reference if already simulated before creation
    simulation_scenario_used: Optional[str] = None


# --- Approval / Rejection / Cancellation / Completion ---

class ApprovalRequest(BaseModel):
    scenario: Optional[str] = Field(None, description="Simulation scenario used for decision.")
    expected_effect: Optional[str] = Field(None, description="Expected outcome.")
    decision_reason: str = Field(..., description="Required explanation for the decision.")


class RejectRequest(BaseModel):
    decision_reason: str


class CancelRequest(BaseModel):
    decision_reason: str


class CompleteRequest(BaseModel):
    after_risk_score: Optional[float] = None


# --- Response ---

class InterventionResponse(BaseModel):
    """
    Full representation of an Intervention, including actions and result audit.
    """
    id: int
    event_id: int
    zone_id: Optional[int] = None
    status: InterventionStatus
    
    before_risk_score: float
    after_risk_score: Optional[float] = None
    risk_reduction: Optional[float] = None
    affected_zones: List[int]
    
    created_at: datetime
    updated_at: datetime
    
    actions: List[InterventionActionSchema] = []
    result: Optional[InterventionResultSchema] = None

    class Config:
        from_attributes = True
