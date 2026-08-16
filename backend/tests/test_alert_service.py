from datetime import datetime, timedelta
import pytest

from app.models.alert import AlertType, AlertSeverity
from app.services.alert_service import AlertService, ActiveUser
from app.services.location_service import MOCK_ZONES


@pytest.fixture
def alert_service(db_session):
    return AlertService(db_session)


@pytest.mark.asyncio
async def test_alert_user_inside_critical_zone(alert_service):
    # Zone 10 is at 40.7128, -74.0060 (radius 50m)
    # User is exactly at the center
    user = ActiveUser(user_id=1, lat=40.7128, lon=-74.0060)
    
    alerts = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[10],
        approaching_zones=[],
        route_changes=[],
        active_users=[user]
    )
    
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.CRITICAL_DANGER
    assert alerts[0].severity == AlertSeverity.CRITICAL
    assert alerts[0].zone_id == 10
    assert alerts[0].user_id == 1


@pytest.mark.asyncio
async def test_alert_user_approaching_dangerous_zone(alert_service):
    # Zone 10 is at 40.7128, -74.0060 (radius 50m)
    # User is placed slightly outside the 50m radius, but within 250m (approaching threshold)
    # Offset by ~0.001 degrees lat is ~111m. Let's use 0.001.
    user = ActiveUser(user_id=2, lat=40.7138, lon=-74.0060)
    
    alerts = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[],
        approaching_zones=[10],
        route_changes=[],
        active_users=[user]
    )
    
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.HIGH_RISK_WARNING
    assert alerts[0].severity == AlertSeverity.WARNING
    assert alerts[0].zone_id == 10


@pytest.mark.asyncio
async def test_user_outside_affected_zones_gets_no_alert(alert_service):
    # User is far away (e.g. lat 41.0, lon -75.0)
    user = ActiveUser(user_id=3, lat=41.0000, lon=-75.0000)
    
    alerts = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[10],
        approaching_zones=[11],
        route_changes=[12],
        active_users=[user]
    )
    
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_route_change_alert(alert_service):
    # User is inside Zone 12 (40.7135, -74.0050)
    user = ActiveUser(user_id=4, lat=40.7135, lon=-74.0050)
    
    alerts = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[],
        approaching_zones=[],
        route_changes=[12],
        active_users=[user]
    )
    
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.ROUTE_REDIRECTION
    assert alerts[0].severity == AlertSeverity.INFO
    assert alerts[0].zone_id == 12


@pytest.mark.asyncio
async def test_alert_deduplication(alert_service):
    # User in Zone 10
    user = ActiveUser(user_id=5, lat=40.7128, lon=-74.0060)
    
    # First run should generate an alert
    alerts1 = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[10],
        approaching_zones=[],
        route_changes=[],
        active_users=[user]
    )
    assert len(alerts1) == 1
    
    # Second run immediately after should NOT generate an alert (spam check)
    alerts2 = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[10],
        approaching_zones=[],
        route_changes=[],
        active_users=[user]
    )
    assert len(alerts2) == 0


@pytest.mark.asyncio
async def test_alert_expiry(alert_service, db_session):
    # User in Zone 10
    user = ActiveUser(user_id=6, lat=40.7128, lon=-74.0060)
    
    # Issue first alert
    alerts1 = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[10],
        approaching_zones=[],
        route_changes=[],
        active_users=[user]
    )
    assert len(alerts1) == 1
    
    # Manually backdate the alert to bypass cooldown and simulate expiry
    # Cooldown for critical is 5 mins, expiry is 15 mins.
    # We backdate created_at by 20 minutes, and expires_at to 5 minutes ago.
    past_time = datetime.utcnow() - timedelta(minutes=20)
    alerts1[0].created_at = past_time
    alerts1[0].expires_at = past_time + timedelta(minutes=15)
    await db_session.commit()
    
    # Run again, it should issue a NEW alert since the previous one expired
    alerts2 = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[10],
        approaching_zones=[],
        route_changes=[],
        active_users=[user]
    )
    assert len(alerts2) == 1
    assert alerts2[0].id != alerts1[0].id


@pytest.mark.asyncio
async def test_deterministic_targeting(alert_service):
    # Multiple users, only 1 in danger, 1 approaching, 1 far away
    u_danger = ActiveUser(user_id=10, lat=40.7128, lon=-74.0060) # Zone 10
    u_approach = ActiveUser(user_id=11, lat=40.7138, lon=-74.0060) # Approaching Zone 10
    u_safe = ActiveUser(user_id=12, lat=41.0, lon=-75.0) # Far away
    
    alerts = await alert_service.generate_targeted_alerts(
        event_id=100,
        critical_zones=[10],
        approaching_zones=[10],
        route_changes=[],
        active_users=[u_danger, u_approach, u_safe]
    )
    
    assert len(alerts) == 2
    
    # Ensure they map correctly
    alert_danger = next(a for a in alerts if a.user_id == 10)
    assert alert_danger.alert_type == AlertType.CRITICAL_DANGER
    
    alert_approach = next(a for a in alerts if a.user_id == 11)
    assert alert_approach.alert_type == AlertType.HIGH_RISK_WARNING
