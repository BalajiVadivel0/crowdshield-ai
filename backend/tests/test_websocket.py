import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token
from app.models.user import UserRole

client = TestClient(app)

def test_websocket_connection_authority():
    token = create_access_token(data={"sub": "1", "role": UserRole.AUTHORITY.value})
    with client.websocket_connect(f"/api/v1/ws/auth1?token={token}") as websocket:
        pass

def test_websocket_connection_citizen():
    token = create_access_token(data={"sub": "2", "role": UserRole.CITIZEN.value})
    with client.websocket_connect(f"/api/v1/ws/cit1?token={token}&zone_id=1") as websocket:
        pass

def test_websocket_rejects_without_client_id():
    response = client.get("/api/v1/ws/")
    assert response.status_code == 404  # Not found, requires client_id
