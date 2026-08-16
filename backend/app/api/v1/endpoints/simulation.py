from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any

from app.api.dependencies import get_db, RequireRole
from app.models.user import UserRole
from app.models.zone import Zone
from app.schemas.simulation import SimulationRequest, SimulationResponse
from app.ai.simulation.service import CrowdSimulationService

router = APIRouter()

@router.post("/run", response_model=SimulationResponse)
async def run_simulation(
    request: SimulationRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(RequireRole([UserRole.AUTHORITY]))
) -> Any:
    """
    Run a simulation for a specific event and zone (AUTHORITY only).
    """
    # Validate zone and get capacity
    stmt = select(Zone).where(Zone.id == request.zone_id, Zone.event_id == request.event_id)
    res = await db.execute(stmt)
    zone = res.scalars().first()
    
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found in the specified event.")

    sim_service = CrowdSimulationService()
    
    # Generate scenario
    # Step seconds can be assumed as 60 seconds for simplicity, so total_steps = duration_minutes
    try:
        readings = sim_service.generate_scenario(
            event_id=request.event_id,
            zone_id=request.zone_id,
            zone_capacity=zone.capacity,
            scenario=request.scenario,
            total_steps=request.duration_minutes,
            step_seconds=60,
            seed=request.seed
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SimulationResponse(
        scenario=request.scenario.value,
        readings=readings
    )
