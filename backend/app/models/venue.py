from sqlalchemy import Column, Integer, String, JSON
from app.core.database import Base

class Venue(Base):
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    location_details = Column(JSON, nullable=True)
    max_capacity = Column(Integer, nullable=True)
