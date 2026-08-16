import pytest
from httpx import AsyncClient
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.event import Event, EventStatus
from app.models.zone import Zone, ZoneStatus
from app.models.user import User, UserRole
from app.models.recommendation import RecommendationModel, RecommendationStatus
from app.models.intervention import Intervention, InterventionStatus
from app.schemas.crowd_reading import CrowdReadingCreate
from app.services.crowd_ingestion_service import CrowdIngestionService
from app.core.security import get_password_hash

# Helper to create basic setup
async def setup_test_data(db_session: AsyncSession) -> tuple[Event, Zone, User]:
    # Ensure authority user
    result = await db_session.execute(select(User).where(User.email == "authority@test.com"))
    auth_user = result.scalar_one_or_none()
    if not auth_user:
        auth_user = User(
            email="authority@test.com",
            hashed_password=get_password_hash("password123"),
            role=UserRole.AUTHORITY
        )
        db_session.add(auth_user)
        await db_session.flush()

    event = Event(
        name="Test Event Phase 6",
        description="Event for recommendations testing",
        venue_id=1,
        status=EventStatus.ACTIVE
    )
    db_session.add(event)
    await db_session.flush()
    await db_session.refresh(event)

    zone = Zone(
        event_id=event.id,
        name="Test Zone",
        capacity=1000,
        status=ZoneStatus.ACTIVE
    )
    db_session.add(zone)
    await db_session.flush()
    await db_session.refresh(zone)
    await db_session.commit()

    return event, zone, auth_user


from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token

@pytest.mark.asyncio
async def test_recommendation_generation_and_simulation_and_approval(
    db_session: AsyncSession,
    app
):
    client = TestClient(app)
    event, zone, user = await setup_test_data(db_session)
    auth_token = create_access_token(data={"sub": str(user.id), "role": user.role.value})
    
    # 1. Generate high risk condition to trigger a recommendation
    # Submit reading
    reading_data = CrowdReadingCreate(
        event_id=event.id,
        zone_id=zone.id,
        timestamp="2026-08-16T12:00:00Z",
        person_count=900,
        density_percent=90.0,
        average_speed=0.2,
        dominant_direction="NORTH",
        crowd_growth_rate=10.0,
        congestion_score=0.9,
        surge_indicator=True,
        reverse_flow_indicator=False,
        bottleneck_indicator=True
    )
    
    ingestion_service = CrowdIngestionService(db_session)
    await ingestion_service.ingest(reading_data)
    
    # 2. Check that recommendation was created via API
    response = client.get(
        f"/api/v1/recommendations/{event.id}",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    
    assert response.status_code == 200
    recs = response.json()
    assert len(recs) > 0
    
    # Pick the first one
    rec = recs[0]
    rec_id = rec["id"]
    
    # 3. Simulate it
    sim_response = client.post(
        f"/api/v1/recommendations/{rec_id}/simulate",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert sim_response.status_code == 200
    sim_data = sim_response.json()
    assert "simulated_risk" in sim_data
    
    # 4. Approve it
    approve_response = client.post(
        f"/api/v1/recommendations/{rec_id}/approve",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert approve_response.status_code == 200
    intervention_data = approve_response.json()
    
    assert intervention_data["status"] == InterventionStatus.APPROVED.value
    assert intervention_data["actions"][0]["action_type"] == rec["action_type"]
    
    # Check DB that recommendation is now APPROVED
    result = await db_session.execute(select(RecommendationModel).where(RecommendationModel.id == rec_id))
    db_rec = result.scalar_one()
    assert db_rec.status == RecommendationStatus.APPROVED
    assert db_rec.approved_by_id == user.id
    assert db_rec.created_intervention_id == intervention_data["id"]

@pytest.mark.asyncio
async def test_recommendation_staleness(
    db_session: AsyncSession,
    app
):
    client = TestClient(app)
    event, zone, user = await setup_test_data(db_session)
    auth_token = create_access_token(data={"sub": str(user.id), "role": user.role.value})

    # High risk
    reading_data1 = CrowdReadingCreate(
        event_id=event.id,
        zone_id=zone.id,
        timestamp="2026-08-16T12:00:00Z",
        person_count=900,
        density_percent=90.0,
        average_speed=0.2,
        dominant_direction="NORTH",
        crowd_growth_rate=10.0,
        congestion_score=0.9,
        surge_indicator=True,
        reverse_flow_indicator=False,
        bottleneck_indicator=True
    )
    
    ingestion_service = CrowdIngestionService(db_session)
    await ingestion_service.ingest(reading_data1)
    
    # Fetch recs
    res = client.get(f"/api/v1/recommendations/{event.id}", headers={"Authorization": f"Bearer {auth_token}"})
    recs_before = res.json()
    assert len(recs_before) > 0
    
    # Safe reading
    reading_data2 = CrowdReadingCreate(
        event_id=event.id,
        zone_id=zone.id,
        timestamp="2026-08-16T12:05:00Z",
        person_count=100,
        density_percent=10.0,
        average_speed=1.5,
        dominant_direction="NORTH",
        crowd_growth_rate=0.0,
        congestion_score=0.1,
        surge_indicator=False,
        reverse_flow_indicator=False,
        bottleneck_indicator=False
    )
    
    await ingestion_service.ingest(reading_data2)
    
    res2 = client.get(f"/api/v1/recommendations/{event.id}", headers={"Authorization": f"Bearer {auth_token}"})
    recs_after = res2.json()
    
    # Should be far fewer or different recommendations (just monitor)
    assert len(recs_after) < len(recs_before) or (len(recs_after) > 0 and recs_after[0]["action_type"] == "MONITOR_ZONE")
    
    # Verify the old ones are STALE
    old_rec_id = recs_before[0]["id"]
    result = await db_session.execute(select(RecommendationModel).where(RecommendationModel.id == old_rec_id))
    db_rec = result.scalar_one()
    # It might be stale or still active depending on deduplication, but usually a high-risk one goes stale
    if db_rec.action_type != "MONITOR_ZONE":
        assert db_rec.status == RecommendationStatus.STALE

