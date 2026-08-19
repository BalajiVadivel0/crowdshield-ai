import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.intervention import InterventionStatus
from app.models.user import UserRole

@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def intervention_payload():
    return {
        "event_id": 1,
        "zone_id": 10,
        "before_risk_score": 85.0,
        "affected_zones": [10, 11],
        "actions": [
            {
                "action_type": "RESTRICT_ENTRY",
                "description": "Close gate A"
            }
        ]
    }


def test_create_intervention(client: TestClient, intervention_payload):
    response = client.post("/api/v1/interventions/", json=intervention_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["status"] == InterventionStatus.PROPOSED.value
    assert data["before_risk_score"] == 85.0
    assert len(data["actions"]) == 1


def test_get_interventions(client: TestClient, intervention_payload):
    # Create one first
    client.post("/api/v1/interventions/", json=intervention_payload)
    
    response = client.get("/api/v1/interventions/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    
    # Filter by event
    response_filtered = client.get("/api/v1/interventions/?event_id=1")
    assert response_filtered.status_code == 200
    assert len(response_filtered.json()) >= 1


def test_full_lifecycle_api(client: TestClient, intervention_payload):
    # 1. Create
    resp = client.post("/api/v1/interventions/", json=intervention_payload)
    inv_id = resp.json()["id"]
    
    # 2. Simulate
    resp = client.post(f"/api/v1/interventions/{inv_id}/simulate")
    assert resp.status_code == 200
    assert resp.json()["status"] == InterventionStatus.SIMULATING.value
    
    # 3. Request Approval
    resp = client.post(f"/api/v1/interventions/{inv_id}/request_approval")
    assert resp.status_code == 200
    assert resp.json()["status"] == InterventionStatus.PENDING_APPROVAL.value
    
    # 4. Approve
    app_payload = {
        "scenario": "SIM_1",
        "expected_effect": "Low risk",
        "decision_reason": "Approved by protocol"
    }
    resp = client.post(f"/api/v1/interventions/{inv_id}/approve", json=app_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == InterventionStatus.APPROVED.value
    
    # 5. Activate
    resp = client.post(f"/api/v1/interventions/{inv_id}/activate")
    assert resp.status_code == 200
    assert resp.json()["status"] == InterventionStatus.ACTIVATED.value
    
    # 6. Complete
    comp_payload = {
        "after_risk_score": 30.0
    }
    resp = client.post(f"/api/v1/interventions/{inv_id}/complete", json=comp_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == InterventionStatus.COMPLETED.value
    assert data["after_risk_score"] == 30.0
    assert data["risk_reduction"] == 55.0


def test_invalid_transition_api(client: TestClient, intervention_payload):
    # Create
    resp = client.post("/api/v1/interventions/", json=intervention_payload)
    inv_id = resp.json()["id"]
    
    # Try to approve without PENDING_APPROVAL
    app_payload = {
        "decision_reason": "skip steps"
    }
    resp = client.post(f"/api/v1/interventions/{inv_id}/approve", json=app_payload)
    
    assert resp.status_code == 409  # Conflict


def test_not_found_handling(client: TestClient):
    resp = client.get("/api/v1/interventions/999999")
    assert resp.status_code == 404
