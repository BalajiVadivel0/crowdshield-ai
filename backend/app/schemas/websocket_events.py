"""
Schemas for Real-Time WebSocket Events.

Defines the structure of messages sent over WebSockets to Authority and Citizen clients.
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class WSEventType(str, Enum):
    CROWD_READING_UPDATE = "CROWD_READING_UPDATE"
    RISK_UPDATE = "RISK_UPDATE"
    PREDICTION_UPDATE = "PREDICTION_UPDATE"
    CROWD_INTELLIGENCE_UPDATE = "CROWD_INTELLIGENCE_UPDATE"
    CRITICAL_ZONE_ALERT = "CRITICAL_ZONE_ALERT"
    ALERT_NOTIFICATION = "ALERT_NOTIFICATION"
    RECOMMENDATIONS_UPDATE = "RECOMMENDATIONS_UPDATE"


class AuthorityIntelligenceData(BaseModel):
    """Payload for CROWD_INTELLIGENCE_UPDATE events sent to Authority clients."""
    overall_risk_score: float
    overall_risk_level: str
    event_trend: str
    propagation_status: str
    critical_zones: List[int]
    high_risk_zones: List[int]
    worsening_zones: List[int]
    event_flags: List[str]


class CitizenZoneAlertData(BaseModel):
    """Payload for CRITICAL_ZONE_ALERT or RISK_UPDATE events sent to Citizen clients."""
    risk_level: str
    risk_score: float
    message: str
    recommended_action: Optional[str] = None
    trend: str

class AlertNotificationData(BaseModel):
    """Payload for ALERT_NOTIFICATION events sent to both Authority and Citizen clients."""
    alert_id: int
    zone_id: Optional[int]
    severity: str
    alert_type: str
    title: str
    message: str
    target_role: str
    created_at: str
