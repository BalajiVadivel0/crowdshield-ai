from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.api.dependencies import get_db, RequireRole
from app.models.user import UserRole
from app.schemas.routing import SafeRouteRequest, SafeRouteResponse
from app.services.routing_service import RoutingService

router = APIRouter()

@router.post("/safe-route", response_model=SafeRouteResponse)
async def get_safe_route(
    request: SafeRouteRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(RequireRole([UserRole.CITIZEN, UserRole.AUTHORITY]))
) -> Any:
    """
    Get a safe route from start to destination, or to the safest exit if destination is omitted.
    """
    if request.destination_zone_id is not None:
        result = await RoutingService.get_safe_route(
            db=db,
            event_id=request.event_id,
            source_zone_id=request.start_zone_id,
            dest_zone_id=request.destination_zone_id,
            avoid_zone_ids=request.avoid_zone_ids
        )
    else:
        result = await RoutingService.get_safest_exit(
            db=db,
            event_id=request.event_id,
            source_zone_id=request.start_zone_id,
            avoid_zone_ids=request.avoid_zone_ids
        )

    if not result.is_available:
        # According to requirements, no safe route might return a 404 or just return the JSON.
        # But SafeRouteResult is designed to be returned with is_available=False and a warning.
        # The prompt says: 404/409 no safe route depending on project error conventions.
        # But it also says return a clean client facing structure using the actual engine output.
        # Let's return the JSON directly, allowing the client to read is_available.
        pass

    return result

@router.get("/safest-exit/{event_id}/{zone_id}", response_model=SafeRouteResponse)
async def get_safest_exit(
    event_id: int,
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(RequireRole([UserRole.CITIZEN, UserRole.AUTHORITY]))
) -> Any:
    """
    Get the safest exit from the given zone.
    """
    result = await RoutingService.get_safest_exit(
        db=db,
        event_id=event_id,
        source_zone_id=zone_id
    )
    return result
