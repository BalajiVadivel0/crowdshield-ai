"""
Crowd intelligence endpoint.

GET /api/v1/crowd-intelligence/{event_id}

Aggregates the latest crowd reading, risk assessment, and prediction for
every zone in the event and returns an event-wide intelligence snapshot via
CrowdIntelligenceService.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, RequireRole
from app.models.user import UserRole
from app.schemas.crowd_intelligence import EventCrowdIntelligence
from app.services.crowd_ingestion_service import CrowdIngestionService

router = APIRouter()


@router.get("/{event_id}", response_model=EventCrowdIntelligence, dependencies=[Depends(RequireRole([UserRole.CITIZEN, UserRole.AUTHORITY]))])
async def get_event_intelligence(
    event_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the current event-level crowd intelligence snapshot.

    Aggregates the most recent readings and risk assessments across all zones
    in the event. Returns an empty snapshot if no data has been ingested yet.
    """
    service = CrowdIngestionService(db)
    try:
        intelligence = await service._aggregate_intelligence(event_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to aggregate crowd intelligence. Check server logs.",
        ) from exc

    return intelligence
