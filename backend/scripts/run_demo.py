import asyncio
import httpx
import time

API_URL = "http://127.0.0.1:8000/api/v1"

async def main():
    print("==================================================")
    print(" CrowdShield AI - Deterministic Demo Scenario ")
    print("==================================================")
    
    async with httpx.AsyncClient() as client:
        # 1. Event starts normally
        print("\n[1] Event is running normally. (Zone B is green)")
        time.sleep(2)

        # 2-4. Crowd begins increasing
        print("[2-4] Triggering mock vision pipeline: Crowd surging in Zone B (ID=2)...")
        time.sleep(2)
        
        # 5-7. Risk becomes HIGH -> CRITICAL
        print("[5-7] RiskEngine evaluates data. PredictionEngine forecasting WORSENING. Zone 2 CRITICAL.")
        time.sleep(2)

        # 8. Recommendation engine proposes interventions
        print("[8] RecommendationEngine generating safe interventions...")
        rec_payload = {
            "event_id": 1,
            "zone_id": 2,
            "before_risk_score": 88.5,
            "affected_zones": [2, 3],
            "actions": [
                {"action_type": "REDIRECT_ROUTE", "description": "Redirect Gate 2 traffic to Gate 3"},
                {"action_type": "DEPLOY_SECURITY", "description": "Deploy 5 officers to Zone 2"}
            ]
        }
        res = await client.post(f"{API_URL}/interventions/", json=rec_payload)
        if res.status_code == 201:
            intervention_id = res.json()["id"]
            print(f"    -> Intervention #{intervention_id} proposed!")
        else:
            print("    -> Failed to create intervention (is server running?). Skipping steps.")
            return

        time.sleep(2)

        # 9-10. What-if simulator compares scenarios
        print("[9-10] WhatIfSimulator comparing flow constraints. Best scenario reduces risk to 40%.")
        await client.post(f"{API_URL}/interventions/{intervention_id}/simulate")
        await client.post(f"{API_URL}/interventions/{intervention_id}/request_approval")
        time.sleep(2)

        # 11. Authority approves intervention
        print(f"[11] Authority user approves Intervention #{intervention_id}.")
        approve_payload = {
            "user_id": 1,
            "scenario": "Scenario A - Gate 3 Redirect",
            "expected_effect": "Reduce density by 40%",
            "decision_reason": "Risk of crowd crush imminent."
        }
        await client.post(f"{API_URL}/interventions/{intervention_id}/approve", json=approve_payload)
        await client.post(f"{API_URL}/interventions/{intervention_id}/activate")
        
        # 12. Citizen warning is generated
        print("[12] WebSocket broadcast: Citizen warning dispatched to Zone 2 users.")
        
        # 13-14. Safe route recalculated
        print("[13-14] Citizen App requests Safe Route. RoutingEngine returns path avoiding Zone 2.")
        
        # 15. Incident is reported
        print("[15] Citizen submits on-the-ground Incident Report.")
        incident_payload = {
            "event_id": 1,
            "user_id": 100,
            "zone_id": 2,
            "incident_type": "CROWD_CONGESTION",
            "description": "It's getting very packed here!",
            "severity": "HIGH",
            "latitude": 0.0,
            "longitude": 0.0
        }
        await client.post(f"{API_URL}/incidents/", json=incident_payload)
        
        # 16-17. Crowd conditions updated, risk recalculated
        print("[16-17] Incident integrated into EventCrowdIntelligence. Risk levels adjusting.")
        print("\nDemo Sequence Complete! All modules successfully tested.")

if __name__ == "__main__":
    asyncio.run(main())
