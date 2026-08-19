import pytest
from fastapi.testclient import TestClient
from app.models.user import User, UserRole
from app.api.dependencies import get_current_user

def test_audit_flow(app):
    client = TestClient(app)

    # 1. Create Intervention (PROPOSED)
    create_payload = {
        "event_id": 1,
        "zone_id": 10,
        "before_risk_score": 85.0,
        "affected_zones": [10],
        "actions": [
            {"action_type": "RESTRICT_ENTRY", "description": "Stop new entries"}
        ]
    }
    resp = client.post("/api/v1/interventions/", json=create_payload)
    assert resp.status_code == 201
    intervention_id = resp.json()["id"]

    # Check Audit Log for CREATE
    audit_resp = client.get(f"/api/v1/interventions/{intervention_id}/audit")
    assert audit_resp.status_code == 200
    audits = audit_resp.json()
    assert len(audits) == 1
    assert audits[0]["action"] == "CREATE"
    assert audits[0]["new_state"] == "PROPOSED"
    assert audits[0]["metadata_"] is not None
    assert audits[0]["metadata_"]["before_risk_score"] == 85.0

    # 2. Simulate (SIMULATING)
    sim_resp = client.post(f"/api/v1/interventions/{intervention_id}/simulate")
    assert sim_resp.status_code == 200

    # 3. Request Approval (PENDING_APPROVAL)
    req_resp = client.post(f"/api/v1/interventions/{intervention_id}/request_approval")
    assert req_resp.status_code == 200

    # 4. Approve (APPROVED)
    approve_payload = {
        "scenario": "Scenario A",
        "expected_effect": "Low risk",
        "decision_reason": "Looks good"
    }
    app_resp = client.post(f"/api/v1/interventions/{intervention_id}/approve", json=approve_payload)
    assert app_resp.status_code == 200

    # Check Audit Log for APPROVE
    audit_resp = client.get(f"/api/v1/interventions/{intervention_id}/audit")
    audits = audit_resp.json()
    # Expect 4 audits: CREATE, SIMULATE, REQUEST_APPROVAL, APPROVE
    assert len(audits) == 4
    approve_audit = audits[0] # Order is descending by timestamp
    assert approve_audit["action"] == "APPROVE"
    assert approve_audit["previous_state"] == "PENDING_APPROVAL"
    assert approve_audit["new_state"] == "APPROVED"
    assert approve_audit["reason"] == "Looks good"
    assert approve_audit["metadata_"]["scenario"] == "Scenario A"

    # 5. Invalid transition: Try to reject an APPROVED intervention
    rej_payload = {"decision_reason": "Changed my mind"}
    rej_resp = client.post(f"/api/v1/interventions/{intervention_id}/reject", json=rej_payload)
    assert rej_resp.status_code == 409 # Conflict

    # Verify no audit was created for the failed transition
    audit_resp2 = client.get(f"/api/v1/interventions/{intervention_id}/audit")
    assert len(audit_resp2.json()) == 4

    # 6. Activate (ACTIVATED)
    act_resp = client.post(f"/api/v1/interventions/{intervention_id}/activate")
    assert act_resp.status_code == 200

    # 7. Complete (COMPLETED)
    comp_payload = {"after_risk_score": 40.0}
    comp_resp = client.post(f"/api/v1/interventions/{intervention_id}/complete", json=comp_payload)
    assert comp_resp.status_code == 200

    # Check Audit Log for COMPLETE
    audit_resp = client.get(f"/api/v1/interventions/{intervention_id}/audit")
    audits = audit_resp.json()
    complete_audit = audits[0]
    assert complete_audit["action"] == "COMPLETE"
    assert complete_audit["metadata_"]["after_risk_score"] == 40.0

@pytest.mark.asyncio
async def test_unauthorized_access(app):
    # Override current user to CITIZEN
    async def override_get_citizen():
        return User(
            id=2,
            email="citizen@example.com",
            hashed_password="mock",
            role=UserRole.CITIZEN,
            assigned_event_id=None,
            assigned_zone_id=None
        )
    
    app.dependency_overrides[get_current_user] = override_get_citizen
    client = TestClient(app)

    # Trying to access audit of intervention 1
    resp = client.get("/api/v1/interventions/1/audit")
    assert resp.status_code == 403 # require_authority raises 403

    app.dependency_overrides.pop(get_current_user, None)

def test_reject_creates_audit(app):
    client = TestClient(app)

    create_payload = {
        "event_id": 1,
        "before_risk_score": 90.0,
        "actions": [{"action_type": "EVACUATE", "description": "Evac"}]
    }
    resp = client.post("/api/v1/interventions/", json=create_payload)
    intv_id = resp.json()["id"]

    client.post(f"/api/v1/interventions/{intv_id}/request_approval")

    rej_payload = {"decision_reason": "Too risky"}
    rej_resp = client.post(f"/api/v1/interventions/{intv_id}/reject", json=rej_payload)
    assert rej_resp.status_code == 200

    audit_resp = client.get(f"/api/v1/interventions/{intv_id}/audit")
    audits = audit_resp.json()
    
    reject_audit = audits[0]
    assert reject_audit["action"] == "REJECT"
    assert reject_audit["previous_state"] == "PENDING_APPROVAL"
    assert reject_audit["new_state"] == "REJECTED"
    assert reject_audit["reason"] == "Too risky"
