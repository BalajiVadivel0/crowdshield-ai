from datetime import datetime
import enum

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class AlertType(enum.Enum):
    CONGESTION_WARNING = "CONGESTION_WARNING"
    HIGH_RISK_WARNING = "HIGH_RISK_WARNING"
    CRITICAL_DANGER = "CRITICAL_DANGER"
    ROUTE_REDIRECTION = "ROUTE_REDIRECTION"
    EVACUATION_GUIDANCE = "EVACUATION_GUIDANCE"
    INCIDENT_NOTIFICATION = "INCIDENT_NOTIFICATION"
    SAFE_STATUS_UPDATE = "SAFE_STATUS_UPDATE"


class AlertSeverity(enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    event_id = Column(Integer, index=True, nullable=False)
    zone_id = Column(Integer, index=True, nullable=True)
    
    alert_type = Column(Enum(AlertType), nullable=False)
    severity = Column(Enum(AlertSeverity), nullable=False)
    
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    language = Column(String, default="en", nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
