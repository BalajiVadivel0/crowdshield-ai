from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, root_validator

from app.models.incident import IncidentSeverity, IncidentStatus, IncidentType


class IncidentReportCreate(BaseModel):
    event_id: int
    user_id: int
    zone_id: Optional[int] = None
    incident_type: IncidentType
    description: str = Field(..., min_length=5, description="Required description of the incident")
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    severity: IncidentSeverity = IncidentSeverity.LOW

    @root_validator(pre=True)
    def validate_location(cls, values):
        zone_id = values.get('zone_id')
        lat = values.get('latitude')
        lon = values.get('longitude')
        
        if zone_id is None and (lat is None or lon is None):
            raise ValueError("Must provide either a zone_id or both latitude and longitude.")
        
        return values


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus


class IncidentReportResponse(BaseModel):
    id: int
    event_id: int
    user_id: int
    zone_id: Optional[int] = None
    incident_type: IncidentType
    description: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    severity: IncidentSeverity
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
