import pytest
from httpx import AsyncClient, ASGITransport
from app.models.user import User, UserRole
from app.api.dependencies import get_current_user

@pytest.mark.asyncio
async def test_simulation_api(app, db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create Event
        res_evt = await client.post("/api/v1/events/", json={
            "name": "Sim Test Event",
            "description": "Integration test",
            "status": "ACTIVE"
        })
        assert res_evt.status_code == 201
        event_id = res_evt.json()["id"]

        # 2. Create Zone
        z1_res = await client.post("/api/v1/zones/", json={"event_id": event_id, "name": "Zone 1", "capacity": 1000, "status": "ACTIVE"})
        z1_id = z1_res.json()["id"]

        payload = {
            "event_id": event_id,
            "zone_id": z1_id,
            "scenario": "SURGE",
            "duration_minutes": 5,
            "seed": 42
        }

        # conftest mocks get_current_user as AUTHORITY
        response = await client.post("/api/v1/simulation/run", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["scenario"] == "SURGE"
        assert len(res_data["readings"]) == 5

        # Now test CITIZEN rejection
        async def override_get_citizen():
            return User(id=2, email="citizen@test.com", hashed_password="mock", role=UserRole.CITIZEN)
            
        app.dependency_overrides[get_current_user] = override_get_citizen
        
        response = await client.post("/api/v1/simulation/run", json=payload)
        assert response.status_code == 403
        
        # Reset override
        app.dependency_overrides.pop(get_current_user, None)
