import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_full_phase1_pipeline(app):
    # 1. Start test client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        
        # 2. Create Event
        event_data = {
            "name": "Phase 1 Test Event",
            "description": "Integration test",
            "status": "ACTIVE"
        }
        res_evt = await client.post("/api/v1/events/", json=event_data)
        assert res_evt.status_code == 201
        event_id = res_evt.json()["id"]

        # 3. Create Zone
        zone_data = {
            "event_id": event_id,
            "name": "Main Gate",
            "capacity": 1000,
            "status": "ACTIVE"
        }
        res_zone = await client.post("/api/v1/zones/", json=zone_data)
        assert res_zone.status_code == 201
        zone_id = res_zone.json()["id"]

        # 4. Ingest Crowd Reading
        reading_data = {
            "event_id": event_id,
            "zone_id": zone_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "person_count": 850,
            "density_percent": 85.0,
            "average_speed": 0.4,
            "dominant_direction": "CONFLICTED",
            "crowd_growth_rate": 15.0,
            "congestion_score": 75.0,
            "surge_indicator": True,
            "reverse_flow_indicator": True,
            "bottleneck_indicator": False
        }
        
        res_ingest = await client.post("/api/v1/crowd-readings/", json=reading_data)
        assert res_ingest.status_code == 201
        ingestion = res_ingest.json()
        
        # Verify persistence and RiskEngine execution
        assert "crowd_reading" in ingestion
        assert "risk_assessment" in ingestion
        assert "prediction" in ingestion
        assert "crowd_intelligence" in ingestion
        
        risk_score = ingestion["risk_assessment"]["score"]
        assert risk_score > 0
        
        # Prediction should indicate insufficient data initially (min 3)
        assert ingestion["prediction"]["confidence"] == 0.0
        
        # 5. Ingest two more to trigger PredictionEngine
        reading_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        reading_data["person_count"] = 900
        reading_data["density_percent"] = 90.0
        await client.post("/api/v1/crowd-readings/", json=reading_data)
        
        reading_data["timestamp"] = datetime.now(timezone.utc).isoformat()
        reading_data["person_count"] = 950
        reading_data["density_percent"] = 95.0
        res_ingest3 = await client.post("/api/v1/crowd-readings/", json=reading_data)
        
        ingestion3 = res_ingest3.json()
        
        # Prediction should now be active
        assert ingestion3["prediction"]["confidence"] > 0
        
        # 6. Retrieve Risk via GET endpoint
        res_risk = await client.get(f"/api/v1/risk/{event_id}/{zone_id}")
        assert res_risk.status_code == 200
        assert res_risk.json()["risk_score"] == ingestion3["risk_assessment"]["score"]
        
        # 7. Retrieve Crowd Intelligence via GET endpoint
        res_intel = await client.get(f"/api/v1/crowd-intelligence/{event_id}")
        assert res_intel.status_code == 200
        intel_data = res_intel.json()
        assert intel_data["overall_risk_score"] > 0
        assert intel_data["highest_risk_zone"] == zone_id
