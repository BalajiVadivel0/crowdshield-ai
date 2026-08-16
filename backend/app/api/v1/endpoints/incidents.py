from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_user, require_authority
from app.models.user import User
from app.schemas.incident import IncidentReportCreate, IncidentReportResponse, IncidentStatusUpdate
from app.services.incident_service import IncidentService

router = APIRouter()


@router.post("/", response_model=IncidentReportResponse, status_code=201)
async def create_incident(
    data: IncidentReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new citizen incident report."""
    data.user_id = current_user.id
    service = IncidentService(db)
    return await service.create_incident(data)


@router.get("/", response_model=List[IncidentReportResponse], dependencies=[Depends(get_current_user)])
async def list_incidents(
    event_id: Optional[int] = None,
    zone_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """List incident reports, optionally filtered by event or zone."""
    service = IncidentService(db)
    return await service.list_incidents(event_id, zone_id)


@router.get("/{incident_id}", response_model=IncidentReportResponse, dependencies=[Depends(get_current_user)])
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific incident report by ID."""
    service = IncidentService(db)
    incident = await service.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.patch("/{incident_id}/status", response_model=IncidentReportResponse, dependencies=[Depends(require_authority)])
async def update_incident_status(
    incident_id: int,
    status_update: IncidentStatusUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update the status of an incident report."""
    service = IncidentService(db)
    try:
        return await service.update_status(incident_id, status_update)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))
