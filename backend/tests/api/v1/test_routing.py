import pytest
from httpx import AsyncClient, ASGITransport

@pytest.mark.asyncio
async def test_full_routing_api(app, db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create Event
        res_evt = await client.post("/api/v1/events/", json={
            "name": "Routing Test Event",
            "description": "Integration test",
            "status": "ACTIVE"
        })
        assert res_evt.status_code == 201
        event_id = res_evt.json()["id"]

        # 2. Create Zones (We need manual DB manipulation for ZoneConnections and is_exit for now, 
        # but let's just create zones via API first)
        z1_res = await client.post("/api/v1/zones/", json={"event_id": event_id, "name": "Zone 1", "capacity": 1000, "status": "ACTIVE"})
        z2_res = await client.post("/api/v1/zones/", json={"event_id": event_id, "name": "Zone 2", "capacity": 1000, "status": "ACTIVE"})
        z3_res = await client.post("/api/v1/zones/", json={"event_id": event_id, "name": "Exit Zone", "capacity": 1000, "status": "ACTIVE"})
        
        z1_id = z1_res.json()["id"]
        z2_id = z2_res.json()["id"]
        z3_id = z3_res.json()["id"]

        # Add ZoneConnection directly to db_session since there's no CRUD API for it yet
        from app.models.zone_connection import ZoneConnection
        from app.models.zone import Zone
        from sqlalchemy.future import select

        # Mark z3 as exit
        stmt = select(Zone).where(Zone.id == z3_id)
        res = await db_session.execute(stmt)
        z3 = res.scalars().first()
        z3.is_exit = True
        
        c1 = ZoneConnection(source_zone_id=z1_id, dest_zone_id=z2_id, distance=10.0, capacity=500, is_bidirectional=True)
        c2 = ZoneConnection(source_zone_id=z2_id, dest_zone_id=z3_id, distance=15.0, capacity=500, is_bidirectional=True)
        db_session.add_all([c1, c2])
        await db_session.commit()

        # 3. Test safe route
        payload = {
            "event_id": event_id,
            "start_zone_id": z1_id,
            "destination_zone_id": z3_id
        }
        response = await client.post("/api/v1/routing/safe-route", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["is_available"] is True
        assert res_data["path"] == [str(z1_id), str(z2_id), str(z3_id)]
        assert res_data["total_distance"] == 25.0

        # 4. Test safest exit
        response = await client.get(f"/api/v1/routing/safest-exit/{event_id}/{z1_id}")
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["is_available"] is True
        assert res_data["destination"] == str(z3_id)
        assert res_data["path"] == [str(z1_id), str(z2_id), str(z3_id)]
