"""
Minimal Zone endpoints for testing and future phases.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_authority, get_current_user
from app.models.zone import Zone
from app.schemas.zone import ZoneCreate, ZoneResponse

router = APIRouter()


@router.post("/", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_authority)])
async def create_zone(
    zone_in: ZoneCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new Zone for an event."""
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
async def list_zones(event_id: int = None, db: AsyncSession = Depends(get_db)):
    """List zones, optionally filtered by event_id."""
    query = select(Zone)
    if event_id is not None:
        query = query.where(Zone.event_id == event_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{zone_id}", response_model=ZoneResponse, dependencies=[Depends(get_current_user)])
async def get_zone(zone_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific zone."""
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone
