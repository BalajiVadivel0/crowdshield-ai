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
    CitizenZoneAlertData
)
from app.services.websocket_manager import manager
from app.ai.risk_engine.models import RiskLevel

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
            
            # 2. Check each zone for necessary Citizen alerts
            for zone_summary in intelligence.zone_summaries:
                await self._evaluate_and_broadcast_citizen_zone(intelligence.event_id, zone_summary)
                
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
            payload=payload
        )
        logger.info(f"Broadcasted Authority intelligence for event_id={intelligence.event_id}")


    async def _evaluate_and_broadcast_citizen_zone(self, event_id: int, zone_summary: ZoneSummary):
        """
        Evaluates a zone's state and sends an alert to its citizens if needed.
        We only alert for HIGH or CRITICAL risk.
        """
        if zone_summary.current_level not in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return  # Normal/Elevated conditions do not spam citizen devices
            
        event_type = (
            WSEventType.CRITICAL_ZONE_ALERT.value 
            if zone_summary.current_level == RiskLevel.CRITICAL 
            else WSEventType.RISK_UPDATE.value
        )
        
        message = "Avoid this zone."
        if zone_summary.surge_active:
            message = "Surge detected. Please move away carefully."
        elif zone_summary.bottleneck_active:
            message = "Severe bottleneck ahead. Choose an alternate route."

        payload_model = CitizenZoneAlertData(
            risk_level=zone_summary.current_level.value,
            risk_score=zone_summary.current_score,
            message=message,
            trend=zone_summary.trend.value,
            recommended_action="EVACUATE" if zone_summary.current_level == RiskLevel.CRITICAL else "CAUTION"
        )
        
        payload = payload_model.model_dump()
        payload["event_id"] = event_id
        payload["zone_id"] = zone_summary.zone_id

        await manager.broadcast_citizen_zone(
            zone_id=zone_summary.zone_id,
            event_type=event_type,
            payload=payload
        )
        logger.info(f"Broadcasted Citizen alert to zone_id={zone_summary.zone_id}")
