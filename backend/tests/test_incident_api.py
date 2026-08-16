import pytest
from fastapi.testclient import TestClient
from app.models.incident import IncidentStatus, IncidentType, IncidentSeverity


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def valid_payload():
    return {
        "event_id": 1,
        "user_id": 1,
        "zone_id": 10,
        "incident_type": IncidentType.CROWD_CONGESTION.value,
        "description": "Crowd getting too dense here",
        "severity": IncidentSeverity.MEDIUM.value
    }


def test_create_incident_api(client: TestClient, valid_payload):
    response = client.post("/api/v1/incidents/", json=valid_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["status"] == IncidentStatus.OPEN.value
    assert data["incident_type"] == valid_payload["incident_type"]


def test_invalid_incident_api(client: TestClient):
    # Missing location (no zone, no lat/lon)
    invalid_payload = {
        "event_id": 1,
        "user_id": 1,
        "incident_type": IncidentType.CROWD_CONGESTION.value,
        "description": "Somewhere",
        "severity": IncidentSeverity.MEDIUM.value
    }
    response = client.post("/api/v1/incidents/", json=invalid_payload)
    assert response.status_code == 422
    assert "Must provide either a zone_id or both latitude and longitude" in response.text


def test_get_and_list_incidents(client: TestClient, valid_payload):
    # Create
    resp = client.post("/api/v1/incidents/", json=valid_payload)
    incident_id = resp.json()["id"]
    
    # Get by ID
    get_resp = client.get(f"/api/v1/incidents/{incident_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == incident_id
    
    # List
    list_resp = client.get("/api/v1/incidents/")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1


def test_update_status_api(client: TestClient, valid_payload):
    # Create
    resp = client.post("/api/v1/incidents/", json=valid_payload)
    incident_id = resp.json()["id"]
    
    # Valid transition to INVESTIGATING
    patch_resp = client.patch(
        f"/api/v1/incidents/{incident_id}/status",
        json={"status": IncidentStatus.INVESTIGATING.value}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == IncidentStatus.INVESTIGATING.value
    
    # Invalid transition back to OPEN
    bad_patch = client.patch(
        f"/api/v1/incidents/{incident_id}/status",
        json={"status": IncidentStatus.OPEN.value}
    )
    assert bad_patch.status_code == 409
    assert "Invalid transition" in bad_patch.text
