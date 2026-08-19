"""
Risk Engine implementation.

Extracts normalized risk features from a CrowdReading, computes a
weighted composite risk score, and determines the categorical risk
level and dominant risk type.

Design principles:
- Deterministic, stateless execution for feature extraction, but state-aware transition.
- Explainable outputs: returns all component scores alongside the final result.
- Handles raw inputs safely (clamps invalid negative values where appropriate).
"""

from typing import Union, List, Optional
from datetime import datetime, timezone

from app.schemas.crowd_reading import CrowdReadingCreate, CrowdReadingResponse
from app.ai.risk_engine.models import (
    RiskAssessment,
    RiskFeatures,
    RiskLevel,
    RiskType,
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_MEDIUM,
    RISK_THRESHOLD_HIGH,
    RISK_RECOVERY_LOW,
    RISK_RECOVERY_MEDIUM,
    RISK_RECOVERY_HIGH,
    WEIGHT_DENSITY,
    WEIGHT_GROWTH,
    WEIGHT_MOVEMENT_CONFLICT,
    WEIGHT_SPEED_REDUCTION,
    MAX_GROWTH_RATE_REFERENCE,
    MAX_FREE_FLOW_SPEED_REFERENCE,
    DENSITY_RISK_HIGH_THRESHOLD,
    CONGESTION_RISK_THRESHOLD,
    CROWD_CRUSH_DENSITY_THRESHOLD,
    CROWD_CRUSH_SPEED_THRESHOLD,
)


