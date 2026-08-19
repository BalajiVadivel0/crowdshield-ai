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

    async def _build_hydrated_graph(self, event_id: int):
        from app.models.crowd_reading import CrowdReading
        from app.models.risk_assessment import RiskAssessmentRecord
        from app.services.routing_service import RoutingService
        from sqlalchemy import desc
        
        venue_graph = await RoutingService.build_venue_graph(self.session, event_id)
        
        # Get unique zones
        result = await self.session.execute(
            select(CrowdReading.zone_id).where(CrowdReading.event_id == event_id).distinct()
        )
        zone_ids = [row[0] for row in result.fetchall()]
        
        current_assessments = {}
        
        for zone_id in zone_ids:
            r_result = await self.session.execute(
                select(CrowdReading).where(CrowdReading.event_id == event_id, CrowdReading.zone_id == zone_id)
                .order_by(desc(CrowdReading.timestamp)).limit(1)
            )
            reading = r_result.scalar_one_or_none()
            
            a_result = await self.session.execute(
                select(RiskAssessmentRecord).where(
                    RiskAssessmentRecord.event_id == event_id, RiskAssessmentRecord.zone_id == zone_id
                ).order_by(desc(RiskAssessmentRecord.timestamp)).limit(1)
            )
            assessment = a_result.scalar_one_or_none()
            
            node_id = str(zone_id)
            if reading and node_id in venue_graph.nodes:
                venue_graph.nodes[node_id].current_crowd = reading.person_count
            if assessment:
                if node_id in venue_graph.nodes:
                    venue_graph.nodes[node_id].risk_score = assessment.risk_score
                # Mock a RiskAssessment-like object with .score for the NetworkPropagationEngine
                from app.ai.risk_engine.models import RiskAssessment, RiskLevel, RiskType, RiskFeatures
                features = RiskFeatures(
                    density_risk=assessment.density_risk,
                    growth_risk=assessment.growth_risk,
                    movement_conflict_risk=assessment.movement_conflict_risk,
                    speed_reduction_risk=assessment.speed_reduction_risk,
                    surge_signal=assessment.surge_signal,
                    reverse_flow_signal=assessment.reverse_flow_signal,
                    bottleneck_signal=assessment.bottleneck_signal,
                    congestion_signal=False
                )
                current_assessments[node_id] = RiskAssessment(
                    score=assessment.risk_score,
                    level=RiskLevel(assessment.risk_level),
                    risk_type=RiskType(assessment.risk_type),
                    features=features,
                    explanation=assessment.explanation,
                    event_id=assessment.event_id,
                    zone_id=assessment.zone_id,
                    source_timestamp=assessment.timestamp.isoformat()
                )
                
        return venue_graph, current_assessments

    async def simulate_recommendation(self, recommendation_id: int):
        rec = await self.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError("Recommendation not found")
            
        if rec.status != RecommendationStatus.GENERATED:
            raise ValueError(f"Cannot simulate recommendation in status {rec.status}")

        from app.schemas.recommendation import RecommendationSimulationResponse
        from app.ai.prediction_engine.propagation import NetworkPropagationEngine
        from app.ai.simulation.mutations import MutationBuilder, apply_mutations
        from app.ai.simulation.ranker import SimulationRanker
        from app.ai.recommendation_engine.models import ActionType

        horizon_minutes = 15
        venue_graph, current_assessments = await self._build_hydrated_graph(rec.event_id)
        network_engine = NetworkPropagationEngine()
        
        # 1. Baseline Snapshot
        baseline_graph = venue_graph.clone()
        baseline_sim_state, baseline_trace = network_engine.forecast_network_risk(
            baseline_graph, current_assessments, horizon_minutes=horizon_minutes
        )
        
        # Determine baseline peak risk
        baseline_peak_risk = 0.0
        for ra in baseline_sim_state.values():
            risk = ra.score
            baseline_peak_risk = max(baseline_peak_risk, risk)

        # Check if simulatable
        try:
            target_zone = str(rec.zone_id) if rec.zone_id else None
            action_enum = ActionType(rec.action_type)
            mutations = MutationBuilder.build_mutations(action_enum, target_zone, venue_graph)
        except ValueError as e:
            # Action is not simulatable or invalid mutation target
            print(f"Simulation ValueError for {rec.action_type}: {e}")
            unsupported_metrics = SimulationRanker.build_unsupported_metrics(baseline_peak_risk, horizon_minutes)
            return RecommendationSimulationResponse(
                recommendation_id=rec.id,
                **unsupported_metrics.dict()
            )
            
        # 2. Scenario Simulation
        scenario_graph = venue_graph.clone()
        apply_mutations(scenario_graph, mutations)
        
        scenario_state, _ = network_engine.forecast_network_risk(
            scenario_graph, current_assessments, horizon_minutes=horizon_minutes
        )
        
        # 3. Metrics and Rank
        metrics = SimulationRanker.calculate_metrics(
            baseline_risk=baseline_peak_risk,
            scenario_state=scenario_state,
            horizon_minutes=horizon_minutes,
            affected_zones=rec.affected_zones
        )
        
        return RecommendationSimulationResponse(
            recommendation_id=rec.id,
            **metrics.dict()
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
