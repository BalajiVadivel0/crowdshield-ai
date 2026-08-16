"""
Crowd Reading ingestion endpoint.

POST /api/v1/crowd-readings/

Accepts a single structured crowd measurement, runs it through the full AI
pipeline, and returns the complete result including risk, prediction, and
event-level intelligence.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.schemas.crowd_reading import CrowdReadingCreate, CrowdReadingResponse
from app.ai.risk_engine.models import RiskAssessment
from app.ai.prediction_engine.models import PredictionResult
from app.schemas.crowd_intelligence import EventCrowdIntelligence
from app.services.crowd_ingestion_service import (
    CrowdIngestionService,
    EventNotFoundError,
    ZoneNotFoundError,
)
from pydantic import BaseModel


class IngestionResponse(BaseModel):
    """Full pipeline result returned after a successful ingestion."""
    crowd_reading: CrowdReadingResponse
    risk_assessment: RiskAssessment
    prediction: PredictionResult
    crowd_intelligence: EventCrowdIntelligence


router = APIRouter()


@router.post("/", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
async def create_crowd_reading(
    data: CrowdReadingCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest a crowd reading and run the full AI pipeline.

    Validates that event_id and zone_id exist in the database before
    proceeding. Returns risk assessment, prediction, and event intelligence.
    """
    service = CrowdIngestionService(db)
    try:
        crowd_reading, risk_assessment, prediction, intelligence = await service.ingest(data)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ZoneNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        # Do not leak internal state; log in production
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal pipeline error. Check server logs for details.",
        ) from exc

    return IngestionResponse(
        crowd_reading=crowd_reading,
        risk_assessment=risk_assessment,
        prediction=prediction,
        crowd_intelligence=intelligence,
    )
