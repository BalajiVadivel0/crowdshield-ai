"""
API endpoints for Authority Interventions.

Handles RESTful routing and input validation, delegating business logic
to the InterventionService.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_authority, get_current_user, verify_event_access
from app.schemas.intervention import (
    ApprovalRequest,
    CancelRequest,
    CompleteRequest,
    InterventionCreate,
    InterventionResponse,
    RejectRequest,
    AuditLogResponse,
)
from app.services.intervention_service import InterventionService
from app.models.audit import AuditLog
from sqlalchemy.future import select


router = APIRouter()


@router.post("/", response_model=InterventionResponse, status_code=201, dependencies=[Depends(require_authority)])
async def create_intervention(
    data: InterventionCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a new PROPOSED intervention from AI recommendations."""
    verify_event_access(data.event_id, current_user)
    service = InterventionService(db)
    return await service.create_intervention(data, current_user)


@router.get("/", response_model=List[InterventionResponse], dependencies=[Depends(get_current_user)])
async def list_interventions(
    event_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List all interventions, optionally filtered by event_id."""
    if event_id is not None:
        verify_event_access(event_id, current_user)
    elif current_user.role != "ADMIN":
        event_id = current_user.assigned_event_id
        if not event_id:
            return []
            
    service = InterventionService(db)
    return await service.list_interventions(event_id)


@router.get("/{intervention_id}", response_model=InterventionResponse, dependencies=[Depends(get_current_user)])
async def get_intervention(
    intervention_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get a specific intervention by ID."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    return intervention

@router.get("/{intervention_id}/audit", response_model=List[AuditLogResponse], dependencies=[Depends(require_authority)])
async def get_intervention_audit(
    intervention_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get audit history for a specific intervention."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    query = select(AuditLog).where(
        AuditLog.entity_type == "INTERVENTION",
        AuditLog.entity_id == intervention_id
    ).order_by(AuditLog.timestamp.desc())
    
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/{intervention_id}/simulate", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def simulate_intervention(
    intervention_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Transition intervention to SIMULATING."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    try:
        return await service.set_simulating(intervention_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/request_approval", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def request_approval(
    intervention_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Transition intervention to PENDING_APPROVAL."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    try:
        return await service.set_pending_approval(intervention_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/approve", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def approve_intervention(
    intervention_id: int,
    req: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Authority approval. Transitions to APPROVED."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    try:
        return await service.approve_intervention(intervention_id, req, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/reject", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def reject_intervention(
    intervention_id: int,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Authority rejection. Transitions to REJECTED."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    try:
        return await service.reject_intervention(intervention_id, req, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/activate", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def activate_intervention(
    intervention_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Activates an approved intervention. Transitions to ACTIVATED."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    try:
        return await service.activate_intervention(intervention_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/complete", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def complete_intervention(
    intervention_id: int,
    req: CompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Completes an active intervention. Transitions to COMPLETED."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    try:
        return await service.complete_intervention(intervention_id, req, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{intervention_id}/cancel", response_model=InterventionResponse, dependencies=[Depends(require_authority)])
async def cancel_intervention(
    intervention_id: int,
    req: CancelRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Cancels an intervention. Transitions to CANCELLED."""
    service = InterventionService(db)
    intervention = await service.get_intervention(intervention_id)
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention not found")
    verify_event_access(intervention.event_id, current_user)
    
    try:
        return await service.cancel_intervention(intervention_id, req, current_user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
