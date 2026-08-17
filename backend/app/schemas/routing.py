from typing import List, Optional
from pydantic import BaseModel
from app.ai.routing.models import SafeRouteResult

class SafeRouteRequest(BaseModel):
    event_id: int
    start_zone_id: int
    destination_zone_id: Optional[int] = None
    avoid_zone_ids: Optional[List[int]] = None

# The response directly uses the SafeRouteResult from the AI engine models
class SafeRouteResponse(SafeRouteResult):
    pass
