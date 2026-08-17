import pytest
from app.models.intervention import InterventionStatus
from app.schemas.intervention import (
    ApprovalRequest,
    CancelRequest,
    CompleteRequest,
    InterventionActionCreate,
    InterventionCreate,
    RejectRequest,
)
from app.services.intervention_service import InterventionService


@pytest.fixture
def intervention_service(db_session):
    return InterventionService(db_session)


@pytest.fixture
def base_intervention_data():
    return InterventionCreate(
        event_id=1,
        zone_id=10,
        before_risk_score=85.0,
        affected_zones=[10, 11],
        actions=[
            InterventionActionCreate(
                action_type="RESTRICT_ENTRY",
                description="Close gate A"
            )
        ]
    )


@pytest.mark.asyncio
async def test_create_intervention(intervention_service, base_intervention_data):
    intervention = await intervention_service.create_intervention(base_intervention_data)
    assert intervention.id is not None
    assert intervention.status == InterventionStatus.PROPOSED
    assert intervention.before_risk_score == 85.0
    assert len(intervention.actions) == 1
    assert intervention.actions[0].action_type == "RESTRICT_ENTRY"
    assert intervention.result is None


@pytest.mark.asyncio
async def test_full_lifecycle(intervention_service, base_intervention_data):
    # 1. Create (PROPOSED)
    intervention = await intervention_service.create_intervention(base_intervention_data)
    
    # 2. PROPOSED -> SIMULATING
    intervention = await intervention_service.set_simulating(intervention.id)
    assert intervention.status == InterventionStatus.SIMULATING
    
    # 3. SIMULATING -> PENDING_APPROVAL
    intervention = await intervention_service.set_pending_approval(intervention.id)
    assert intervention.status == InterventionStatus.PENDING_APPROVAL
    
    # 4. PENDING_APPROVAL -> APPROVED
    app_req = ApprovalRequest(
        user_id=42,
        scenario="SCENARIO_1",
        expected_effect="Risk drops to 40",
        decision_reason="Looks good"
    )
    intervention = await intervention_service.approve_intervention(intervention.id, app_req, actor_user_id=42)
    assert intervention.status == InterventionStatus.APPROVED
    assert intervention.result is not None
    assert intervention.result.approved_by_user_id == 42
    
    # 5. APPROVED -> ACTIVATED
    intervention = await intervention_service.activate_intervention(intervention.id, actor_user_id=42)
    assert intervention.status == InterventionStatus.ACTIVATED
    
    # 6. ACTIVATED -> COMPLETED
    comp_req = CompleteRequest(after_risk_score=40.0)
    intervention = await intervention_service.complete_intervention(intervention.id, comp_req, actor_user_id=42)
    assert intervention.status == InterventionStatus.COMPLETED
    assert intervention.after_risk_score == 40.0
    assert intervention.risk_reduction == 45.0


@pytest.mark.asyncio
async def test_reject_intervention(intervention_service, base_intervention_data):
    intervention = await intervention_service.create_intervention(base_intervention_data)
    intervention = await intervention_service.set_pending_approval(intervention.id)
    
    rej_req = RejectRequest(user_id=99, decision_reason="Not safe enough")
    intervention = await intervention_service.reject_intervention(intervention.id, rej_req, actor_user_id=99)
    
    assert intervention.status == InterventionStatus.REJECTED
    assert intervention.result.approved_by_user_id == 99
    assert "REJECTED" in intervention.result.decision_reason


@pytest.mark.asyncio
async def test_cancel_intervention(intervention_service, base_intervention_data):
    intervention = await intervention_service.create_intervention(base_intervention_data)
    
    cancel_req = CancelRequest(user_id=101, decision_reason="False alarm")
    intervention = await intervention_service.cancel_intervention(intervention.id, cancel_req, actor_user_id=101)
    
    assert intervention.status == InterventionStatus.CANCELLED
    assert intervention.result.approved_by_user_id == 101
    assert "CANCELLED" in intervention.result.decision_reason


@pytest.mark.asyncio
async def test_invalid_transition_to_approve(intervention_service, base_intervention_data):
    # Cannot approve directly from PROPOSED
    intervention = await intervention_service.create_intervention(base_intervention_data)
    
    app_req = ApprovalRequest(
        user_id=1,
        decision_reason="Skip steps"
    )
    with pytest.raises(ValueError, match="Cannot approve intervention in status"):
        await intervention_service.approve_intervention(intervention.id, app_req, actor_user_id=1)


@pytest.mark.asyncio
async def test_invalid_transition_to_activate(intervention_service, base_intervention_data):
    # Cannot activate directly from PROPOSED
    intervention = await intervention_service.create_intervention(base_intervention_data)
    
    with pytest.raises(ValueError, match="Cannot activate intervention in status"):
        await intervention_service.activate_intervention(intervention.id, actor_user_id=1)


@pytest.mark.asyncio
async def test_invalid_cancellation_from_terminal(intervention_service, base_intervention_data):
    # Setup up to COMPLETION
    intervention = await intervention_service.create_intervention(base_intervention_data)
    await intervention_service.set_pending_approval(intervention.id)
    app_req = ApprovalRequest(user_id=42, decision_reason="ok")
    await intervention_service.approve_intervention(intervention.id, app_req, actor_user_id=42)
    await intervention_service.activate_intervention(intervention.id, actor_user_id=42)
    await intervention_service.complete_intervention(intervention.id, CompleteRequest(), actor_user_id=42)
    
    cancel_req = CancelRequest(user_id=101, decision_reason="Try to cancel after complete")
    with pytest.raises(ValueError, match="terminal status"):
        await intervention_service.cancel_intervention(intervention.id, cancel_req, actor_user_id=101)
