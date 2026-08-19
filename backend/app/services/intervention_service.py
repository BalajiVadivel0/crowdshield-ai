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

from app.models.intervention import Intervention, InterventionAction, InterventionResult, InterventionStatus
from app.models.audit import AuditLog
from app.models.user import User
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

    async def create_intervention(self, data: InterventionCreate, current_user: User) -> Intervention:
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

        # Log creation
        await self._log_audit(
            intervention=intervention, 
            action="CREATE",
            old_status=None, 
            new_status=intervention.status,
            user=current_user, 
            reason="Intervention Created",
            metadata={
                "before_risk_score": data.before_risk_score,
                "actions_count": len(data.actions)
            }
        )
        
        await self.session.commit()
        await self.session.refresh(intervention)
        
        # Load relationships so returned object is fully populated
        return await self.get_intervention(intervention.id)

    async def _log_audit(
        self, 
        intervention: Intervention, 
        action: str, 
        old_status: Optional[InterventionStatus], 
        new_status: InterventionStatus, 
        user: Optional[User] = None, 
        reason: Optional[str] = None,
        metadata: Optional[dict] = None
    ):
        """Append an audit log record for state transitions (uncommitted)."""
        log = AuditLog(
            actor_user_id=user.id if user else None,
            actor_role=user.role.value if user else None,
            entity_type="INTERVENTION",
            entity_id=intervention.id,
            event_id=intervention.event_id,
            zone_id=intervention.zone_id,
            action=action,
            previous_state=old_status.value if old_status else None,
            new_state=new_status.value,
            reason=reason,
            metadata_=metadata
        )
        self.session.add(log)

    async def set_simulating(self, intervention_id: int, current_user: User) -> Intervention:
        """Transition from PROPOSED to SIMULATING."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.PROPOSED:
            raise ValueError(f"Cannot simulate intervention in status: {intervention.status.value}")

        old_status = intervention.status
        intervention.status = InterventionStatus.SIMULATING
        
        await self._log_audit(
            intervention=intervention, 
            action="SIMULATE",
            old_status=old_status, 
            new_status=intervention.status,
            user=current_user, 
            reason="Simulating intervention"
        )
        await self.session.commit()
        return intervention

    async def set_pending_approval(self, intervention_id: int, current_user: User) -> Intervention:
        """Transition from PROPOSED/SIMULATING to PENDING_APPROVAL."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status not in (InterventionStatus.PROPOSED, InterventionStatus.SIMULATING):
            raise ValueError(f"Cannot request approval for status: {intervention.status.value}")

        old_status = intervention.status
        intervention.status = InterventionStatus.PENDING_APPROVAL
        
        await self._log_audit(
            intervention=intervention, 
            action="REQUEST_APPROVAL",
            old_status=old_status, 
            new_status=intervention.status,
            user=current_user, 
            reason="Requested approval"
        )
        await self.session.commit()
        return intervention

    async def approve_intervention(self, intervention_id: int, req: ApprovalRequest, current_user: User) -> Intervention:
        """
        Transition from PENDING_APPROVAL to APPROVED.
        Requires recording an audit trail in InterventionResult.
        """
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.PENDING_APPROVAL:
            raise ValueError(f"Cannot approve intervention in status: {intervention.status.value}")

        old_status = intervention.status
        intervention.status = InterventionStatus.APPROVED
        
        # Create result audit
        result = InterventionResult(
            approved_by_user_id=current_user.id,
            simulation_scenario_used=req.scenario,
            expected_effect=req.expected_effect,
            decision_reason=req.decision_reason
        )
        intervention.result = result
        
        await self._log_audit(
            intervention=intervention, 
            action="APPROVE",
            old_status=old_status, 
            new_status=intervention.status,
            user=current_user, 
            reason=req.decision_reason,
            metadata={
                "scenario": req.scenario,
                "expected_effect": req.expected_effect
            }
        )
        await self.session.commit()
        return intervention

    async def reject_intervention(self, intervention_id: int, req: RejectRequest, current_user: User) -> Intervention:
        """
        Transition from PENDING_APPROVAL to REJECTED.
        """
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.PENDING_APPROVAL:
            raise ValueError(f"Cannot reject intervention in status: {intervention.status.value}")

        old_status = intervention.status
        intervention.status = InterventionStatus.REJECTED
        
        # Create result audit for rejection
        result = InterventionResult(
            approved_by_user_id=current_user.id,
            decision_reason=f"REJECTED: {req.decision_reason}"
        )
        intervention.result = result

        await self._log_audit(
            intervention=intervention, 
            action="REJECT",
            old_status=old_status, 
            new_status=intervention.status,
            user=current_user, 
            reason=req.decision_reason
        )
        await self.session.commit()
        return intervention

    async def activate_intervention(self, intervention_id: int, current_user: User) -> Intervention:
        """Transition from APPROVED to ACTIVATED."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.APPROVED:
            raise ValueError(f"Cannot activate intervention in status: {intervention.status.value}")

        old_status = intervention.status
        intervention.status = InterventionStatus.ACTIVATED
        
        await self._log_audit(
            intervention=intervention, 
            action="ACTIVATE",
            old_status=old_status, 
            new_status=intervention.status,
            user=current_user, 
            reason="Activated intervention"
        )
        await self.session.commit()
        return intervention

    async def complete_intervention(self, intervention_id: int, req: CompleteRequest, current_user: User) -> Intervention:
        """Transition from ACTIVATED to COMPLETED, storing final risk outcome."""
        intervention = await self.get_intervention(intervention_id)
        if not intervention:
            raise ValueError("Intervention not found")

        if intervention.status != InterventionStatus.ACTIVATED:
            raise ValueError(f"Cannot complete intervention in status: {intervention.status.value}")

        old_status = intervention.status
        intervention.status = InterventionStatus.COMPLETED
        
        if req.after_risk_score is not None:
            intervention.after_risk_score = req.after_risk_score
            intervention.risk_reduction = intervention.before_risk_score - req.after_risk_score

        await self._log_audit(
            intervention=intervention, 
            action="COMPLETE",
            old_status=old_status, 
            new_status=intervention.status,
            user=current_user, 
            reason="Completed intervention",
            metadata={
                "after_risk_score": req.after_risk_score
            } if req.after_risk_score is not None else None
        )
        await self.session.commit()
        return intervention

    async def cancel_intervention(self, intervention_id: int, req: CancelRequest, current_user: User) -> Intervention:
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

        old_status = intervention.status
        intervention.status = InterventionStatus.CANCELLED

        # Record cancellation reason if a result record doesn't exist,
        # or append to it if it does.
        if intervention.result:
            intervention.result.decision_reason += f"\nCANCELLED: {req.decision_reason}"
        else:
            result = InterventionResult(
                approved_by_user_id=current_user.id,
                decision_reason=f"CANCELLED: {req.decision_reason}"
            )
            intervention.result = result

        await self._log_audit(
            intervention=intervention, 
            action="CANCEL",
            old_status=old_status, 
            new_status=intervention.status,
            user=current_user, 
            reason=req.decision_reason
        )
        await self.session.commit()
        return intervention
