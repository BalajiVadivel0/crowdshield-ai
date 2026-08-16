"""
Pydantic schemas for Zone.
"""
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.zone import ZoneStatus


class ZoneCreate(BaseModel):
    event_id: int = Field(..., description="The event this zone belongs to.")
    name: str = Field(..., min_length=1, max_length=200, description="Zone display name.")
    capacity: int = Field(default=500, ge=1, description="Maximum safe occupancy.")
    status: ZoneStatus = Field(default=ZoneStatus.ACTIVE)


class ZoneResponse(ZoneCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
