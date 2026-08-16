from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, JSON, Enum
from sqlalchemy.orm import relationship
import enum
from datetime import datetime, timezone
from app.core.database import Base

class RecommendationStatus(str, enum.Enum):
    GENERATED = "GENERATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"

class RecommendationModel(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    recommendation_id = Column(String, index=True) # Deterministic engine ID (e.g., 'RESTRICT_ENTRY_3')
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True) # Nullable for event-wide actions
    action_type = Column(String, nullable=False)
    priority = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    triggering_conditions = Column(JSON, nullable=False) # Store the structured list of conditions
    expected_effect = Column(String, nullable=False)
    affected_zones = Column(JSON, nullable=False) # List of ints
    
    status = Column(Enum(RecommendationStatus), default=RecommendationStatus.GENERATED, nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_intervention_id = Column(Integer, ForeignKey("interventions.id"), nullable=True)

    # Relationships
    event = relationship("Event")
    zone = relationship("Zone")
    approved_by = relationship("User")
    created_intervention = relationship("Intervention")
