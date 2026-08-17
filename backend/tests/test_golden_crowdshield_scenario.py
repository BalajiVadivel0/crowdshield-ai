import pytest
from httpx import AsyncClient
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.event import Event, EventStatus
from app.models.zone import Zone, ZoneStatus
from app.models.zone_connection import ZoneConnection
from app.models.user import User, UserRole
from app.models.recommendation import RecommendationModel, RecommendationStatus
from app.models.intervention import Intervention, InterventionStatus
from app.schemas.crowd_reading import CrowdReadingCreate
from app.services.crowd_ingestion_service import CrowdIngestionService
from app.core.security import get_password_hash

from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token


async def setup_golden_venue(db_session: AsyncSession) -> tuple[Event, User]:
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
        name="Golden Scenario Event",
        description="Event for Golden Scenario Testing",
        venue_id=1,
        status=EventStatus.ACTIVE
    )
    db_session.add(event)
    await db_session.flush()
    await db_session.refresh(event)

    # Zone A (Source)
    zone_a = Zone(id=10, event_id=event.id, name="Zone A", capacity=1000, status=ZoneStatus.ACTIVE)
    # Zone B (Downstream)
    zone_b = Zone(id=11, event_id=event.id, name="Zone B", capacity=1000, status=ZoneStatus.ACTIVE)
    # Zone C (Isolated)
    zone_c = Zone(id=12, event_id=event.id, name="Zone C", capacity=1000, status=ZoneStatus.ACTIVE)
    # Exit D (Alternate Exit)
    exit_d = Zone(id=13, event_id=event.id, name="Exit D", capacity=2000, status=ZoneStatus.ACTIVE, is_exit=True)
    # Gate E (Incoming Gate)
    gate_e = Zone(id=14, event_id=event.id, name="Gate E", capacity=500, status=ZoneStatus.ACTIVE)
    
    db_session.add_all([zone_a, zone_b, zone_c, exit_d, gate_e])
    await db_session.flush()

    # Gate E -> Zone A (Entry)
    conn_ea = ZoneConnection(source_zone_id=14, dest_zone_id=10, distance=5.0, capacity=300, is_bidirectional=False, status="OPEN")
    # Zone A -> Zone B
    conn_ab = ZoneConnection(source_zone_id=10, dest_zone_id=11, distance=10.0, capacity=500, is_bidirectional=False, status="OPEN")
    # Zone A -> Exit D
    conn_ad = ZoneConnection(source_zone_id=10, dest_zone_id=13, distance=15.0, capacity=1000, is_bidirectional=False, status="RESTRICTED")

    db_session.add_all([conn_ea, conn_ab, conn_ad])
    await db_session.commit()

    return event, auth_user


