from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.alert import Alert, AlertSeverity, AlertType
from app.models.user import UserRole
from app.schemas.crowd_intelligence import EventCrowdIntelligence, ZoneSummary
from app.schemas.websocket_events import AlertNotificationData

class AlertService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def process_intelligence_and_broadcast(self, intelligence: EventCrowdIntelligence):
        """
        Main entrypoint from the crowd ingestion pipeline.
        Generates alerts, persists them, and delegates broadcast.
        """
        # 1. Generate alerts
        new_alerts = await self.generate_alerts_from_intelligence(intelligence)
        
        # 2. Delegate WebSocket broadcasting
        if new_alerts:
            # Import here to avoid circular imports if any
            from app.services.realtime_event_service import RealtimeEventService
            realtime_service = RealtimeEventService()
            for alert in new_alerts:
                await realtime_service.broadcast_alert(alert)

    async def generate_alerts_from_intelligence(self, intelligence: EventCrowdIntelligence) -> List[Alert]:
        """
        Evaluates the current crowd intelligence and generates persisted alerts if thresholds are breached.
        """
        generated_alerts = []

        # 1. Authority Event-Wide Alerting
        if intelligence.overall_risk_level.value in ("CRITICAL", "HIGH"):
            severity = AlertSeverity.CRITICAL if intelligence.overall_risk_level.value == "CRITICAL" else AlertSeverity.WARNING
            alert = await self._issue_alert_if_not_spam(
                event_id=intelligence.event_id,
                zone_id=None,
                target_role=UserRole.AUTHORITY,
                alert_type=AlertType.CRITICAL_DANGER if severity == AlertSeverity.CRITICAL else AlertType.HIGH_RISK_WARNING,
                severity=severity,
                title="Event Risk Escalation",
                message=f"Overall event risk is now {intelligence.overall_risk_level.value}. Review active interventions.",
                cooldown_minutes=15,
                expiry_minutes=60
            )
            if alert: generated_alerts.append(alert)

        # 2. Citizen Zone-Targeted Alerting
        for zone in intelligence.zone_summaries:
            if zone.current_level.value == "CRITICAL":
                alert = await self._issue_alert_if_not_spam(
                    event_id=intelligence.event_id,
                    zone_id=zone.zone_id,
                    target_role=UserRole.CITIZEN,
                    alert_type=AlertType.CRITICAL_DANGER,
                    severity=AlertSeverity.CRITICAL,
                    title="Critical Safety Alert",
                    message="This area is currently unsafe. Please move away immediately and follow safe routes.",
                    cooldown_minutes=5,
                    expiry_minutes=15
                )
                if alert: generated_alerts.append(alert)
                
            elif zone.current_level.value == "HIGH":
                alert = await self._issue_alert_if_not_spam(
                    event_id=intelligence.event_id,
                    zone_id=zone.zone_id,
                    target_role=UserRole.CITIZEN,
                    alert_type=AlertType.HIGH_RISK_WARNING,
                    severity=AlertSeverity.WARNING,
                    title="High Crowd Density",
                    message="Crowd density is increasing. Exercise caution.",
                    cooldown_minutes=10,
                    expiry_minutes=30
                )
                if alert: generated_alerts.append(alert)

            # Specific incident alerts
            if zone.surge_active:
                alert = await self._issue_alert_if_not_spam(
                    event_id=intelligence.event_id,
                    zone_id=zone.zone_id,
                    target_role=UserRole.CITIZEN,
                    alert_type=AlertType.HIGH_RISK_WARNING,
                    severity=AlertSeverity.WARNING,
                    title="Crowd Surge Detected",
                    message="Sudden crowd movement detected. Avoid the surge direction.",
                    cooldown_minutes=15,
                    expiry_minutes=30
                )
                if alert: generated_alerts.append(alert)

        return generated_alerts

    async def _issue_alert_if_not_spam(
        self,
        event_id: int,
        zone_id: Optional[int],
        target_role: UserRole,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        cooldown_minutes: int,
        expiry_minutes: int
    ) -> Optional[Alert]:
        """
        Anti-spam deduplication:
        Checks if an identical alert type for the same event/zone/role was issued within the cooldown window.
        """
        now = datetime.now(timezone.utc)
        cooldown_threshold = now - timedelta(minutes=cooldown_minutes)

        query = select(Alert).where(
            Alert.event_id == event_id,
            Alert.target_role == target_role,
            Alert.alert_type == alert_type,
            Alert.created_at >= cooldown_threshold,
            Alert.expires_at > now
        )

        if zone_id is not None:
            query = query.where(Alert.zone_id == zone_id)
        else:
            query = query.where(Alert.zone_id.is_(None))

        result = await self.session.execute(query)
        existing_alert = result.scalars().first()

        if existing_alert:
            return None  # Spam blocked

        # Issue new alert
        new_alert = Alert(
            event_id=event_id,
            zone_id=zone_id,
            target_role=target_role,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            created_at=now,
            expires_at=now + timedelta(minutes=expiry_minutes)
        )
        self.session.add(new_alert)
        await self.session.commit()
        await self.session.refresh(new_alert)
        return new_alert
