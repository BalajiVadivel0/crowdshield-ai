"""
Authority Intervention & Approval Backend — Database Models.

Defines the persistence layer for interventions recommended by the AI
and approved by safety authorities.

Models:
    InterventionStatus  — Enum of allowed lifecycle states.
    Intervention        — The overarching intervention record.
    InterventionAction  — Specific actions (e.g. RESTRICT_ENTRY) within an intervention.
    InterventionResult  — Audit record of simulation, approval, and expected effects.

These models ensure that the AI cannot independently act. All authority
decisions, including reasons and expected effects, are securely audited.
"""

from datetime import datetime
import enum

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class InterventionStatus(str, enum.Enum):
    """
    Lifecycle states for an intervention.
    
    Allowed transitions (enforced at service layer):
    PROPOSED -> SIMULATING -> PENDING_APPROVAL -> CANCELLED
    SIMULATING -> PENDING_APPROVAL -> CANCELLED
    PENDING_APPROVAL -> APPROVED -> REJECTED -> CANCELLED
    APPROVED -> ACTIVATED -> CANCELLED
    ACTIVATED -> COMPLETED -> CANCELLED
    COMPLETED/REJECTED/CANCELLED -> terminal.
    """
    PROPOSED = "PROPOSED"
    SIMULATING = "SIMULATING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVATED = "ACTIVATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Intervention(Base):
    """
    The overarching record for a proposed or executed intervention.
    
    Fields:
        id                — Primary key.
        event_id          — The event this intervention targets.
        zone_id           — Primary zone targeted (can be null for event-wide).
        status            — Current InterventionStatus.
        before_risk_score — Risk score before the intervention (0-100).
        after_risk_score  — Risk score after the intervention (0-100, can be null).
        risk_reduction    — Computed difference (before - after).
        affected_zones    — JSON list of zone IDs impacted by this intervention.
        created_at        — Timestamp of creation.
        updated_at        — Timestamp of last status change.
    """
    __tablename__ = "interventions"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, nullable=False, index=True)
    zone_id = Column(Integer, nullable=True, index=True)
    status = Column(Enum(InterventionStatus), nullable=False, default=InterventionStatus.PROPOSED, index=True)
    
    before_risk_score = Column(Float, nullable=False)
    after_risk_score = Column(Float, nullable=True)
    risk_reduction = Column(Float, nullable=True)
    
    affected_zones = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), onupdate=lambda: datetime.utcnow(), nullable=False)

    # Relationships
    actions = relationship("InterventionAction", back_populates="intervention", cascade="all, delete-orphan")
    result = relationship("InterventionResult", back_populates="intervention", uselist=False, cascade="all, delete-orphan")

class InterventionAction(Base):
    """
    A specific action recommended as part of an intervention.
    
    Fields:
        id              — Primary key.
        intervention_id — Parent intervention FK.
        action_type     — ActionType string (e.g. "RESTRICT_ENTRY", "ONE_WAY_FLOW").
        description     — Human-readable details.
    """
    __tablename__ = "intervention_actions"

    id = Column(Integer, primary_key=True, index=True)
    intervention_id = Column(Integer, ForeignKey("interventions.id"), nullable=False, index=True)
    action_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)

    intervention = relationship("Intervention", back_populates="actions")


class InterventionResult(Base):
    """
    Audit record for authority decisions (Approval, Rejection, Cancellation)
    and simulation outcomes.
    
    Fields:
        id                       — Primary key.
        intervention_id          — Parent intervention FK.
        approved_by_user_id      — ID of the authority user who made the decision.
        approved_at              — Timestamp of the decision.
        simulation_scenario_used — Which simulation scenario was evaluated.
        expected_effect          — Human-readable expected outcome.
        decision_reason          — Required explanation for approval/rejection/cancellation.
    """
    __tablename__ = "intervention_results"

    id = Column(Integer, primary_key=True, index=True)
    intervention_id = Column(Integer, ForeignKey("interventions.id"), nullable=False, index=True, unique=True)
    
    approved_by_user_id = Column(Integer, nullable=False, index=True)
    approved_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), nullable=False)
    
    simulation_scenario_used = Column(String(100), nullable=True)
    expected_effect = Column(Text, nullable=True)
    
    # Required for explainability
    decision_reason = Column(Text, nullable=False)

    intervention = relationship("Intervention", back_populates="result")


