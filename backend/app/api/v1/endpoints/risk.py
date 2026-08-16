"""
Risk assessment endpoint.

GET /api/v1/risk/{event_id}/{zone_id}

Returns the latest persisted risk assessment for the given event/zone pair.
Does NOT recompute — always reads from the DB to reflect the state as of the
most recent crowd reading ingestion.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.api.dependencies import get_db, require_authority
from app.models.risk_assessment import RiskAssessmentRecord


class RiskAssessmentResponse(BaseModel):
    """Serialised view of the latest persisted RiskAssessmentRecord."""
    id: int
    event_id: int
    zone_id: int
    crowd_reading_id: int
    timestamp: datetime

    # Core result
    risk_score: float
    risk_level: str
    risk_type: str
    explanation: str

    # Feature breakdown
    density_risk: float
    growth_risk: float
    movement_conflict_risk: float
    speed_reduction_risk: float

    # Boolean signals
    surge_signal: bool
    reverse_flow_signal: bool
    bottleneck_signal: bool

    created_at: datetime

    model_config = {"from_attributes": True}


router = APIRouter()


@router.get("/{event_id}/{zone_id}", response_model=RiskAssessmentResponse, dependencies=[Depends(require_authority)])
async def get_latest_risk(
    event_id: int,
    zone_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve the latest persisted risk assessment for a specific zone.

    Returns 404 if no crowd reading has been ingested for this event/zone yet.
    """
    result = await db.execute(
        select(RiskAssessmentRecord)
        .where(
            RiskAssessmentRecord.event_id == event_id,
            RiskAssessmentRecord.zone_id == zone_id,
        )
        .order_by(desc(RiskAssessmentRecord.timestamp))
        .limit(1)
    )
    record = result.scalar_one_or_none()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No risk assessment found for event_id={event_id}, zone_id={zone_id}. "
                "Submit a crowd reading first."
            ),
        )

    return record
