from typing import List, Optional
from pydantic import BaseModel
from app.ai.simulation.scenarios import ScenarioType
from app.schemas.crowd_reading import CrowdReadingCreate

class SimulationRequest(BaseModel):
    event_id: int
    zone_id: int
    scenario: ScenarioType
    duration_minutes: int = 10
    seed: Optional[int] = None

class SimulationResponse(BaseModel):
    scenario: str
    readings: List[CrowdReadingCreate]