@pytest.mark.asyncio
async def test_golden_crowdshield_scenario(db_session: AsyncSession, app):
    client = TestClient(app)
    event, auth_user = await setup_golden_venue(db_session)
    auth_token = create_access_token(data={"sub": str(auth_user.id), "role": auth_user.role.value})
    headers = {"Authorization": f"Bearer {auth_token}"}
    
    ingestion_service = CrowdIngestionService(db_session)

    # Zone A: INITIAL LOW DENSITY
    reading_a_0 = CrowdReadingCreate(
        event_id=event.id, zone_id=10, timestamp="2026-08-16T11:50:00Z",
        person_count=100, density_percent=10.0, average_speed=1.5, dominant_direction="NORTH",
        crowd_growth_rate=1.0, congestion_score=0.05, surge_indicator=False,
        reverse_flow_indicator=False, bottleneck_indicator=False
    )
    await ingestion_service.ingest(reading_a_0)

    # Zone A: MODERATE DENSITY
    reading_a_1 = CrowdReadingCreate(
        event_id=event.id, zone_id=10, timestamp="2026-08-16T11:55:00Z",
        person_count=400, density_percent=40.0, average_speed=1.0, dominant_direction="NORTH",
        crowd_growth_rate=5.0, congestion_score=0.2, surge_indicator=False,
        reverse_flow_indicator=False, bottleneck_indicator=False
    )
    await ingestion_service.ingest(reading_a_1)

    # Zone A: HIGH DENSITY (WORSENING)
    reading_a = CrowdReadingCreate(
        event_id=event.id, zone_id=10, timestamp="2026-08-16T12:00:00Z",
        person_count=950, density_percent=95.0, average_speed=0.1, dominant_direction="NORTH",
        crowd_growth_rate=25.0, congestion_score=0.95, surge_indicator=True,
        reverse_flow_indicator=False, bottleneck_indicator=True
    )
    # Zone B: MODERATE
    reading_b = CrowdReadingCreate(
        event_id=event.id, zone_id=11, timestamp="2026-08-16T12:00:00Z",
        person_count=200, density_percent=20.0, average_speed=1.0, dominant_direction="NORTH",
        crowd_growth_rate=0.0, congestion_score=0.1, surge_indicator=False,
        reverse_flow_indicator=False, bottleneck_indicator=False
    )
    # Zone C: NORMAL
    reading_c = CrowdReadingCreate(
        event_id=event.id, zone_id=12, timestamp="2026-08-16T12:00:00Z",
        person_count=50, density_percent=5.0, average_speed=1.2, dominant_direction="EAST",
        crowd_growth_rate=0.0, congestion_score=0.05, surge_indicator=False,
        reverse_flow_indicator=False, bottleneck_indicator=False
    )

    await ingestion_service.ingest(reading_a)
    await ingestion_service.ingest(reading_b)
    await ingestion_service.ingest(reading_c)

    # 2. RISK ASSESSMENT & 3. TEMPORAL PREDICTION & 4. NETWORK PROPAGATION
    response = client.get(f"/api/v1/crowd-intelligence/{event.id}", headers=headers)
    assert response.status_code == 200
    intel = response.json()
    
    print("\n--- Event Intelligence ---")
    print(f"Overall Risk Level: {intel['overall_risk_level']}")
    
    zone_summaries = {z['zone_id']: z for z in intel['zone_summaries']}
    
    # Assert Zone A
    assert zone_summaries[10]['current_level'] in ["HIGH", "CRITICAL"]
    assert zone_summaries[10]['trend'] == "WORSENING"
    
    # Assert Zone B has network impacts from Zone A
    assert len(zone_summaries[11]['network_impacts']) >= 1
    impact = zone_summaries[11]['network_impacts'][0]
    assert impact['source_zone_id'] == "10"
    assert impact['destination_zone_id'] == "11"
    
    # Assert Zone C has NO network impacts
    assert len(zone_summaries[12]['network_impacts']) == 0

    # 5. INTERVENTION GENERATION & 6. BASELINE SIMULATION & 7. INTERVENTION SIMULATION & 8. RANKING
    response = client.get(f"/api/v1/recommendations/{event.id}", headers=headers)
    assert response.status_code == 200
    recs = response.json()
    
    assert len(recs) > 0, "No recommendations were generated"
    
    print("\n--- Ranking Candidates ---")
    prev_score = -1.0
    simulated_count = 0
    for r in recs:
        # Simulate each candidate
        sim_response = client.post(f"/api/v1/recommendations/{r['id']}/simulate", headers=headers)
        assert sim_response.status_code == 200
        sim_data = sim_response.json()
        
        if r['action_type'] in ["OPEN_ALTERNATE_EXIT", "CLOSE_ENTRY_GATE", "RESTRICT_ENTRY", "ONE_WAY_FLOW"]:
            assert sim_data['simulated'] is True
            assert sim_data['baseline_peak_network_risk'] is not None
            simulated_count += 1
            print(f"Candidate: {r['action_type']} -> Score: {sim_data.get('scenario_score')}")
        else:
            assert sim_data['simulated'] is False
            print(f"Candidate (Not Simulatable): {r['action_type']}")
    
    assert simulated_count > 0, "No candidates were successfully simulated"
    
    # 9. HUMAN APPROVAL
    best_rec = recs[0]
    rec_id = best_rec['id']
    
    approve_response = client.post(
        f"/api/v1/recommendations/{rec_id}/approve",
        headers=headers
    )
    assert approve_response.status_code == 200
    
    # Verify Intervention State
    inv_response = client.get("/api/v1/interventions/", headers=headers, params={"event_id": event.id})
    assert inv_response.status_code == 200
    invs = inv_response.json()
    assert len(invs) > 0
    active_inv = invs[0]
    assert active_inv['status'] in ["PENDING_APPROVAL", "APPROVED", "ACTIVATED"]
    
    print(f"\n--- Approval Verified ---")
    print(f"Action: {best_rec['action_type']} -> State: {active_inv['status']}")
    
    # 10. POST-INTERVENTION MEASUREMENT
    # Inject improving reading for Zone A
    reading_a_post = CrowdReadingCreate(
        event_id=event.id, zone_id=10, timestamp="2026-08-16T12:15:00Z",
        person_count=500, density_percent=50.0, average_speed=0.8, dominant_direction="NORTH",
        crowd_growth_rate=-5.0, congestion_score=0.4, surge_indicator=False,
        reverse_flow_indicator=False, bottleneck_indicator=False
    )
    await ingestion_service.ingest(reading_a_post)
    
    post_response = client.get(f"/api/v1/crowd-intelligence/{event.id}", headers=headers)
    post_intel = post_response.json()
    post_zone_summaries = {z['zone_id']: z for z in post_intel['zone_summaries']}
    
    # Verify risk decreased
    assert post_zone_summaries[10]['current_score'] < zone_summaries[10]['current_score']
    print(f"\n--- Post-Intervention Metrics ---")
    print(f"Zone A Risk Before: {zone_summaries[10]['current_score']:.1f} -> After: {post_zone_summaries[10]['current_score']:.1f}")
    
    # 11. FAILURE / RESILIENCE CASE
    print("\n--- Failure Resilience ---")
    import unittest.mock as mock
    with mock.patch('app.ai.prediction_engine.propagation.NetworkPropagationEngine.forecast_network_risk', side_effect=Exception("Simulated network failure")):
        # Should gracefully handle failure and continue producing local intel
        reading_a_fail = CrowdReadingCreate(
            event_id=event.id, zone_id=10, timestamp="2026-08-16T12:20:00Z",
            person_count=900, density_percent=90.0, average_speed=0.2, dominant_direction="NORTH",
            crowd_growth_rate=15.0, congestion_score=0.9, surge_indicator=True,
            reverse_flow_indicator=False, bottleneck_indicator=True
        )
        try:
            await ingestion_service.ingest(reading_a_fail)
            fail_response = client.get(f"/api/v1/crowd-intelligence/{event.id}", headers=headers)
            assert fail_response.status_code == 200
            fail_intel = fail_response.json()
            fail_zone_summaries = {z['zone_id']: z for z in fail_intel['zone_summaries']}
            
            # Local intel still produced
            assert fail_zone_summaries[10]['current_level'] is not None
            # Network impact list is empty because propagation engine crashed
            assert len(fail_zone_summaries[11]['network_impacts']) == 0
            print("Propagation failure gracefully isolated. Local intelligence preserved.")
        except Exception as e:
            pytest.fail(f"Pipeline failed to isolate engine exception: {e}")

    print("\nGolden Scenario successfully validated end-to-end!")
