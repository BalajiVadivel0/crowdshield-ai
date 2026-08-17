"""
Zone Connection model.

Represents a path or corridor between two zones in a venue.
Used to dynamically build the VenueGraph for safe routing algorithms.
"""

from sqlalchemy import Column, Integer, Float, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.core.database import Base


class ZoneConnection(Base):
    __tablename__ = "zone_connections"

    id = Column(Integer, primary_key=True, index=True)
    
    source_zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False, index=True)
    dest_zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False, index=True)
    
    distance = Column(Float, nullable=False, default=10.0) # distance in meters
    capacity = Column(Integer, nullable=False, default=1000) # throughput capacity
    is_bidirectional = Column(Boolean, nullable=False, default=True)

    # Relationships
    source_zone = relationship("Zone", foreign_keys=[source_zone_id])
    dest_zone = relationship("Zone", foreign_keys=[dest_zone_id])
