import os
import sys
import asyncio
import httpx

API_BASE = "http://localhost:8000/api/v1"

async def run_e2e_validations():
    async with httpx.AsyncClient() as client:
        print("Starting E2E Validation Script...")

        # 1. Register Auth
        auth_data = {"email": "e2e_auth@example.com", "password": "password123", "role": "AUTHORITY"}
        res = await client.post(f"{API_BASE}/auth/register", json=auth_data)
        
        # We might already be registered, so let's just login
        res = await client.post(f"{API_BASE}/auth/login", data={"username": "e2e_auth@example.com", "password": "password123"})
        if res.status_code != 200:
            print("Failed to login Authority!")
            return
        auth_token = res.json()["access_token"]

        # 2. Register Citizen
        cit_data = {"email": "e2e_cit@example.com", "password": "password123", "role": "CITIZEN"}
        await client.post(f"{API_BASE}/auth/register", json=cit_data)
        
        res = await client.post(f"{API_BASE}/auth/login", data={"username": "e2e_cit@example.com", "password": "password123"})
        if res.status_code != 200:
            print("Failed to login Citizen!")
            return
        cit_token = res.json()["access_token"]

        print("Authentication Success!")

        # 3. Security Validation: Citizen trying to perform Authority Action
        res = await client.get(f"{API_BASE}/interventions/active", headers={"Authorization": f"Bearer {cit_token}"})
        if res.status_code == 403:
            print("SUCCESS: Citizen cannot access Authority Interventions endpoint.")
        else:
            print(f"FAILED: Citizen got status code {res.status_code}")

        # 4. Audit Trail Validation: Authority taking action
        # Let's get active recommendations
        res = await client.get(f"{API_BASE}/recommendations/active", headers={"Authorization": f"Bearer {auth_token}"})
        if res.status_code == 200:
            recs = res.json()
            if recs:
                rec_id = recs[0]["id"]
                action_data = {"recommendation_id": rec_id, "action": "APPROVE"}
                res_action = await client.post(f"{API_BASE}/interventions/", json=action_data, headers={"Authorization": f"Bearer {auth_token}"})
                print(f"Intervention Action Response: {res_action.status_code}")

                # Check Audit logs
                res_audit = await client.get(f"{API_BASE}/interventions/audit/logs", headers={"Authorization": f"Bearer {auth_token}"})
                logs = res_audit.json()
                if logs:
                    print("SUCCESS: Audit Logs found!")
                    print(f"Latest Log: ACTION={logs[0]['action']} BY={logs[0]['user_id']}")
                else:
                    print("FAILED: No Audit logs found after action.")
            else:
                print("No active recommendations to test intervention, but access works.")
        
        print("E2E VALIDATION COMPLETE!")

if __name__ == "__main__":
    asyncio.run(run_e2e_validations())
