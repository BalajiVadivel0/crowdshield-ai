from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text, JSON
from app.core.database import Base

class AuditLog(Base):
    """
    Generic append-only audit trail for entity state transitions and actions.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), nullable=False)
    
    actor_user_id = Column(Integer, nullable=True, index=True)
    actor_role = Column(String(50), nullable=True)
    
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    
    event_id = Column(Integer, nullable=True, index=True)
    zone_id = Column(Integer, nullable=True, index=True)
    
    action = Column(String(100), nullable=False)
    
    previous_state = Column(String(100), nullable=True)
    new_state = Column(String(100), nullable=True)
    
    reason = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
