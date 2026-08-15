"""
Risk Engine implementation.

Extracts normalized risk features from a CrowdReading, computes a
weighted composite risk score, and determines the categorical risk
level and dominant risk type.

Design principles:
- Deterministic, stateless execution.
- Explainable outputs: returns all component scores alongside the final result.
- Handles raw inputs safely (clamps invalid negative values where appropriate).
"""

from typing import Union

from app.schemas.crowd_reading import CrowdReadingCreate, CrowdReadingResponse
from app.ai.risk_engine.models import (
    RiskAssessment,
    RiskFeatures,
    RiskLevel,
    RiskType,
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_MEDIUM,
    RISK_THRESHOLD_HIGH,
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
    Stateless evaluator for crowd risk conditions.
    """

    def evaluate(self, reading: Union[CrowdReadingCreate, CrowdReadingResponse]) -> RiskAssessment:
        """
        Evaluate a single crowd reading and produce a full RiskAssessment.

        Args:
            reading: Validated crowd measurement data (either the create payload
                     or the persisted DB response).

        Returns:
            RiskAssessment object containing score, level, type, and explainability features.
        """
        # 1. Extract and normalize features
        features = self._extract_features(reading)

        # 2. Compute composite score
        score = self._compute_composite_score(features)

        # 3. Determine risk level
        level = self._determine_level(score)

        # 4. Classify risk type
        risk_type = self._classify_type(reading, features, score)

        # 5. Build explainability payload
        explanation = self._build_explanation(score, level, risk_type, features)

        return RiskAssessment(
            score=round(score, 2),
            level=level,
            risk_type=risk_type,
            features=features,
            explanation=explanation,
            event_id=reading.event_id,
            zone_id=reading.zone_id,
            source_timestamp=reading.timestamp.isoformat(),
        )

    # ------------------------------------------------------------------
    # 1. Feature Extraction & Normalization
    # ------------------------------------------------------------------

    def _extract_features(self, reading: Union[CrowdReadingCreate, CrowdReadingResponse]) -> RiskFeatures:
        """
        Extract and normalize risk features onto a 0–100 scale.
        """
        # A. Density risk: directly use density_percent (already 0-100)
        density_risk = max(0.0, min(100.0, reading.density_percent))

        # B. Growth risk: map growth rate (0 -> 0, MAX_GROWTH_RATE -> 100)
        # Negative growth (dispersion) contributes 0 risk.
        raw_growth = reading.crowd_growth_rate if reading.crowd_growth_rate is not None else 0.0
        growth_risk = 0.0
        if raw_growth > 0:
            growth_risk = (raw_growth / MAX_GROWTH_RATE_REFERENCE) * 100.0
        growth_risk = max(0.0, min(100.0, growth_risk))

        # C. Movement conflict risk
        # For now, it's a binary 0 or 100 based on the CONFLICTED direction.
        # Future enhancement: could scale if vision pipeline provided a conflict intensity.
        movement_conflict_risk = 100.0 if reading.reverse_flow_indicator else 0.0

        # D. Speed reduction risk
        # 0 when at or above MAX_FREE_FLOW (fast), 100 when stationary (0 m/s)
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
        """
        Compute the weighted composite risk score (0-100).
        """
        score = (
            features.density_risk * WEIGHT_DENSITY
            + features.growth_risk * WEIGHT_GROWTH
            + features.movement_conflict_risk * WEIGHT_MOVEMENT_CONFLICT
            + features.speed_reduction_risk * WEIGHT_SPEED_REDUCTION
        )
        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # 3. Level Mapping
    # ------------------------------------------------------------------

    def _determine_level(self, score: float) -> RiskLevel:
        """
        Map a numeric score to a categorical risk level.
        """
        if score <= RISK_THRESHOLD_LOW:
            return RiskLevel.LOW
        if score <= RISK_THRESHOLD_MEDIUM:
            return RiskLevel.MEDIUM
        if score <= RISK_THRESHOLD_HIGH:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    # ------------------------------------------------------------------
    # 4. Type Classification
    # ------------------------------------------------------------------

    def _classify_type(
        self,
        reading: Union[CrowdReadingCreate, CrowdReadingResponse],
        features: RiskFeatures,
        score: float,
    ) -> RiskType:
        """
        Determine the dominant risk condition.

        Evaluated in order of descending severity / specific patterns.
        """
        # 1. CROWD_CRUSH: The most severe condition (high density + virtually no movement)
        if (
            reading.density_percent >= CROWD_CRUSH_DENSITY_THRESHOLD
            and reading.average_speed <= CROWD_CRUSH_SPEED_THRESHOLD
        ):
            return RiskType.CROWD_CRUSH

        # 2. BOTTLENECK: Detected structurally by the vision/metrics layer
        if features.bottleneck_signal:
            return RiskType.BOTTLENECK

        # 3. CROWD_SURGE: Rapid influx dominates the current risk profile
        if features.surge_signal:
            return RiskType.CROWD_SURGE

        # 4. REVERSE_FLOW: Opposing streams
        if features.reverse_flow_signal:
            return RiskType.REVERSE_FLOW

        # 5. HIGH_DENSITY: Heavy load but still moving / no crush yet
        if reading.density_percent >= DENSITY_RISK_HIGH_THRESHOLD:
            return RiskType.HIGH_DENSITY

        # 6. CONGESTION: General elevated congestion without specific critical markers
        if features.congestion_signal:
            return RiskType.CONGESTION

        # 7. MOVEMENT_ANOMALY: Moderate score but doesn't fit standard density/congestion profiles
        if score > RISK_THRESHOLD_LOW:
            return RiskType.MOVEMENT_ANOMALY

        # 8. STABLE: Default normal condition
        return RiskType.STABLE

    # ------------------------------------------------------------------
    # 5. Explainability
    # ------------------------------------------------------------------

    def _build_explanation(
        self,
        score: float,
        level: RiskLevel,
        risk_type: RiskType,
        features: RiskFeatures,
    ) -> str:
        """
        Build a human-readable explanation of why the score was assigned.
        """
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
        if features.surge_signal:
            active_signals.append("Surge")
        if features.reverse_flow_signal:
            active_signals.append("Reverse Flow")
        if features.bottleneck_signal:
            active_signals.append("Bottleneck")

        if active_signals:
            lines.append(f"Active Danger Signals: {', '.join(active_signals)}")

        return "\n".join(lines)
