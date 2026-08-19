import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.incident import IncidentStatus, IncidentSeverity, IncidentType
from app.schemas.incident import IncidentReportCreate

@pytest.mark.asyncio
async def test_phase5h_intelligence_integration(app, db_session):
    """
    Test that active incidents properly surface in the CrowdIntelligence snapshot
    without modifying the underlying RiskEngine math.
    """
    client = TestClient(app)

    # 1. Create Event
    event_data = {
        "name": "Phase 5H Test Event",
        "description": "Testing incident intelligence signals",
        "status": "ACTIVE"
    }
    res_evt = client.post("/api/v1/events/", json=event_data)
    assert res_evt.status_code == 201
    event_id = res_evt.json()["id"]

    # 2. Create Zone
    zone_data = {
        "event_id": event_id,
        "name": "Test Zone",
        "capacity": 500,
        "status": "ACTIVE"
    }
    res_zone = client.post("/api/v1/zones/", json=zone_data)
    zone_id = res_zone.json()["id"]

    # 3. Create Users
    cit_user = User(email="cit1@ex.com", hashed_password="pw", role=UserRole.CITIZEN, assigned_zone_id=zone_id)
    auth_user = User(email="auth1@ex.com", hashed_password="pw", role=UserRole.AUTHORITY)
    db_session.add_all([cit_user, auth_user])
    await db_session.commit()
    
    cit_token = create_access_token(data={"sub": str(cit_user.id), "role": UserRole.CITIZEN.value})
    auth_token = create_access_token(data={"sub": str(auth_user.id), "role": UserRole.AUTHORITY.value})
    headers_cit = {"Authorization": f"Bearer {cit_token}"}
    headers_auth = {"Authorization": f"Bearer {auth_token}"}

    # 4. Ingest an initial crowd reading (Baseline Risk)
    reading_data = {
        "event_id": event_id,
        "zone_id": zone_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "person_count": 100,
        "density_percent": 20.0,
        "average_speed": 1.2,
        "dominant_direction": "FLOWING",
        "crowd_growth_rate": 0.0,
        "congestion_score": 10.0,
        "surge_indicator": False,
        "reverse_flow_indicator": False,
        "bottleneck_indicator": False
    }
    res_ingest = client.post("/api/v1/crowd-readings/", json=reading_data)
    assert res_ingest.status_code == 201
    
    with client.websocket_connect(f"/api/v1/ws/auth-client?token={auth_token}") as ws:
        
        # 6. Report an active incident
        inc_data = {
            "event_id": event_id,
            "user_id": cit_user.id,
            "zone_id": zone_id,
            "incident_type": "BLOCKED_ROUTE",
            "description": "The exit is totally blocked.",
            "severity": "CRITICAL"
        }
        res_inc = client.post("/api/v1/incidents/", json=inc_data, headers=headers_cit)
        assert res_inc.status_code == 201
        inc_id = res_inc.json()["id"]
        
        # Ingest another reading to trigger intelligence update
        reading_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        res_ingest2 = client.post("/api/v1/crowd-readings/", json=reading_data)
        assert res_ingest2.status_code == 201
        
        # We use the REST endpoint to get the full EventCrowdIntelligence object
        # which contains zone_summaries (the websocket payload AuthorityIntelligenceData omits this)
        res_intel = client.get(f"/api/v1/crowd-intelligence/{event_id}", headers=headers_auth)
        assert res_intel.status_code == 200
        intel = res_intel.json()
        
        # Check Event flags
        assert "INCIDENT_REPORTED" in intel["event_flags"]
        assert "BLOCKED_ROUTE_REPORTED" in intel["event_flags"]
        
        # Check Zone flags
        zone_summary = intel["zone_summaries"][0]
        assert zone_summary["zone_id"] == zone_id
        assert zone_summary["active_incidents"] == 1
        assert "BLOCKED_ROUTE" in zone_summary["incident_types"]
        assert zone_summary["highest_incident_severity"] == "CRITICAL"
        
        # Baseline Risk score must remain LOW despite the Critical incident
        assert zone_summary["current_level"] == "LOW"
        assert zone_summary["current_score"] < 35.0
        
        # 7. Resolve the incident
        res_update = client.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "RESOLVED"}, headers=headers_auth)
        assert res_update.status_code == 200
        
        # 8. Ingest another reading
        reading_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        res_ingest3 = client.post("/api/v1/crowd-readings/", json=reading_data)
        assert res_ingest3.status_code == 201
        
        res_intel_res = client.get(f"/api/v1/crowd-intelligence/{event_id}", headers=headers_auth)
        assert res_intel_res.status_code == 200
        intel_res = res_intel_res.json()
        
        assert "INCIDENT_REPORTED" not in intel_res["event_flags"]
        
        zone_summary_res = intel_res["zone_summaries"][0]
        assert zone_summary_res["active_incidents"] == 0
        assert len(zone_summary_res["incident_types"]) == 0
        assert zone_summary_res["highest_incident_severity"] is None
