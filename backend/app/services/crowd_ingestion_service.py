"""
Crowd Ingestion Service.

Orchestrates the full pipeline when a new crowd reading arrives:
  1. Validate event and zone existence in the DB.
  2. Persist the CrowdReading.
  3. Run RiskEngine → persist RiskAssessmentRecord.
  4. Load historical risk records → run PredictionEngine.
  5. Run CrowdIntelligenceService for the event-wide snapshot.

Architecture rules enforced here:
  - No AI logic lives inside this service.
  - No DB logic lives inside AI engines.
  - Router handlers remain thin callers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crowd_reading import CrowdReading
from app.models.event import Event
from app.models.zone import Zone
from app.models.risk_assessment import RiskAssessmentRecord
from app.schemas.crowd_reading import CrowdReadingCreate, CrowdReadingResponse

from app.ai.risk_engine.engine import RiskEngine
from app.ai.risk_engine.models import RiskAssessment, RiskFeatures, RiskLevel, RiskType
from app.ai.prediction_engine.engine import PredictionEngine
from app.ai.prediction_engine.models import PredictionResult
from app.services.crowd_intelligence_service import CrowdIntelligenceService
from app.schemas.crowd_intelligence import EventCrowdIntelligence


# How many past risk assessments to feed the PredictionEngine for trend analysis.
PREDICTION_HISTORY_LIMIT = 20


class EventNotFoundError(Exception):
    pass


class ZoneNotFoundError(Exception):
    pass


class CrowdIngestionService:
    """
    Orchestrates a single crowd reading through the full AI pipeline and
    persists all produced artefacts.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._risk_engine = RiskEngine()
        self._prediction_engine = PredictionEngine()
        self._intelligence_service = CrowdIntelligenceService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest(
        self, data: CrowdReadingCreate
    ) -> tuple[CrowdReadingResponse, RiskAssessment, PredictionResult, EventCrowdIntelligence]:
        """
        Full pipeline for one crowd reading.

        Returns:
            (crowd_reading_response, risk_assessment, prediction_result, intelligence)
        """
        # 1. Validate foreign references
        await self._validate_event(data.event_id)
        await self._validate_zone(data.event_id, data.zone_id)

        # 2. Persist CrowdReading
        crowd_reading_response = await self._persist_crowd_reading(data)

        # 3. Load historical risk assessments for risk evaluation and prediction
        history = await self._load_risk_history(data.event_id, data.zone_id)

        # 4. Risk evaluation (with hysteresis & multi-signal using history)
        risk_assessment = self._risk_engine.evaluate(crowd_reading_response, history)

        # 5. Persist RiskAssessmentRecord
        await self._persist_risk_assessment(
            risk_assessment, crowd_reading_response.id, crowd_reading_response.timestamp
        )

        # 6. Run prediction (include the new assessment in the history)
        prediction_history = [risk_assessment] + history
        prediction_result = self._prediction_engine.predict(prediction_history)

        # 7. Build event-wide intelligence
        intelligence = await self._aggregate_intelligence(data.event_id)

        # 8. Recommendation Generation
        from app.services.recommendation_service import RecommendationService
        from app.services.intervention_service import InterventionService
        
        intervention_svc = InterventionService(self._db)
        rec_svc = RecommendationService(self._db, intervention_svc)
        
        active_recommendations = await rec_svc.generate_and_persist(intelligence)

        # 9. Alert generation and delivery
        from app.services.alert_service import AlertService
        alert_service = AlertService(self._db)
        await alert_service.process_intelligence_and_broadcast(intelligence)

        # 10. Broadcast real-time intelligence updates
        from app.services.realtime_event_service import RealtimeEventService
        realtime_service = RealtimeEventService()
        await realtime_service.process_intelligence_update(intelligence)
        
        # 11. Broadcast real-time recommendations update
        if active_recommendations:
            from app.services.websocket_manager import manager
            from app.schemas.websocket_events import WSEventType
            payload = {
                "event_id": intelligence.event_id,
                "recommendation_ids": [r.id for r in active_recommendations]
            }
            await manager.broadcast_authority(
                event_type=WSEventType.RECOMMENDATIONS_UPDATE.value,
                payload=payload
            )

        return crowd_reading_response, risk_assessment, prediction_result, intelligence

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    async def _validate_event(self, event_id: int) -> Event:
        result = await self._db.execute(
            select(Event).where(Event.id == event_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            raise EventNotFoundError(f"Event {event_id} does not exist.")
        return event

    async def _validate_zone(self, event_id: int, zone_id: int) -> Zone:
        result = await self._db.execute(
            select(Zone).where(Zone.id == zone_id, Zone.event_id == event_id)
        )
        zone = result.scalar_one_or_none()
        if zone is None:
            raise ZoneNotFoundError(
                f"Zone {zone_id} does not exist or does not belong to event {event_id}."
            )
        return zone

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist_crowd_reading(self, data: CrowdReadingCreate) -> CrowdReadingResponse:
        db_reading = CrowdReading(
            event_id=data.event_id,
            zone_id=data.zone_id,
            timestamp=data.timestamp,
            person_count=data.person_count,
            density_percent=data.density_percent,
            average_speed=data.average_speed,
            dominant_direction=data.dominant_direction,
            crowd_growth_rate=data.crowd_growth_rate,
            congestion_score=data.congestion_score,
            surge_indicator=data.surge_indicator,
            reverse_flow_indicator=data.reverse_flow_indicator,
            bottleneck_indicator=data.bottleneck_indicator,
        )
        self._db.add(db_reading)
        await self._db.flush()  # get the auto-generated id without committing
        await self._db.refresh(db_reading)
        return CrowdReadingResponse.model_validate(db_reading)

    async def _persist_risk_assessment(
        self,
        assessment: RiskAssessment,
        crowd_reading_id: int,
        source_timestamp: datetime,
    ) -> RiskAssessmentRecord:
        record = RiskAssessmentRecord(
            event_id=assessment.event_id,
            zone_id=assessment.zone_id,
            crowd_reading_id=crowd_reading_id,
            timestamp=source_timestamp,
            risk_score=assessment.score,
            risk_level=assessment.level.value,
            risk_type=assessment.risk_type.value,
            explanation=assessment.explanation,
            density_risk=assessment.features.density_risk,
            growth_risk=assessment.features.growth_risk,
            movement_conflict_risk=assessment.features.movement_conflict_risk,
            speed_reduction_risk=assessment.features.speed_reduction_risk,
            surge_signal=assessment.features.surge_signal,
            reverse_flow_signal=assessment.features.reverse_flow_signal,
            bottleneck_signal=assessment.features.bottleneck_signal,
        )
        self._db.add(record)
        await self._db.flush()
        await self._db.refresh(record)
        await self._db.commit()
        return record

    # ------------------------------------------------------------------
    # History loading
    # ------------------------------------------------------------------

    async def _load_risk_history(
        self, event_id: int, zone_id: int
    ) -> List[RiskAssessment]:
        """
        Loads the most recent risk assessment records and converts them to
        the Pydantic RiskAssessment objects that PredictionEngine expects.
        """
        result = await self._db.execute(
            select(RiskAssessmentRecord)
            .where(
                RiskAssessmentRecord.event_id == event_id,
                RiskAssessmentRecord.zone_id == zone_id,
            )
            .order_by(desc(RiskAssessmentRecord.timestamp))
            .limit(PREDICTION_HISTORY_LIMIT)
        )
        records: List[RiskAssessmentRecord] = list(result.scalars().all())

        return [self._record_to_pydantic(r) for r in records]

    @staticmethod
    def _record_to_pydantic(record: RiskAssessmentRecord) -> RiskAssessment:
        """Convert a DB RiskAssessmentRecord → Pydantic RiskAssessment for AI engines."""
        features = RiskFeatures(
            density_risk=record.density_risk,
            growth_risk=record.growth_risk,
            movement_conflict_risk=record.movement_conflict_risk,
            speed_reduction_risk=record.speed_reduction_risk,
            surge_signal=record.surge_signal,
            reverse_flow_signal=record.reverse_flow_signal,
            bottleneck_signal=record.bottleneck_signal,
            congestion_signal=(record.movement_conflict_risk > 0),  # best proxy from stored data
        )
        return RiskAssessment(
            score=record.risk_score,
            level=RiskLevel(record.risk_level),
            risk_type=RiskType(record.risk_type),
            features=features,
            explanation=record.explanation,
            event_id=record.event_id,
            zone_id=record.zone_id,
            source_timestamp=record.timestamp.isoformat(),
        )

    # ------------------------------------------------------------------
    # Intelligence aggregation
    # ------------------------------------------------------------------

    async def _aggregate_intelligence(self, event_id: int) -> EventCrowdIntelligence:
        """
        Builds an event-wide intelligence snapshot from the latest DB state.

        Strategy:
          - For each zone in the event, take the single most-recent CrowdReading
            and the most-recent RiskAssessmentRecord.
          - Re-run PredictionEngine per zone with its local history.
          - Load recent active incidents.
          - Feed everything to CrowdIntelligenceService.
        """
        from app.models.incident import IncidentReport, IncidentStatus
        from datetime import timedelta
        
        # Load recent active incidents for this event
        now_utc = datetime.now(timezone.utc)
        two_hours_ago = now_utc - timedelta(hours=2)
        
        inc_result = await self._db.execute(
            select(IncidentReport)
            .where(
                IncidentReport.event_id == event_id,
                IncidentReport.status.in_([
                    IncidentStatus.OPEN,
                    IncidentStatus.ACKNOWLEDGED,
                    IncidentStatus.INVESTIGATING
                ]),
                IncidentReport.created_at >= two_hours_ago
            )
        )
        active_incidents = list(inc_result.scalars().all())

        # Find all unique zone IDs that have readings for this event
        result = await self._db.execute(
            select(CrowdReading.zone_id)
            .where(CrowdReading.event_id == event_id)
            .distinct()
        )
        zone_ids = [row[0] for row in result.fetchall()]

        readings: List[CrowdReadingCreate] = []
        assessments: List[RiskAssessment] = []
        predictions: List[PredictionResult] = []

        for zone_id in zone_ids:
            # Latest reading for this zone
            r_result = await self._db.execute(
                select(CrowdReading)
                .where(CrowdReading.event_id == event_id, CrowdReading.zone_id == zone_id)
                .order_by(desc(CrowdReading.timestamp))
                .limit(1)
            )
            reading = r_result.scalar_one_or_none()
            if reading is None:
                continue

            # Latest risk assessment for this zone
            a_result = await self._db.execute(
                select(RiskAssessmentRecord)
                .where(
                    RiskAssessmentRecord.event_id == event_id,
                    RiskAssessmentRecord.zone_id == zone_id,
                )
                .order_by(desc(RiskAssessmentRecord.timestamp))
                .limit(1)
            )
            assessment_record = a_result.scalar_one_or_none()
            if assessment_record is None:
                continue

            # Build Pydantic objects
            reading_schema = CrowdReadingCreate(
                event_id=reading.event_id,
                zone_id=reading.zone_id,
                timestamp=reading.timestamp,
                person_count=reading.person_count,
                density_percent=reading.density_percent,
                average_speed=reading.average_speed,
                dominant_direction=reading.dominant_direction,
                crowd_growth_rate=reading.crowd_growth_rate,
                congestion_score=reading.congestion_score,
                surge_indicator=reading.surge_indicator,
                reverse_flow_indicator=reading.reverse_flow_indicator,
                bottleneck_indicator=reading.bottleneck_indicator,
            )
            assessment_pydantic = self._record_to_pydantic(assessment_record)

            # Zone prediction history
            zone_history = await self._load_risk_history(event_id, zone_id)
            prediction = self._prediction_engine.predict(zone_history)

            readings.append(reading_schema)
            assessments.append(assessment_pydantic)
            predictions.append(prediction)

        return self._intelligence_service.aggregate(event_id, readings, assessments, predictions, active_incidents=active_incidents)
