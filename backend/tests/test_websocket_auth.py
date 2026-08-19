import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import User, UserRole
from app.api.dependencies import get_current_user
import asyncio
from fastapi.testclient import TestClient
from app.core.security import create_access_token

@pytest.fixture
def clean_app(app):
    # Remove the mock get_current_user dependency specifically for auth tests
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]
    yield app

@pytest.mark.asyncio
async def test_websocket_auth_success(clean_app, db_session):
    client = TestClient(clean_app)
    
    user = User(email="user1@example.com", hashed_password="pw", role=UserRole.CITIZEN, assigned_zone_id=1)
    db_session.add(user)
    await db_session.commit()
    
    # Generate a valid token
    token = create_access_token(
        data={"sub": str(user.id), "role": UserRole.CITIZEN.value}
    )
    
    with client.websocket_connect(f"/api/v1/ws/client1?token={token}") as websocket:
        # If it connects without raising an exception, auth succeeded
        # We can try to send a ping or just let the connection close gracefully
        assert websocket is not None

@pytest.mark.asyncio
async def test_websocket_auth_failure_invalid_token(clean_app, db_session):
    client = TestClient(clean_app)
    
    # Missing token -> 422 Unprocessable Entity because of Query(...)
    with pytest.raises(Exception) as excinfo:
        with client.websocket_connect("/api/v1/ws/client2") as websocket:
            pass
            
    # Invalid token -> 1008
    with pytest.raises(Exception) as excinfo:
        with client.websocket_connect("/api/v1/ws/client2?token=invalidtoken") as websocket:
            pass

@pytest.mark.asyncio
async def test_websocket_auth_failure_invalid_role(clean_app, db_session):
    client = TestClient(clean_app)
    
    user = User(email="user2@example.com", hashed_password="pw", role=UserRole.CITIZEN, assigned_zone_id=1)
    db_session.add(user)
    await db_session.commit()
    
    # Token with invalid role
    token = create_access_token(
        data={"sub": str(user.id), "role": "HACKER"}
    )
    
    # Should be rejected with 1008
    with pytest.raises(Exception) as excinfo:
        with client.websocket_connect(f"/api/v1/ws/client3?token={token}") as websocket:
            pass
