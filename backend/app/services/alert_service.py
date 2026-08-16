from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.alert import Alert, AlertSeverity, AlertType
from app.services.location_service import LocationService


class ActiveUser:
    """Mock representation of a user's current reported state for evaluation."""
    def __init__(self, user_id: int, lat: float, lon: float):
        self.user_id = user_id
        self.lat = lat
        self.lon = lon


class AlertService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate_targeted_alerts(
        self,
        event_id: int,
        critical_zones: List[int],
        approaching_zones: List[int],
        route_changes: List[int],
        active_users: List[ActiveUser]
    ) -> List[Alert]:
        """
        Evaluates active users against current danger zones and route changes,
        generating alerts for those affected.
        """
        generated_alerts = []

        for user in active_users:
            current_zone = LocationService.resolve_zone(user.lat, user.lon)

            # 1. Target users inside critical zones
            if current_zone in critical_zones:
                alert = await self._issue_alert_if_not_spam(
                    user_id=user.user_id,
                    event_id=event_id,
                    zone_id=current_zone,
                    alert_type=AlertType.CRITICAL_DANGER,
                    severity=AlertSeverity.CRITICAL,
                    title="CRITICAL DANGER",
                    message="Evacuate the area immediately via the nearest safe exit.",
                    cooldown_minutes=5,
                    expiry_minutes=15
                )
                if alert: generated_alerts.append(alert)

            # 2. Target users approaching dangerous zones
            # We check if they are approaching any of the zones in `approaching_zones`
            # and they are NOT already inside a critical zone (to prevent double alerting).
            elif any(LocationService.is_approaching_zone(user.lat, user.lon, z) for z in approaching_zones):
                # Identify the specific zone they are approaching for the alert
                approached_zone = next(z for z in approaching_zones if LocationService.is_approaching_zone(user.lat, user.lon, z))
                
                alert = await self._issue_alert_if_not_spam(
                    user_id=user.user_id,
                    event_id=event_id,
                    zone_id=approached_zone,
                    alert_type=AlertType.HIGH_RISK_WARNING,
                    severity=AlertSeverity.WARNING,
                    title="DANGER AHEAD",
                    message="You are approaching a high-risk zone. Please alter your route.",
                    cooldown_minutes=10,
                    expiry_minutes=30
                )
                if alert: generated_alerts.append(alert)

            # 3. Target users affected by route redirection
            # For this MVP, if a user's current zone is in the route_changes list, we alert them.
            if current_zone in route_changes:
                alert = await self._issue_alert_if_not_spam(
                    user_id=user.user_id,
                    event_id=event_id,
                    zone_id=current_zone,
                    alert_type=AlertType.ROUTE_REDIRECTION,
                    severity=AlertSeverity.INFO,
                    title="ROUTE REDIRECTION",
                    message="Safety personnel have redirected routes in your area. Follow the digital signs.",
                    cooldown_minutes=30,
                    expiry_minutes=60
                )
                if alert: generated_alerts.append(alert)

        return generated_alerts

    async def _issue_alert_if_not_spam(
        self,
        user_id: int,
        event_id: int,
        zone_id: int,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        cooldown_minutes: int,
        expiry_minutes: int
    ) -> Optional[Alert]:
        """
        Anti-spam logic: Does not create an alert if an identical one was issued
        recently (within cooldown) and hasn't expired.
        """
        now = datetime.utcnow()
        cooldown_threshold = now - timedelta(minutes=cooldown_minutes)

        query = select(Alert).where(
            Alert.user_id == user_id,
            Alert.zone_id == zone_id,
            Alert.alert_type == alert_type,
            Alert.created_at >= cooldown_threshold,
            Alert.expires_at > now
        )
        
        result = await self.session.execute(query)
        existing_alert = result.scalars().first()

        if existing_alert:
            return None  # Spam blocked

        # Issue new alert
        new_alert = Alert(
            user_id=user_id,
            event_id=event_id,
            zone_id=zone_id,
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
