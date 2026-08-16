"""
API endpoints for Authority Interventions.

Handles RESTful routing and input validation, delegating business logic
to the InterventionService.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.schemas.intervention import (
    ApprovalRequest,
    CancelRequest,
    CompleteRequest,
    InterventionCreate,
    InterventionResponse,
    RejectRequest,
)
from app.services.intervention_service import InterventionService


router = APIRouter()


@router.post("/", response_model=InterventionResponse, status_code=201)
async def create_intervention(
    data: InterventionCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new PROPOSED intervention from AI recommendations."""
    service = InterventionService(db)
    return await service.create_intervention(data)


@router.get("/", response_model=List[InterventionResponse])
async def list_interventions(
    event_id: int = None,
    db: AsyncSession = Depends(get_db)
):
    """List all interventions, optionally filtered by event_id."""
    service = InterventionService(db)
    return await service.list_interventions(event_id)


@router.get("/{intervention_id}", response_model=InterventionResponse)
async def get_intervention(
    intervention_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific intervention by ID."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    return intervention


@router.post("/{intervention_id}/simulate", response_model=InterventionResponse)
async def simulate_intervention(
    intervention_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Transition intervention to SIMULATING."""
    service = InterventionService(db)
    try:
        return await service.set_simulating(intervention_id)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/request_approval", response_model=InterventionResponse)
async def request_approval(
    intervention_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Transition intervention to PENDING_APPROVAL."""
    service = InterventionService(db)
    try:
        return await service.set_pending_approval(intervention_id)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/approve", response_model=InterventionResponse)
async def approve_intervention(
    intervention_id: int,
    req: ApprovalRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authority approval. Transitions to APPROVED."""
    service = InterventionService(db)
    try:
        return await service.approve_intervention(intervention_id, req)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/reject", response_model=InterventionResponse)
async def reject_intervention(
    intervention_id: int,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authority rejection. Transitions to REJECTED."""
    service = InterventionService(db)
    try:
        return await service.reject_intervention(intervention_id, req)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/activate", response_model=InterventionResponse)
async def activate_intervention(
    intervention_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Activates an approved intervention. Transitions to ACTIVATED."""
    service = InterventionService(db)
    try:
        return await service.activate_intervention(intervention_id)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/complete", response_model=InterventionResponse)
async def complete_intervention(
    intervention_id: int,
    req: CompleteRequest,
    db: AsyncSession = Depends(get_db)
):
    """Completes an active intervention. Transitions to COMPLETED."""
    service = InterventionService(db)
    try:
        return await service.complete_intervention(intervention_id, req)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/cancel", response_model=InterventionResponse)
async def cancel_intervention(
    intervention_id: int,
    req: CancelRequest,
    db: AsyncSession = Depends(get_db)
):
    """Cancels an intervention. Transitions to CANCELLED."""
    service = InterventionService(db)
    try:
        return await service.cancel_intervention(intervention_id, req)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))
