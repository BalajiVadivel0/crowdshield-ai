"""
Real-Time Event Service

Translates AI intelligence models into WebSocket events and pushes them
to the ConnectionManager for broadcast.
"""
import logging
from typing import List

from app.schemas.crowd_intelligence import EventCrowdIntelligence, ZoneSummary
from app.schemas.websocket_events import (
    WSEventType,
    AuthorityIntelligenceData,
    CitizenZoneAlertData,
    AlertNotificationData
)
from app.services.websocket_manager import manager
from app.ai.risk_engine.models import RiskLevel
from app.models.alert import Alert

logger = logging.getLogger(__name__)


class RealtimeEventService:
    
    async def process_intelligence_update(self, intelligence: EventCrowdIntelligence):
        """
        Receives the latest event intelligence snapshot and dispatches 
        relevant WebSocket broadcasts to Authority and Citizen clients.
        
        This method is safe to call and swallows internal exceptions 
        so it won't crash the parent HTTP request.
        """
        try:
            # 1. Always broadcast to Authority (dashboard)
            await self._broadcast_authority(intelligence)
            
            # 2. Citizen alerts are now handled by AlertService -> broadcast_alert
                
        except Exception as e:
            logger.error(f"Error in RealtimeEventService processing: {e}", exc_info=True)


    async def _broadcast_authority(self, intelligence: EventCrowdIntelligence):
        """Constructs and sends the Authority-level dashboard update."""
        
        critical_zones = []
        high_risk_zones = []
        worsening_zones = []
        
        for zone in intelligence.zone_summaries:
            if zone.current_level == RiskLevel.CRITICAL:
                critical_zones.append(zone.zone_id)
            elif zone.current_level == RiskLevel.HIGH:
                high_risk_zones.append(zone.zone_id)
                
            if zone.trend.name in ("WORSENING", "RAPID_DETERIORATION"):
                worsening_zones.append(zone.zone_id)

        payload_model = AuthorityIntelligenceData(
            overall_risk_score=intelligence.overall_risk_score,
            overall_risk_level=intelligence.overall_risk_level.value,
            event_trend=intelligence.event_trend.value,
            propagation_status=intelligence.propagation_status.value,
            critical_zones=critical_zones,
            high_risk_zones=high_risk_zones,
            worsening_zones=worsening_zones,
            event_flags=intelligence.event_flags
        )
        
        # We also pass event_id in the wrapper inside broadcast_authority if we modify it,
        # but ConnectionManager builds the envelope. Let's just pass the model dump.
        # Note: ConnectionManager doesn't embed event_id by default in the envelope, 
        # so we inject it into the payload dict.
        payload = payload_model.model_dump()
        payload["event_id"] = intelligence.event_id
        
        await manager.broadcast_authority(
            event_type=WSEventType.CROWD_INTELLIGENCE_UPDATE.value,
            payload=payload,
            event_id=intelligence.event_id
        )
        logger.info(f"Broadcasted Authority intelligence for event_id={intelligence.event_id}")


    async def broadcast_alert(self, alert: Alert):
        """Broadcasts a persisted alert to appropriate WebSocket topics."""
        payload_model = AlertNotificationData(
            alert_id=alert.id,
            zone_id=alert.zone_id,
            severity=alert.severity.value,
            alert_type=alert.alert_type.value,
            title=alert.title,
            message=alert.message,
            target_role=alert.target_role.value,
            created_at=alert.created_at.isoformat()
        )
        
        payload = payload_model.model_dump()
        payload["event_id"] = alert.event_id
        
        if alert.target_role.value == "CITIZEN" and alert.zone_id is not None:
            payload["zone_id"] = alert.zone_id
            await manager.broadcast_citizen_zone(
                zone_id=alert.zone_id,
                event_type=WSEventType.ALERT_NOTIFICATION.value,
                payload=payload,
                event_id=alert.event_id
            )
            logger.info(f"Broadcasted Citizen Alert {alert.id} to zone_id={alert.zone_id}")
        elif alert.target_role.value == "AUTHORITY":
            await manager.broadcast_authority(
                event_type=WSEventType.ALERT_NOTIFICATION.value,
                payload=payload,
                event_id=alert.event_id
            )
            logger.info(f"Broadcasted Authority Alert {alert.id} for event_id={alert.event_id}")
