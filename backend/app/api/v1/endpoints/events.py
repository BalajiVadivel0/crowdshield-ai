"""
Minimal Event endpoints for testing and future phases.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.models.event import Event
from app.schemas.event import EventCreate, EventResponse

router = APIRouter()


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    event_in: EventCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new Event."""
    db_event = Event(
        name=event_in.name,
        description=event_in.description,
        status=event_in.status.value,
        venue_id=event_in.venue_id,
    )
    db.add(db_event)
    await db.commit()
    await db.refresh(db_event)
    return db_event


@router.get("/", response_model=List[EventResponse])
async def list_events(db: AsyncSession = Depends(get_db)):
    """List all events."""
    result = await db.execute(select(Event))
    return list(result.scalars().all())


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific event."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
