"""
Minimal Zone endpoints for testing and future phases.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_authority, get_current_user, verify_event_access
from app.models.zone import Zone
from app.models.zone_connection import ZoneConnection
from app.schemas.zone import ZoneCreate, ZoneResponse, ZoneConnectionResponse

router = APIRouter()


@router.post("/", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_authority)])
async def create_zone(
    zone_in: ZoneCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a new Zone for an event."""
    verify_event_access(zone_in.event_id, current_user)
    db_zone = Zone(
        event_id=zone_in.event_id,
        name=zone_in.name,
        capacity=zone_in.capacity,
        status=zone_in.status.value,
    )
    db.add(db_zone)
    await db.commit()
    await db.refresh(db_zone)
    return db_zone


@router.get("/", response_model=List[ZoneResponse], dependencies=[Depends(get_current_user)])
async def list_zones(
    event_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List zones, optionally filtered by event_id."""
    if event_id is not None:
        verify_event_access(event_id, current_user)
    elif current_user.role.value != "ADMIN":
        event_id = current_user.assigned_event_id
        if not event_id:
            return []
            
    query = select(Zone)
    if event_id is not None:
        query = query.where(Zone.event_id == event_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/connections/", response_model=List[ZoneConnectionResponse], dependencies=[Depends(get_current_user)])
async def list_zone_connections(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List zone connections for a specific event."""
    verify_event_access(event_id, current_user)
    # Since connections link zones, we query connections whose source_zone belongs to the event
    query = select(ZoneConnection).join(Zone, ZoneConnection.source_zone_id == Zone.id).where(Zone.event_id == event_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{zone_id}", response_model=ZoneResponse, dependencies=[Depends(get_current_user)])
async def get_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get a specific zone."""
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    verify_event_access(zone.event_id, current_user)
    return zone
