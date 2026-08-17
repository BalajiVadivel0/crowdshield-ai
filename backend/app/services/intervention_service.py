"""
Intervention Service Layer.

Enforces strict state transitions and business logic for the
Authority Intervention & Approval Backend.

Allowed Transitions:
- PROPOSED -> SIMULATING -> PENDING_APPROVAL -> CANCELLED
- SIMULATING -> PENDING_APPROVAL -> CANCELLED
- PENDING_APPROVAL -> APPROVED -> REJECTED -> CANCELLED
- APPROVED -> ACTIVATED -> CANCELLED
- ACTIVATED -> COMPLETED -> CANCELLED
"""

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.intervention import Intervention, InterventionAction, InterventionResult, InterventionStatus, InterventionAudit
from app.schemas.intervention import ApprovalRequest, CancelRequest, CompleteRequest, InterventionCreate, RejectRequest


class InterventionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_intervention(self, intervention_id: int) -> Optional[Intervention]:
        """Fetch an intervention with its actions and result by ID."""
        query = select(Intervention).options(
            selectinload(Intervention.actions),
            selectinload(Intervention.result)
        ).where(Intervention.id == intervention_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_interventions(self, event_id: Optional[int] = None) -> List[Intervention]:
        """List interventions, optionally filtered by event_id."""
        query = select(Intervention).options(
            selectinload(Intervention.actions),
            selectinload(Intervention.result)
        )
        if event_id is not None:
            query = query.where(Intervention.event_id == event_id)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create_intervention(self, data: InterventionCreate) -> Intervention:
        """Create a new PROPOSED intervention."""
        intervention = Intervention(
            event_id=data.event_id,
            zone_id=data.zone_id,
            status=InterventionStatus.PROPOSED,
            before_risk_score=data.before_risk_score,
            affected_zones=data.affected_zones
        )
        self.session.add(intervention)
        await self.session.flush()

        for action_data in data.actions:
            action = InterventionAction(
                intervention_id=intervention.id,
                action_type=action_data.action_type,
                description=action_data.description
            )
            self.session.add(action)

        await self.session.commit()
        await self.session.refresh(intervention)
        
        # Load relationships so returned object is fully populated
        return await self.get_intervention(intervention.id)

    async def set_simulating(self, intervention_id: int) -> Intervention:
        """Transition from PROPOSED to SIMULATING."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.PROPOSED:
            raise ValueError(f"Cannot simulate intervention in status: {intervention.status.value}")

        intervention.status = InterventionStatus.SIMULATING
        await self.session.commit()
        return intervention

    async def set_pending_approval(self, intervention_id: int) -> Intervention:
        """Transition from PROPOSED/SIMULATING to PENDING_APPROVAL."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status not in (InterventionStatus.PROPOSED, InterventionStatus.SIMULATING):
            raise ValueError(f"Cannot request approval for status: {intervention.status.value}")

        intervention.status = InterventionStatus.PENDING_APPROVAL
        await self.session.commit()
        return intervention

    async def approve_intervention(self, intervention_id: int, req: ApprovalRequest, actor_user_id: int) -> Intervention:
        """
        Transition from PENDING_APPROVAL to APPROVED.
        Requires recording an audit trail in InterventionResult.
        """
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.PENDING_APPROVAL:
            raise ValueError(f"Cannot approve intervention in status: {intervention.status.value}")

        previous_status = intervention.status
        intervention.status = InterventionStatus.APPROVED
        
        # Create result audit
        result = InterventionResult(
            approved_by_user_id=actor_user_id,
            simulation_scenario_used=req.scenario,
            expected_effect=req.expected_effect,
            decision_reason=req.decision_reason
        )
        intervention.result = result
        
        audit = InterventionAudit(
            intervention_id=intervention.id,
            action="APPROVE",
            actor_user_id=actor_user_id,
            previous_status=previous_status,
            new_status=intervention.status
        )
        self.session.add(audit)
        
        await self.session.commit()
        return intervention

    async def reject_intervention(self, intervention_id: int, req: RejectRequest, actor_user_id: int) -> Intervention:
        """
        Transition from PENDING_APPROVAL to REJECTED.
        """
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.PENDING_APPROVAL:
            raise ValueError(f"Cannot reject intervention in status: {intervention.status.value}")

        previous_status = intervention.status
        intervention.status = InterventionStatus.REJECTED
        
        # Create result audit for rejection
        result = InterventionResult(
            approved_by_user_id=actor_user_id,
            decision_reason=f"REJECTED: {req.decision_reason}"
        )
        intervention.result = result

        audit = InterventionAudit(
            intervention_id=intervention.id,
            action="REJECT",
            actor_user_id=actor_user_id,
            previous_status=previous_status,
            new_status=intervention.status
        )
        self.session.add(audit)

        await self.session.commit()
        return intervention

    async def activate_intervention(self, intervention_id: int, actor_user_id: int) -> Intervention:
        """Transition from APPROVED to ACTIVATED."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.APPROVED:
            raise ValueError(f"Cannot activate intervention in status: {intervention.status.value}")

        previous_status = intervention.status
        intervention.status = InterventionStatus.ACTIVATED
        
        audit = InterventionAudit(
            intervention_id=intervention.id,
            action="ACTIVATE",
            actor_user_id=actor_user_id,
            previous_status=previous_status,
            new_status=intervention.status
        )
        self.session.add(audit)
        
        await self.session.commit()
        return intervention

    async def complete_intervention(self, intervention_id: int, req: CompleteRequest, actor_user_id: int) -> Intervention:
        """Transition from ACTIVATED to COMPLETED, storing final risk outcome."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.ACTIVATED:
            raise ValueError(f"Cannot complete intervention in status: {intervention.status.value}")

        previous_status = intervention.status
        intervention.status = InterventionStatus.COMPLETED
        
        if req.after_risk_score is not None:
            intervention.after_risk_score = req.after_risk_score
            intervention.risk_reduction = intervention.before_risk_score - req.after_risk_score

        audit = InterventionAudit(
            intervention_id=intervention.id,
            action="COMPLETE",
            actor_user_id=actor_user_id,
            previous_status=previous_status,
            new_status=intervention.status
        )
        self.session.add(audit)

        await self.session.commit()
        return intervention

    async def cancel_intervention(self, intervention_id: int, req: CancelRequest, actor_user_id: int) -> Intervention:
        """
        Transition to CANCELLED from any non-terminal state.
        Terminal states: COMPLETED, REJECTED, CANCELLED.
        """
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        terminal_states = {
            InterventionStatus.COMPLETED,
            InterventionStatus.REJECTED,
            InterventionStatus.CANCELLED
        }
        
        if intervention.status in terminal_states:
            raise ValueError(f"Cannot cancel intervention already in terminal status: {intervention.status.value}")

        previous_status = intervention.status
        intervention.status = InterventionStatus.CANCELLED

        # Record cancellation reason if a result record doesn't exist,
        # or append to it if it does.
        if intervention.result:
            intervention.result.decision_reason += f"\nCANCELLED: {req.decision_reason}"
        else:
            result = InterventionResult(
                approved_by_user_id=actor_user_id,
                decision_reason=f"CANCELLED: {req.decision_reason}"
            )
            intervention.result = result

        audit = InterventionAudit(
            intervention_id=intervention.id,
            action="CANCEL",
            actor_user_id=actor_user_id,
            previous_status=previous_status,
            new_status=intervention.status
        )
        self.session.add(audit)

        await self.session.commit()
        return intervention