class RiskEngine:
    """
    Evaluator for crowd risk conditions.
    """

    def evaluate(
        self,
        reading: Union[CrowdReadingCreate, CrowdReadingResponse],
        history: List[RiskAssessment] = None
    ) -> RiskAssessment:
        """
        Evaluate a single crowd reading and produce a full RiskAssessment.

        Args:
            reading: Validated crowd measurement data (either the create payload
                     or the persisted DB response).
            history: Recent risk assessments for the same zone (most recent first).

        Returns:
            RiskAssessment object containing score, level, type, and explainability features.
        """
        history = history or []

        # 1. Extract and normalize features
        features = self._extract_features(reading)

        # 2. Compute composite score
        score = self._compute_composite_score(features)

        # 3. Classify risk type
        risk_type = self._classify_type(reading, features, score)

        # 4. Count active severe signals
        active_signals_count = self._count_active_signals(reading, features, score)

        # 5. Compute persistence
        persistence_count, persistence_duration = self._compute_persistence(
            score, active_signals_count, history, reading.timestamp
        )

        # 6. Determine risk level with hysteresis and multi-signal confirmation
        previous_level = history[0].level if history else RiskLevel.LOW
        level = self._determine_level(
            score, active_signals_count, persistence_count, previous_level
        )

        # 7. Build explainability payload
        explanation = self._build_explanation(
            score, level, risk_type, features, active_signals_count, persistence_count, persistence_duration, previous_level
        )

        return RiskAssessment(
            score=round(score, 2),
            level=level,
            risk_type=risk_type,
            features=features,
            explanation=explanation,
            active_signals_count=active_signals_count,
            persistence_count=persistence_count,
            persistence_duration_seconds=persistence_duration,
            event_id=reading.event_id,
            zone_id=reading.zone_id,
            source_timestamp=reading.timestamp.isoformat(),
        )

    # ------------------------------------------------------------------
    # 1. Feature Extraction & Normalization
    # ------------------------------------------------------------------

    def _extract_features(self, reading: Union[CrowdReadingCreate, CrowdReadingResponse]) -> RiskFeatures:
        # A. Density risk: directly use density_percent (already 0-100)
        density_risk = max(0.0, min(100.0, reading.density_percent))

        # B. Growth risk: map growth rate (0 -> 0, MAX_GROWTH_RATE -> 100)
        raw_growth = reading.crowd_growth_rate if reading.crowd_growth_rate is not None else 0.0
        growth_risk = 0.0
        if raw_growth > 0:
            growth_risk = (raw_growth / MAX_GROWTH_RATE_REFERENCE) * 100.0
        growth_risk = max(0.0, min(100.0, growth_risk))

        # C. Movement conflict risk
        movement_conflict_risk = 100.0 if reading.reverse_flow_indicator else 0.0

        # D. Speed reduction risk
        speed = max(0.0, reading.average_speed)
        if speed >= MAX_FREE_FLOW_SPEED_REFERENCE:
            speed_reduction_risk = 0.0
        else:
            speed_deficit = MAX_FREE_FLOW_SPEED_REFERENCE - speed
            speed_reduction_risk = (speed_deficit / MAX_FREE_FLOW_SPEED_REFERENCE) * 100.0
        speed_reduction_risk = max(0.0, min(100.0, speed_reduction_risk))

        # E. Boolean signals
        congestion_signal = reading.congestion_score >= CONGESTION_RISK_THRESHOLD

        return RiskFeatures(
            density_risk=round(density_risk, 2),
            growth_risk=round(growth_risk, 2),
            movement_conflict_risk=round(movement_conflict_risk, 2),
            speed_reduction_risk=round(speed_reduction_risk, 2),
            surge_signal=reading.surge_indicator,
            reverse_flow_signal=reading.reverse_flow_indicator,
            bottleneck_signal=reading.bottleneck_indicator,
            congestion_signal=congestion_signal,
        )

    # ------------------------------------------------------------------
    # 2. Score Calculation
    # ------------------------------------------------------------------

    def _compute_composite_score(self, features: RiskFeatures) -> float:
        score = (
            features.density_risk * WEIGHT_DENSITY
            + features.growth_risk * WEIGHT_GROWTH
            + features.movement_conflict_risk * WEIGHT_MOVEMENT_CONFLICT
            + features.speed_reduction_risk * WEIGHT_SPEED_REDUCTION
        )
        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # 3. Type Classification
    # ------------------------------------------------------------------

    def _classify_type(
        self,
        reading: Union[CrowdReadingCreate, CrowdReadingResponse],
        features: RiskFeatures,
        score: float,
    ) -> RiskType:
        if (
            reading.density_percent >= CROWD_CRUSH_DENSITY_THRESHOLD
            and reading.average_speed <= CROWD_CRUSH_SPEED_THRESHOLD
        ):
            return RiskType.CROWD_CRUSH
        if features.bottleneck_signal:
            return RiskType.BOTTLENECK
        if features.surge_signal:
            return RiskType.CROWD_SURGE
        if features.reverse_flow_signal:
            return RiskType.REVERSE_FLOW
        if reading.density_percent >= DENSITY_RISK_HIGH_THRESHOLD:
            return RiskType.HIGH_DENSITY
        if features.congestion_signal:
            return RiskType.CONGESTION
        if score > RISK_THRESHOLD_LOW:
            return RiskType.MOVEMENT_ANOMALY
        return RiskType.STABLE

    # ------------------------------------------------------------------
    # 4. Multi-Signal Confirmation
    # ------------------------------------------------------------------

    def _count_active_signals(self, reading: Union[CrowdReadingCreate, CrowdReadingResponse], features: RiskFeatures, score: float) -> int:
        """
        Count the number of active severe signals indicating crowd danger.
        """
        count = 0
        if reading.density_percent >= DENSITY_RISK_HIGH_THRESHOLD:
            count += 1
        if features.speed_reduction_risk > 50.0:
            count += 1
        if features.surge_signal:
            count += 1
        if features.reverse_flow_signal:
            count += 1
        if features.bottleneck_signal:
            count += 1
        return count

    def _compute_persistence(
        self,
        score: float,
        active_signals_count: int,
        history: List[RiskAssessment],
        current_timestamp: datetime
    ) -> tuple[int, Optional[float]]:
        """
        Calculates how long a dangerous condition has persisted.
        A condition is considered dangerous if score >= 60 OR active_signals >= 1.
        Returns: (consecutive_dangerous_readings, duration_in_seconds)
        """
        is_dangerous = score >= RISK_THRESHOLD_MEDIUM or active_signals_count >= 1
        
        if not is_dangerous:
            return 0, 0.0

        count = 1
        oldest_dangerous_time = current_timestamp

        for record in history:
            record_is_dangerous = record.score >= RISK_THRESHOLD_MEDIUM or record.active_signals_count >= 1
            if record_is_dangerous:
                count += 1
                try:
                    if record.source_timestamp:
                        # Assumes UTC isoformat
                        oldest_dangerous_time = datetime.fromisoformat(record.source_timestamp.replace('Z', '+00:00'))
                except ValueError:
                    pass
            else:
                break
                
        duration = (current_timestamp - oldest_dangerous_time).total_seconds()
        return count, max(0.0, duration)

    # ------------------------------------------------------------------
    # 5. Level Mapping (Hysteresis & Confirmation)
    # ------------------------------------------------------------------

    def _determine_level(
        self, score: float, active_signals_count: int, persistence_count: int, previous_level: RiskLevel
    ) -> RiskLevel:
        """
        Determine the risk level using state-aware hysteresis and multi-signal confirmation.
        
        CRITICAL escalation requires multiple signals OR persistence, allowing rapid
        deterioration to escalate immediately without waiting 3 readings.
        """
        # 1. Evaluate CRITICAL
        can_be_critical = score >= RISK_THRESHOLD_HIGH and (active_signals_count >= 2 or persistence_count >= 3)
        if previous_level == RiskLevel.CRITICAL and score >= RISK_RECOVERY_HIGH:
            return RiskLevel.CRITICAL
        if can_be_critical:
            return RiskLevel.CRITICAL
            
        # 2. Evaluate HIGH
        can_be_high = score >= RISK_THRESHOLD_MEDIUM and (active_signals_count >= 1 or persistence_count >= 2)
        if previous_level in (RiskLevel.CRITICAL, RiskLevel.HIGH) and score >= RISK_RECOVERY_MEDIUM:
            return RiskLevel.HIGH
        if can_be_high:
            return RiskLevel.HIGH
            
        # 3. Evaluate MEDIUM
        can_be_medium = score >= RISK_THRESHOLD_LOW
        if previous_level in (RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM) and score >= RISK_RECOVERY_LOW:
            return RiskLevel.MEDIUM
        if can_be_medium:
            return RiskLevel.MEDIUM
            
        return RiskLevel.LOW

    # ------------------------------------------------------------------
    # 6. Explainability
    # ------------------------------------------------------------------

    def _build_explanation(
        self,
        score: float,
        level: RiskLevel,
        risk_type: RiskType,
        features: RiskFeatures,
        active_signals_count: int,
        persistence_count: int,
        persistence_duration: Optional[float],
        previous_level: RiskLevel
    ) -> str:
        lines = [
            f"Risk Score: {score:.2f} ({level.value})",
            f"Dominant Condition: {risk_type.value}",
            "Contributing factors (normalized 0-100):",
            f" - Density Risk: {features.density_risk:.1f}",
            f" - Growth Risk: {features.growth_risk:.1f}",
            f" - Movement Conflict Risk: {features.movement_conflict_risk:.1f}",
            f" - Speed Reduction Risk: {features.speed_reduction_risk:.1f}",
        ]

        active_signals = []
        if features.density_risk >= DENSITY_RISK_HIGH_THRESHOLD:
            active_signals.append("High Density")
        if features.speed_reduction_risk > 50.0:
            active_signals.append("Speed Degradation")
        if features.surge_signal:
            active_signals.append("Crowd Surge")
        if features.reverse_flow_signal:
            active_signals.append("Flow Conflict")
        if features.bottleneck_signal:
            active_signals.append("Bottleneck")

        if active_signals:
            lines.append(f"Active Severe Signals ({active_signals_count}): {', '.join(active_signals)}")
        
        if persistence_count > 0:
            lines.append(f"Persistence: {persistence_count} consecutive dangerous readings (~{persistence_duration:.1f}s)")
            
        if previous_level != level:
            lines.append(f"State Transition: Changed from {previous_level.value} to {level.value}")
        elif level != RiskLevel.LOW:
            lines.append(f"State Transition: Maintained at {level.value} due to hysteresis/persistence")

        return "\n".join(lines)
