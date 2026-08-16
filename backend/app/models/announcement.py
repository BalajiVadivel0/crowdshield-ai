import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text

from app.core.database import Base


class AnnouncementChannel(enum.Enum):
    MOBILE_APP = "MOBILE_APP"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    PUBLIC_PA = "PUBLIC_PA"
    SMS = "SMS"


class AnnouncementPriority(enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, index=True, nullable=False)
    zone_id = Column(Integer, index=True, nullable=True)
    
    language = Column(String(10), nullable=False, default="en")
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    
    priority = Column(Enum(AnnouncementPriority), nullable=False)
    channel = Column(Enum(AnnouncementChannel), nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow(), nullable=False)
