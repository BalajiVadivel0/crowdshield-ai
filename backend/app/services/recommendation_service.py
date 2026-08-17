from typing import List, Optional
from datetime import datetime, timezone
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.recommendation import RecommendationModel, RecommendationStatus
from app.ai.recommendation_engine.engine import RecommendationEngine
from app.ai.recommendation_engine.models import RecommendationPriority
from app.schemas.crowd_intelligence import EventCrowdIntelligence
from app.services.intervention_service import InterventionService
from app.schemas.intervention import InterventionCreate, InterventionActionCreate, ApprovalRequest
from app.ai.simulation.service import CrowdSimulationService
from app.ai.simulation.scenarios import ScenarioType

class RecommendationService:
    def __init__(self, session: AsyncSession, intervention_service: InterventionService):
        self.session = session
        self.intervention_service = intervention_service
        self.simulation_service = CrowdSimulationService()
        self.engine = RecommendationEngine()

    async def get_recommendation(self, recommendation_id: int) -> Optional[RecommendationModel]:
        query = select(RecommendationModel).where(RecommendationModel.id == recommendation_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_active_recommendations(self, event_id: int) -> List[RecommendationModel]:
        query = select(RecommendationModel).where(
            RecommendationModel.event_id == event_id,
            RecommendationModel.status == RecommendationStatus.GENERATED
        ).order_by(RecommendationModel.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def generate_and_persist(self, intelligence: EventCrowdIntelligence) -> List[RecommendationModel]:
        """
        Generate recommendations from current intelligence, deduplicate,
        mark old active recommendations as STALE if they are no longer generated,
        and persist new ones.
        """
        # 1. Generate new recommendations
        new_recs = self.engine.recommend(intelligence)
        
        # 2. Get existing active recommendations
        query = select(RecommendationModel).where(
            RecommendationModel.event_id == intelligence.event_id,
            RecommendationModel.status == RecommendationStatus.GENERATED
        )
        result = await self.session.execute(query)
        existing_active = list(result.scalars().all())
        
        # 3. Match them up by recommendation_id (the deterministic string)
        new_rec_ids = {r.recommendation_id for r in new_recs}
        
        # 4. Mark STALE those that are no longer recommended
        for existing in existing_active:
            if existing.recommendation_id not in new_rec_ids:
                existing.status = RecommendationStatus.STALE
                existing.expires_at = datetime.now(timezone.utc)
                self.session.add(existing)

        # 5. Insert new ones if they don't already exist as active
        existing_active_ids = {r.recommendation_id for r in existing_active if r.status == RecommendationStatus.GENERATED}
        persisted_recs = []
        
        for new_rec in new_recs:
            if new_rec.recommendation_id not in existing_active_ids:
                db_rec = RecommendationModel(
                    recommendation_id=new_rec.recommendation_id,
                    event_id=new_rec.event_id,
                    zone_id=new_rec.zone_id,
                    action_type=new_rec.action_type.value,
                    priority=new_rec.priority.value,
                    confidence=new_rec.confidence,
                    reason=new_rec.reason,
                    triggering_conditions=[cond.dict() for cond in new_rec.triggering_conditions],
                    expected_effect=new_rec.expected_effect,
                    affected_zones=new_rec.affected_zones,
                    status=RecommendationStatus.GENERATED
                )
                self.session.add(db_rec)
                persisted_recs.append(db_rec)
        
        await self.session.commit()
        
        # Return all active recommendations
        return await self.list_active_recommendations(intelligence.event_id)

    async def simulate_recommendation(self, recommendation_id: int):
        rec = await self.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError("Recommendation not found")
            
        if rec.status != RecommendationStatus.GENERATED:
            raise ValueError(f"Cannot simulate recommendation in status {rec.status}")

        # Simulate the 'NORMAL' scenario to show risk reduction
        # In a real system, this would use a more sophisticated model mapping action_type to an outcome.
        readings = self.simulation_service.generate_scenario(
            event_id=rec.event_id,
            zone_id=rec.zone_id or 1,
            zone_capacity=1000, # default capacity
            scenario=ScenarioType.NORMAL,
            total_steps=5,
            step_seconds=60
        )
        # Dummy result based on readings
        simulated_risk = 20.0
        risk_reduction = max(0.0, (rec.confidence * 100) - simulated_risk)
        
        from app.schemas.recommendation import RecommendationSimulationResponse
        return RecommendationSimulationResponse(
            recommendation_id=rec.id,
            current_risk=rec.confidence * 100,
            simulated_risk=simulated_risk,
            risk_reduction=risk_reduction,
            affected_zones=rec.affected_zones
        )

    async def approve_recommendation(self, recommendation_id: int, user_id: int):
        rec = await self.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError("Recommendation not found")
            
        if rec.status != RecommendationStatus.GENERATED:
            raise ValueError(f"Cannot approve recommendation in status {rec.status}")

        # 1. Create Intervention
        intervention_create = InterventionCreate(
            event_id=rec.event_id,
            zone_id=rec.zone_id,
            before_risk_score=rec.confidence * 100, # Approximation for before risk
            affected_zones=rec.affected_zones,
            actions=[
                InterventionActionCreate(
                    action_type=rec.action_type,
                    description=rec.reason
                )
            ]
        )
        
        intervention = await self.intervention_service.create_intervention(intervention_create)
        
        # Advance intervention through required states for Approval
        await self.intervention_service.set_simulating(intervention.id)
        await self.intervention_service.set_pending_approval(intervention.id)
        
        # Approve intervention
        approval_req = ApprovalRequest(
            user_id=user_id,
            scenario="RECOMMENDATION_ENGINE",
            expected_effect=rec.expected_effect,
            decision_reason="Approved from AI Recommendation"
        )
        approved_intervention = await self.intervention_service.approve_intervention(intervention.id, approval_req, actor_user_id=user_id)

        # 2. Mark Recommendation as APPROVED
        rec.status = RecommendationStatus.APPROVED
        rec.approved_by_id = user_id
        rec.created_intervention_id = approved_intervention.id
        self.session.add(rec)
        await self.session.commit()
        
        return rec, approved_intervention

    async def reject_recommendation(self, recommendation_id: int, user_id: int):
        rec = await self.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError("Recommendation not found")
            
        if rec.status != RecommendationStatus.GENERATED:
            raise ValueError(f"Cannot reject recommendation in status {rec.status}")

        rec.status = RecommendationStatus.REJECTED
        rec.approved_by_id = user_id
        self.session.add(rec)
        await self.session.commit()
        return rec
