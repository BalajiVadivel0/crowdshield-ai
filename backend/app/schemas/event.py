"""
Pydantic schemas for Event.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.event import EventStatus


class EventCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Human-readable event name.")
    description: Optional[str] = Field(default=None, description="Optional event description.")
    status: EventStatus = Field(default=EventStatus.ACTIVE)
    venue_id: Optional[int] = Field(default=None, description="ID of the host venue.")


class EventResponse(EventCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
