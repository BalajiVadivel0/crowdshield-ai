import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class IncidentType(enum.Enum):
    CROWD_CONGESTION = "CROWD_CONGESTION"
    BLOCKED_ROUTE = "BLOCKED_ROUTE"
    MEDICAL_EMERGENCY = "MEDICAL_EMERGENCY"
    CROWD_PANIC = "CROWD_PANIC"
    FALL = "FALL"
    SECURITY_ISSUE = "SECURITY_ISSUE"
    OTHER = "OTHER"


class IncidentSeverity(enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class IncidentReport(Base):
    __tablename__ = "incident_reports"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    zone_id = Column(Integer, index=True, nullable=True)
    
    incident_type = Column(Enum(IncidentType), nullable=False)
    description = Column(Text, nullable=False)
    
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    severity = Column(Enum(IncidentSeverity), nullable=False)
    status = Column(Enum(IncidentStatus), default=IncidentStatus.OPEN, nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), onupdate=lambda: datetime.utcnow(), nullable=False)

    user = relationship("User")
