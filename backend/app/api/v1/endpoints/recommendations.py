from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_authority, get_current_user
from app.schemas.recommendation import RecommendationResponse, RecommendationSimulationResponse, RecommendationActionRequest
from app.services.recommendation_service import RecommendationService
from app.services.intervention_service import InterventionService
from app.schemas.intervention import InterventionResponse

router = APIRouter()

@router.get("/{event_id}", response_model=List[RecommendationResponse], dependencies=[Depends(require_authority)])
async def list_active_recommendations(
    event_id: int,
    db: AsyncSession = Depends(get_db)
):
    """List all active recommendations for an event."""
    intervention_svc = InterventionService(db)
    service = RecommendationService(db, intervention_svc)
    return await service.list_active_recommendations(event_id)

@router.post("/{recommendation_id}/simulate", response_model=RecommendationSimulationResponse, dependencies=[Depends(require_authority)])
async def simulate_recommendation(
    recommendation_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Run a what-if simulation for a recommendation."""
    intervention_svc = InterventionService(db)
    service = RecommendationService(db, intervention_svc)
    try:
        return await service.simulate_recommendation(recommendation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{recommendation_id}/approve", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def approve_recommendation(
    recommendation_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Approve a recommendation and create an intervention."""
    intervention_svc = InterventionService(db)
    service = RecommendationService(db, intervention_svc)
    try:
        rec, intervention = await service.approve_recommendation(recommendation_id, current_user.id)
        return intervention
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{recommendation_id}/reject", response_model=RecommendationResponse, dependencies=[Depends(require_authority)])
async def reject_recommendation(
    recommendation_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reject a recommendation."""
    intervention_svc = InterventionService(db)
    service = RecommendationService(db, intervention_svc)
    try:
        return await service.reject_recommendation(recommendation_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
