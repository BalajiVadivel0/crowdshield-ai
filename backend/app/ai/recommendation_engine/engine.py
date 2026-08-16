"""
Recommendation Engine implementation.

Evaluates an EventCrowdIntelligence snapshot and produces a prioritised,
deduplicated list of intervention Recommendations for event safety authorities.

Design principles:
- Deterministic, stateless execution — same input always produces same output.
- Explainable: every recommendation carries a human-readable reason and a
  list of structured TriggeringCondition objects (one per active signal).
- Transparent rule table: each rule is a named method; no logic buried in loops.
- Deduplication: same (zone_id, action_type) pair → keep highest-priority entry.
  Within same priority → keep entry with more triggering conditions, then higher
  confidence. Tie-break is deterministic.
- Ranking: CRITICAL first, then HIGH, MEDIUM, LOW. Within same priority:
  confidence descending → risk score descending → zone_id ascending (None last)
  → action_type deterministic order.
- Authority gate: requires_authority_approval is always True.
  This engine NEVER executes physical actions.
- Event-level propagation recommendations use zone_id=None (never a fabricated int).

DO NOT modify Member 1 modules:
    app/ai/risk_engine/
    app/ai/prediction_engine/
    app/ai/simulation/
    app/ai/vision/
    app/services/crowd_intelligence_service.py
    app/services/crowd_metrics_service.py
    app/schemas/crowd_reading.py
    app/schemas/crowd_intelligence.py
"""

from typing import List, Optional, Tuple

from app.ai.prediction_engine.models import TrendDirection
from app.ai.recommendation_engine.models import (
    ACTION_TYPE_ORDER,
    CONFIDENCE_FLOOR,
    CONFIDENCE_HIGH_PREDICTION_BOOST,
    CONFIDENCE_HIGH_PREDICTION_THRESHOLD,
    CONFIDENCE_IMMINENT_BOOST,
    CONFIDENCE_IMMINENT_THRESHOLD_MINUTES,
    CONFIDENCE_WORSENING_BOOST,
    CRUSH_DENSITY_THRESHOLD,
    CRUSH_SPEED_THRESHOLD,
    ActionType,
    PRIORITY_RANK,
    Recommendation,
    RecommendationPriority,
    TriggeringCondition,
)
from app.ai.risk_engine.models import RiskLevel, RiskType
from app.schemas.crowd_intelligence import EventCrowdIntelligence, PropagationStatus, ZoneSummary


class RecommendationEngine:
    """
    Deterministic, stateless rule engine that translates crowd intelligence
    into prioritised intervention recommendations.

    Usage::

        engine = RecommendationEngine()
        recommendations = engine.recommend(intelligence)

    The engine evaluates each zone in the EventCrowdIntelligence snapshot
    and applies a fixed set of named rules. All outputs are deduplicated so
    that authorities receive exactly one recommendation per (zone, action_type)
    pair — always the highest-priority one.

    Event-level propagation rules use zone_id=None (not a fabricated integer)
    because they address cross-zone risk without targeting a single zone.
    """

    def recommend(self, intelligence: EventCrowdIntelligence) -> List[Recommendation]:
        """
        Produce a prioritised, deduplicated list of intervention recommendations.

        Args:
            intelligence: The event-level crowd intelligence snapshot produced
                          by CrowdIntelligenceService.aggregate(). Not mutated.

        Returns:
            List of Recommendation objects sorted by deterministic urgency order:
            CRITICAL → HIGH → MEDIUM → LOW. Within same priority: confidence
            descending → risk score descending → zone_id ascending (None last)
            → action_type deterministic order.
        """
        raw: List[Recommendation] = []

        for zone in intelligence.zone_summaries:
            raw.extend(self._evaluate_zone(zone, intelligence))

        # Apply event-wide propagation rules (cross-zone; zone_id=None)
        raw.extend(self._evaluate_propagation(intelligence))

        # Deduplicate: keep best per (zone_id, action_type)
        deduplicated = self._deduplicate(raw)

        # Sort deterministically
        deduplicated.sort(key=self._sort_key)

        return deduplicated

    # ------------------------------------------------------------------
    # Zone-level rule dispatch
    # ------------------------------------------------------------------

    def _evaluate_zone(
        self,
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
    ) -> List[Recommendation]:
        """
        Apply all applicable rules for a single zone and collect recommendations.

        Rule evaluation is independent — a zone may trigger multiple rules
        simultaneously (e.g., both surge and reverse flow). All generated
        recommendations are collected; deduplication runs afterwards.
        """
        results: List[Recommendation] = []

        # Rule A: CRITICAL + high density + low speed → crush prevention
        if self._is_crush_condition(zone):
            results.extend(self._rule_crush_prevention(zone, intelligence))

        # Rule B: Crowd surge active
        if zone.surge_active:
            results.extend(self._rule_crowd_surge(zone, intelligence))

        # Rule C: Reverse flow active
        if zone.reverse_flow_active:
            results.extend(self._rule_reverse_flow(zone, intelligence))

        # Rule D: Bottleneck active
        if zone.bottleneck_active:
            results.extend(self._rule_bottleneck(zone, intelligence))

        # Rule E: HIGH_DENSITY type (not already crush — that's handled above)
        if (
            zone.current_risk_type == RiskType.HIGH_DENSITY
            and not self._is_crush_condition(zone)
        ):
            results.extend(self._rule_high_density(zone, intelligence))

        # Rule G: No special danger signal — baseline MONITOR_ZONE for every zone
        # that has no active danger indicators. Also runs for elevated zones
        # (MONITOR_ZONE is then at a higher priority than LOW).
        results.extend(self._rule_no_special_signal(zone, intelligence))

        return results

    # ------------------------------------------------------------------
    # Event-level propagation rule
    # ------------------------------------------------------------------

    def _evaluate_propagation(
        self, intelligence: EventCrowdIntelligence
    ) -> List[Recommendation]:
        """
        Apply cross-zone risk propagation rules (Rule F).

        Fires when RISK_PROPAGATION_DETECTED is in event_flags OR
        propagation_status is ELEVATED or SEVERE.

        All resulting recommendations use zone_id=None — they are event-wide
        and must NEVER be assigned a fabricated zone identifier.
        """
        is_propagating = (
            "RISK_PROPAGATION_DETECTED" in intelligence.event_flags
            or intelligence.propagation_status
            in (PropagationStatus.ELEVATED, PropagationStatus.SEVERE)
        )

        if not is_propagating:
            return []

        return self._rule_risk_propagation(intelligence)

    # ------------------------------------------------------------------
    # Condition helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_crush_condition(zone: ZoneSummary) -> bool:
        """
        True when the zone exhibits conditions consistent with an imminent crowd crush:
        CRITICAL risk level, density at or above the crush threshold, and speed
        at or below the crush speed threshold.

        Thresholds come from centralized constants — no magic numbers here.
        """
        return (
            zone.current_level == RiskLevel.CRITICAL
            and zone.density_percent >= CRUSH_DENSITY_THRESHOLD
            and zone.average_speed <= CRUSH_SPEED_THRESHOLD
        )

    @staticmethod
    def _has_danger_signal(zone: ZoneSummary) -> bool:
        """True when at least one active danger indicator is present in the zone."""
        return (
            zone.surge_active
            or zone.reverse_flow_active
            or zone.bottleneck_active
            or zone.current_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            or zone.current_risk_type == RiskType.HIGH_DENSITY
        )

    # ------------------------------------------------------------------
    # Named rules — Rule A through Rule G
    # ------------------------------------------------------------------

    def _rule_crush_prevention(
        self,
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
    ) -> List[Recommendation]:
        """
        Rule A — CRITICAL crowd condition.

        Triggered when a zone is CRITICAL AND density ≥ CRUSH_DENSITY_THRESHOLD
        AND speed ≤ CRUSH_SPEED_THRESHOLD.

        Actions: RESTRICT_ENTRY, OPEN_ALTERNATE_EXIT, DEPLOY_SECURITY.
        Priority: CRITICAL.
        """
        priority = RecommendationPriority.CRITICAL
        conditions = self._build_crush_conditions(zone, intelligence)
        confidence = self._compute_confidence(zone, intelligence, priority)

        reason_base = (
            f"Zone {zone.zone_id} is at CRITICAL risk with {zone.density_percent:.0f}% density "
            f"and near-stationary movement ({zone.average_speed:.2f} m/s). "
            f"Crowd crush conditions detected ({zone.current_risk_type.value})."
        )
        if zone.trend == TrendDirection.WORSENING:
            reason_base += " Conditions are actively worsening."
        if zone.time_to_critical is not None:
            reason_base += (
                f" Estimated time to critical threshold: ~{zone.time_to_critical:.0f} minutes."
            )

        return [
            Recommendation(
                recommendation_id=f"{ActionType.RESTRICT_ENTRY.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.RESTRICT_ENTRY,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Immediately restrict entry to halt additional inflow.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Stops additional crowd accumulation in the zone, reducing density "
                    "and pressure over time. May not provide immediate relief."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.OPEN_ALTERNATE_EXIT.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.OPEN_ALTERNATE_EXIT,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Open alternate exits to rapidly relieve zone pressure.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Provides additional egress pathways to enable crowd dispersal. "
                    "Effectiveness depends on exit accessibility and crowd compliance."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.DEPLOY_SECURITY.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.DEPLOY_SECURITY,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Deploy trained security personnel for immediate crowd control.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Provides on-ground authority to enforce crowd management measures "
                    "and assist persons in distress."
                ),
                affected_zones=[zone.zone_id],
            ),
        ]

    def _rule_crowd_surge(
        self,
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
    ) -> List[Recommendation]:
        """
        Rule B — Crowd surge.

        Triggered when surge_active is True.

        Actions: RESTRICT_ENTRY, REDIRECT_CROWD, ONE_WAY_FLOW.
        Priority: CRITICAL when zone is CRITICAL, otherwise HIGH.
        """
        priority = (
            RecommendationPriority.CRITICAL
            if zone.current_level == RiskLevel.CRITICAL
            else RecommendationPriority.HIGH
        )
        conditions = self._build_surge_conditions(zone, intelligence)
        confidence = self._compute_confidence(zone, intelligence, priority)

        reason_base = (
            f"Zone {zone.zone_id} is experiencing a CROWD SURGE with "
            f"{zone.density_percent:.0f}% density and active surge indicator. "
            f"Risk level: {zone.current_level.value}."
        )

        return [
            Recommendation(
                recommendation_id=f"{ActionType.RESTRICT_ENTRY.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.RESTRICT_ENTRY,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Restrict entry to limit crowd inflow during the surge.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Reduces the rate of crowd accumulation, reducing the risk of the surge "
                    "escalating into a crush condition."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.REDIRECT_CROWD.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.REDIRECT_CROWD,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Redirect incoming crowd to lower-density areas.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Distributes crowd pressure across multiple zones, reducing "
                    "over-concentration in the surging area."
                ),
                affected_zones=list(dict.fromkeys([zone.zone_id] + intelligence.priority_zones[:3])),
            ),
            Recommendation(
                recommendation_id=f"{ActionType.ONE_WAY_FLOW.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.ONE_WAY_FLOW,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Enforce one-way flow to channel the surge safely.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Prevents opposing crowd streams from forming, improving throughput "
                    "and reducing turbulence."
                ),
                affected_zones=[zone.zone_id],
            ),
        ]

    def _rule_reverse_flow(
        self,
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
    ) -> List[Recommendation]:
        """
        Rule C — Reverse flow.

        Triggered when reverse_flow_active is True.

        Actions: ONE_WAY_FLOW, REDIRECT_CROWD, BROADCAST_ANNOUNCEMENT.
        Priority: HIGH (CRITICAL if zone is already CRITICAL).
        """
        priority = (
            RecommendationPriority.CRITICAL
            if zone.current_level == RiskLevel.CRITICAL
            else RecommendationPriority.HIGH
        )
        conditions = self._build_reverse_flow_conditions(zone, intelligence)
        confidence = self._compute_confidence(zone, intelligence, priority)

        reason_base = (
            f"Zone {zone.zone_id} has CONFLICTED crowd direction — opposing streams are colliding. "
            f"Density: {zone.density_percent:.0f}%, Speed: {zone.average_speed:.2f} m/s. "
            "Reverse flow dramatically increases compressive forces and stampede risk."
        )

        return [
            Recommendation(
                recommendation_id=f"{ActionType.ONE_WAY_FLOW.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.ONE_WAY_FLOW,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Enforce one-way flow to eliminate opposing streams.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Eliminates head-on crowd collision, reducing compressive forces "
                    "and restoring safe directional movement."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.REDIRECT_CROWD.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.REDIRECT_CROWD,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Redirect one of the opposing streams to break the conflict.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Separates conflicting crowd streams into distinct paths, "
                    "eliminating the reverse-flow condition."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.BROADCAST_ANNOUNCEMENT.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.BROADCAST_ANNOUNCEMENT,
                priority=RecommendationPriority.HIGH,
                confidence=min(confidence, 0.85),
                reason=reason_base + " Use PA system to guide crowd to the correct direction.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Provides clear directional guidance, reducing confusion and supporting "
                    "the one-way flow enforcement."
                ),
                affected_zones=[zone.zone_id],
            ),
        ]

    def _rule_bottleneck(
        self,
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
    ) -> List[Recommendation]:
        """
        Rule D — Bottleneck.

        Triggered when bottleneck_active is True.

        Actions: OPEN_ALTERNATE_EXIT, REDIRECT_CROWD, CHANGE_BARRICADE.
        Priority: HIGH (CRITICAL if zone is already CRITICAL).
        """
        priority = (
            RecommendationPriority.CRITICAL
            if zone.current_level == RiskLevel.CRITICAL
            else RecommendationPriority.HIGH
        )
        conditions = self._build_bottleneck_conditions(zone, intelligence)
        confidence = self._compute_confidence(zone, intelligence, priority)

        reason_base = (
            f"Zone {zone.zone_id} has a BOTTLENECK: {zone.density_percent:.0f}% density with "
            f"critically low movement speed ({zone.average_speed:.2f} m/s). "
            "Throughput has been severely reduced, increasing compression risk."
        )

        return [
            Recommendation(
                recommendation_id=f"{ActionType.OPEN_ALTERNATE_EXIT.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.OPEN_ALTERNATE_EXIT,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Open alternate exits to relieve bottleneck pressure.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Provides additional outflow pathways, reducing density at the "
                    "bottleneck point and improving throughput."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.REDIRECT_CROWD.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.REDIRECT_CROWD,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Redirect crowd away from the bottleneck point.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Reduces the number of people approaching the bottleneck, "
                    "allowing it to drain progressively."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.CHANGE_BARRICADE.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.CHANGE_BARRICADE,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Reconfigure barriers to widen the flow path.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Increases the effective width of the passage, improving "
                    "throughput capacity and reducing the bottleneck."
                ),
                affected_zones=[zone.zone_id],
            ),
        ]

    def _rule_high_density(
        self,
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
    ) -> List[Recommendation]:
        """
        Rule E — High density (not yet at crush/bottleneck level).

        Triggered when current_risk_type is HIGH_DENSITY and no crush condition.

        Actions: RESTRICT_ENTRY, MONITOR_ZONE.
        Priority: MEDIUM; raises to HIGH when trend is WORSENING or when the
                  prediction indicates time_to_critical is near.
        """
        # Base priority MEDIUM; raise to HIGH if worsening or imminent critical
        priority = RecommendationPriority.MEDIUM
        if zone.trend == TrendDirection.WORSENING:
            priority = RecommendationPriority.HIGH
        elif (
            zone.time_to_critical is not None
            and zone.time_to_critical <= CONFIDENCE_IMMINENT_THRESHOLD_MINUTES
        ):
            priority = RecommendationPriority.HIGH

        conditions = self._build_high_density_conditions(zone, intelligence)
        confidence = self._compute_confidence(zone, intelligence, priority)

        reason_base = (
            f"Zone {zone.zone_id} has HIGH density ({zone.density_percent:.0f}%) "
            f"with a risk score of {zone.current_score:.0f}. "
        )
        if zone.trend == TrendDirection.WORSENING:
            reason_base += (
                "Conditions are actively worsening — early intervention recommended."
            )
        elif zone.time_to_critical is not None:
            reason_base += (
                f"Predicted to reach CRITICAL in approximately "
                f"{zone.time_to_critical:.0f} minutes."
            )
        else:
            reason_base += "Situation requires monitoring to prevent further escalation."

        return [
            Recommendation(
                recommendation_id=f"{ActionType.RESTRICT_ENTRY.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.RESTRICT_ENTRY,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Restrict entry to prevent further density increase.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Slows crowd accumulation, keeping density below bottleneck "
                    "and crush thresholds."
                ),
                affected_zones=[zone.zone_id],
            ),
            Recommendation(
                recommendation_id=f"{ActionType.MONITOR_ZONE.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.MONITOR_ZONE,
                priority=priority,
                confidence=confidence,
                reason=reason_base + " Maintain heightened monitoring to detect further escalation.",
                triggering_conditions=conditions,
                expected_effect=(
                    "Ensures early detection of worsening conditions so that "
                    "additional interventions can be activated before a critical threshold."
                ),
                affected_zones=[zone.zone_id],
            ),
        ]

    def _rule_no_special_signal(
        self,
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
    ) -> List[Recommendation]:
        """
        Rule G — No special danger signal.

        Applies to every zone regardless of other rules, acting as a baseline.
        For zones with no active danger indicators, this is the ONLY recommendation.
        For elevated zones, it is de-prioritised by deduplication after higher-priority
        action-specific MONITOR_ZONE recommendations are kept.

        Action: MONITOR_ZONE.
        Priority: LOW for safe zones; MEDIUM for elevated; HIGH for CRITICAL.
        """
        # Assign priority from risk level
        if zone.current_level == RiskLevel.CRITICAL:
            priority = RecommendationPriority.HIGH
        elif zone.current_level == RiskLevel.HIGH:
            priority = RecommendationPriority.MEDIUM
        elif zone.current_level == RiskLevel.MEDIUM:
            priority = RecommendationPriority.LOW
        else:
            priority = RecommendationPriority.LOW

        # Bump up one level if trend is WORSENING and priority is LOW
        if zone.trend == TrendDirection.WORSENING and priority == RecommendationPriority.LOW:
            priority = RecommendationPriority.MEDIUM

        conditions = self._build_monitor_conditions(zone, intelligence)
        confidence = self._compute_confidence(zone, intelligence, priority)

        reason = (
            f"Zone {zone.zone_id} has a risk score of {zone.current_score:.0f} "
            f"({zone.current_level.value}) with trend: {zone.trend.value}. "
            f"Density: {zone.density_percent:.0f}%, Speed: {zone.average_speed:.2f} m/s. "
            "Increase monitoring frequency to detect further escalation early."
        )
        if zone.time_to_critical is not None:
            reason += (
                f" Predicted to reach CRITICAL in approximately "
                f"{zone.time_to_critical:.0f} minutes."
            )

        return [
            Recommendation(
                recommendation_id=f"{ActionType.MONITOR_ZONE.value}_{zone.zone_id}",
                event_id=intelligence.event_id,
                zone_id=zone.zone_id,
                action_type=ActionType.MONITOR_ZONE,
                priority=priority,
                confidence=confidence,
                reason=reason,
                triggering_conditions=conditions,
                expected_effect=(
                    "Ensures early detection of worsening conditions, allowing "
                    "timely escalation before a critical threshold is crossed."
                ),
                affected_zones=[zone.zone_id],
            )
        ]

    def _rule_risk_propagation(
        self, intelligence: EventCrowdIntelligence
    ) -> List[Recommendation]:
        """
        Rule F — Risk propagation (event-wide).

        Fires when risk is spreading across multiple zones.

        Actions: REDIRECT_CROWD, OPEN_ALTERNATE_EXIT, DEPLOY_SECURITY,
                 BROADCAST_ANNOUNCEMENT.
        Zone: None — these are event-wide recommendations. No zone ID is
              fabricated; affected_zones lists the actual priority zones.
        Priority: CRITICAL for SEVERE propagation; HIGH otherwise.
        """
        priority = (
            RecommendationPriority.CRITICAL
            if intelligence.propagation_status == PropagationStatus.SEVERE
            else RecommendationPriority.HIGH
        )

        # Confidence derived from event-level signals
        base_confidence = intelligence.overall_risk_score / 100.0
        if intelligence.propagation_status == PropagationStatus.SEVERE:
            base_confidence = min(1.0, base_confidence + 0.15)

        worsening_boost = (
            CONFIDENCE_WORSENING_BOOST
            if intelligence.event_trend == TrendDirection.WORSENING
            else 0.0
        )
        floor = float(CONFIDENCE_FLOOR.get(priority.value, 0.10))
        confidence = round(max(floor, min(1.0, base_confidence + worsening_boost)), 3)

        affected = intelligence.priority_zones[:5]

        reason_base = (
            f"Risk propagation detected across the venue "
            f"(status: {intelligence.propagation_status.value}). "
            f"{intelligence.critical_zone_count} critical and "
            f"{intelligence.high_risk_zone_count} high-risk zones. "
            f"Overall event risk: {intelligence.overall_risk_score:.0f}/100 "
            f"({intelligence.overall_risk_level.value})."
        )

        # Build triggering conditions from event-level signals
        event_conditions = self._build_propagation_conditions(intelligence)

        rec_id_prefix_map = [
            (ActionType.REDIRECT_CROWD, "Redistribute crowd load across all venue zones."),
            (ActionType.OPEN_ALTERNATE_EXIT, "Open additional exits to increase total venue outflow."),
            (ActionType.DEPLOY_SECURITY, "Deploy security across zones to manage propagating risk."),
        ]

        results = []
        for action, action_reason_suffix in rec_id_prefix_map:
            results.append(
                Recommendation(
                    recommendation_id=f"{action.value}_event",
                    event_id=intelligence.event_id,
                    zone_id=None,  # event-wide — no fabricated zone
                    action_type=action,
                    priority=priority,
                    confidence=confidence,
                    reason=reason_base + " " + action_reason_suffix,
                    triggering_conditions=event_conditions,
                    expected_effect=self._propagation_effect(action),
                    affected_zones=affected,
                )
            )

        # BROADCAST_ANNOUNCEMENT is always HIGH and capped confidence
        results.append(
            Recommendation(
                recommendation_id=f"{ActionType.BROADCAST_ANNOUNCEMENT.value}_event",
                event_id=intelligence.event_id,
                zone_id=None,
                action_type=ActionType.BROADCAST_ANNOUNCEMENT,
                priority=RecommendationPriority.HIGH,
                confidence=min(confidence, 0.90),
                reason=reason_base + " Issue venue-wide announcement to guide and calm the crowd.",
                triggering_conditions=event_conditions,
                expected_effect=(
                    "Reduces panic and confusion, providing clear guidance that "
                    "facilitates orderly crowd redistribution."
                ),
                affected_zones=affected,
            )
        )

        return results

    # ------------------------------------------------------------------
    # Confidence calculation — deterministic, never random
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(
        zone: ZoneSummary,
        intelligence: EventCrowdIntelligence,
        priority: RecommendationPriority,
    ) -> float:
        """
        Compute a deterministic confidence score [0.0, 1.0].

        Confidence represents the strength of evidence for the recommendation,
        NOT the probability of preventing a disaster.

        A CRITICAL zone can still have moderate confidence if the supporting
        prediction is weak or based on few observations.

        Contributing factors (all deterministic):
        1. Current risk score / 100 — base evidence from the risk engine.
        2. +CONFIDENCE_WORSENING_BOOST if trend is WORSENING.
        3. +CONFIDENCE_IMMINENT_BOOST if time_to_critical < IMMINENT_THRESHOLD.
        4. +CONFIDENCE_HIGH_PREDICTION_BOOST if prediction confidence is high.
        5. Clamped to [priority_floor, 1.0] to prevent underconfident critical recs.
        """
        base = zone.current_score / 100.0
        trend_boost = CONFIDENCE_WORSENING_BOOST if zone.trend == TrendDirection.WORSENING else 0.0

        ttc_boost = 0.0
        if (
            zone.time_to_critical is not None
            and zone.time_to_critical < CONFIDENCE_IMMINENT_THRESHOLD_MINUTES
        ):
            ttc_boost = CONFIDENCE_IMMINENT_BOOST

        pred_boost = (
            CONFIDENCE_HIGH_PREDICTION_BOOST
            if zone.confidence >= CONFIDENCE_HIGH_PREDICTION_THRESHOLD
            else 0.0
        )

        floor = float(CONFIDENCE_FLOOR.get(priority.value, 0.10))
        raw = base + trend_boost + ttc_boost + pred_boost
        return round(max(floor, min(1.0, raw)), 3)

    # ------------------------------------------------------------------
    # TriggeringCondition builders — per-rule structured evidence lists
    # ------------------------------------------------------------------

    @staticmethod
    def _build_crush_conditions(
        zone: ZoneSummary, intelligence: EventCrowdIntelligence
    ) -> List[TriggeringCondition]:
        """Build structured conditions for Rule A (crush prevention)."""
        conds = [
            TriggeringCondition(
                signal="risk_level",
                observed_value=zone.current_level.value,
                threshold="CRITICAL",
                explanation=f"Zone {zone.zone_id} risk level is {zone.current_level.value}, "
                            "indicating imminent danger.",
            ),
            TriggeringCondition(
                signal="density_percent",
                observed_value=zone.density_percent,
                threshold=CRUSH_DENSITY_THRESHOLD,
                explanation=f"Zone density ({zone.density_percent:.0f}%) exceeds the "
                            f"{CRUSH_DENSITY_THRESHOLD:.0f}% crowd crush threshold.",
            ),
            TriggeringCondition(
                signal="average_speed",
                observed_value=zone.average_speed,
                threshold=CRUSH_SPEED_THRESHOLD,
                explanation=f"Movement speed ({zone.average_speed:.2f} m/s) is at or below "
                            f"the {CRUSH_SPEED_THRESHOLD:.2f} m/s crush speed threshold.",
            ),
        ]
        if zone.trend == TrendDirection.WORSENING:
            conds.append(TriggeringCondition(
                signal="trend",
                observed_value=zone.trend.value,
                threshold=None,
                explanation="Risk trend is WORSENING, indicating continued deterioration.",
            ))
        if zone.time_to_critical is not None:
            conds.append(TriggeringCondition(
                signal="time_to_critical_minutes",
                observed_value=zone.time_to_critical,
                threshold=CONFIDENCE_IMMINENT_THRESHOLD_MINUTES,
                explanation=f"CRITICAL risk threshold estimated in ~{zone.time_to_critical:.0f} minutes.",
            ))
        return conds

    @staticmethod
    def _build_surge_conditions(
        zone: ZoneSummary, intelligence: EventCrowdIntelligence
    ) -> List[TriggeringCondition]:
        """Build structured conditions for Rule B (crowd surge)."""
        return [
            TriggeringCondition(
                signal="surge_active",
                observed_value=True,
                threshold=None,
                explanation=f"Zone {zone.zone_id} has an active crowd surge indicator "
                            "(rapid crowd growth rate detected).",
            ),
            TriggeringCondition(
                signal="density_percent",
                observed_value=zone.density_percent,
                threshold=None,
                explanation=f"Current density is {zone.density_percent:.0f}% — surge is "
                            "compounding existing crowd load.",
            ),
            TriggeringCondition(
                signal="risk_level",
                observed_value=zone.current_level.value,
                threshold=None,
                explanation=f"Risk level is {zone.current_level.value}.",
            ),
        ]

    @staticmethod
    def _build_reverse_flow_conditions(
        zone: ZoneSummary, intelligence: EventCrowdIntelligence
    ) -> List[TriggeringCondition]:
        """Build structured conditions for Rule C (reverse flow)."""
        return [
            TriggeringCondition(
                signal="reverse_flow_active",
                observed_value=True,
                threshold=None,
                explanation=f"Zone {zone.zone_id} has opposing crowd streams "
                            "(CONFLICTED direction detected).",
            ),
            TriggeringCondition(
                signal="density_percent",
                observed_value=zone.density_percent,
                threshold=None,
                explanation=f"Density ({zone.density_percent:.0f}%) amplifies compressive "
                            "forces from opposing flow.",
            ),
            TriggeringCondition(
                signal="average_speed",
                observed_value=zone.average_speed,
                threshold=None,
                explanation=f"Movement speed ({zone.average_speed:.2f} m/s) is reduced due "
                            "to crowd stream collision.",
            ),
        ]

    @staticmethod
    def _build_bottleneck_conditions(
        zone: ZoneSummary, intelligence: EventCrowdIntelligence
    ) -> List[TriggeringCondition]:
        """Build structured conditions for Rule D (bottleneck)."""
        return [
            TriggeringCondition(
                signal="bottleneck_active",
                observed_value=True,
                threshold=None,
                explanation=f"Zone {zone.zone_id} has an active bottleneck: high density "
                            "combined with critically low throughput.",
            ),
            TriggeringCondition(
                signal="density_percent",
                observed_value=zone.density_percent,
                threshold=None,
                explanation=f"Density ({zone.density_percent:.0f}%) exceeds safe zone throughput capacity.",
            ),
            TriggeringCondition(
                signal="average_speed",
                observed_value=zone.average_speed,
                threshold=None,
                explanation=f"Speed ({zone.average_speed:.2f} m/s) indicates near-stationary flow.",
            ),
        ]

    @staticmethod
    def _build_high_density_conditions(
        zone: ZoneSummary, intelligence: EventCrowdIntelligence
    ) -> List[TriggeringCondition]:
        """Build structured conditions for Rule E (high density)."""
        conds = [
            TriggeringCondition(
                signal="risk_type",
                observed_value=zone.current_risk_type.value,
                threshold="HIGH_DENSITY",
                explanation=f"Zone {zone.zone_id} dominant risk type is HIGH_DENSITY.",
            ),
            TriggeringCondition(
                signal="density_percent",
                observed_value=zone.density_percent,
                threshold=None,
                explanation=f"Density is {zone.density_percent:.0f}%, approaching dangerous levels.",
            ),
        ]
        if zone.trend == TrendDirection.WORSENING:
            conds.append(TriggeringCondition(
                signal="trend",
                observed_value=zone.trend.value,
                threshold=None,
                explanation="Risk trend is WORSENING — density is increasing.",
            ))
        return conds

    @staticmethod
    def _build_monitor_conditions(
        zone: ZoneSummary, intelligence: EventCrowdIntelligence
    ) -> List[TriggeringCondition]:
        """Build structured conditions for Rule G (monitor / no special signal)."""
        return [
            TriggeringCondition(
                signal="risk_score",
                observed_value=zone.current_score,
                threshold=None,
                explanation=f"Zone {zone.zone_id} current risk score is {zone.current_score:.0f} "
                            f"({zone.current_level.value}).",
            ),
            TriggeringCondition(
                signal="trend",
                observed_value=zone.trend.value,
                threshold=None,
                explanation=f"Crowd trend: {zone.trend.value}.",
            ),
        ]

    @staticmethod
    def _build_propagation_conditions(
        intelligence: EventCrowdIntelligence,
    ) -> List[TriggeringCondition]:
        """Build structured conditions for Rule F (risk propagation)."""
        conds = [
            TriggeringCondition(
                signal="propagation_status",
                observed_value=intelligence.propagation_status.value,
                threshold="DEVELOPING",
                explanation=f"Venue propagation status is {intelligence.propagation_status.value} "
                            "— risk is spreading across zones.",
            ),
            TriggeringCondition(
                signal="critical_zone_count",
                observed_value=intelligence.critical_zone_count,
                threshold=1,
                explanation=f"{intelligence.critical_zone_count} zone(s) are at CRITICAL risk level.",
            ),
            TriggeringCondition(
                signal="overall_risk_score",
                observed_value=intelligence.overall_risk_score,
                threshold=None,
                explanation=f"Event-wide risk score: {intelligence.overall_risk_score:.0f}/100 "
                            f"({intelligence.overall_risk_level.value}).",
            ),
        ]
        if "RISK_PROPAGATION_DETECTED" in intelligence.event_flags:
            conds.append(TriggeringCondition(
                signal="event_flag",
                observed_value="RISK_PROPAGATION_DETECTED",
                threshold=None,
                explanation="System flagged active risk propagation across venue zones.",
            ))
        return conds

    @staticmethod
    def _propagation_effect(action: ActionType) -> str:
        """Return the expected effect string for a given propagation action."""
        effects = {
            ActionType.REDIRECT_CROWD: (
                "Reduces load concentration in the highest-risk zones by "
                "redistributing people to safer areas of the venue."
            ),
            ActionType.OPEN_ALTERNATE_EXIT: (
                "Increases total venue egress capacity, enabling faster crowd "
                "dispersal across all affected zones."
            ),
            ActionType.DEPLOY_SECURITY: (
                "Provides on-ground authority and crowd management capacity "
                "at all high-risk zones simultaneously."
            ),
        }
        return effects.get(
            action,
            "Supports crowd management efforts during the propagation event.",
        )

    # ------------------------------------------------------------------
    # Deduplication — keep best per (zone_id, action_type)
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(recommendations: List[Recommendation]) -> List[Recommendation]:
        """
        Remove duplicate (zone_id, action_type) pairs.

        Resolution order (all deterministic):
        1. Lower PRIORITY_RANK wins (CRITICAL > HIGH > MEDIUM > LOW).
        2. Tie on priority → more triggering_conditions wins (stronger evidence).
        3. Tie on evidence count → higher confidence wins.
        4. Tie on confidence → keep the first occurrence (input order is stable).

        Event-level recommendations use key=(None, action_type).
        """
        best: dict[Tuple, Recommendation] = {}

        for rec in recommendations:
            key = (rec.zone_id, rec.action_type)
            if key not in best:
                best[key] = rec
                continue

            existing = best[key]
            existing_rank = PRIORITY_RANK[existing.priority]
            candidate_rank = PRIORITY_RANK[rec.priority]

            if candidate_rank < existing_rank:
                best[key] = rec
            elif candidate_rank == existing_rank:
                # Same priority: prefer more evidence
                existing_evidence = len(existing.triggering_conditions)
                candidate_evidence = len(rec.triggering_conditions)
                if candidate_evidence > existing_evidence:
                    best[key] = rec
                elif candidate_evidence == existing_evidence:
                    # Same evidence count: prefer higher confidence
                    if rec.confidence > existing.confidence:
                        best[key] = rec
                    # Equal confidence: keep existing (stable / deterministic)

        return list(best.values())

    # ------------------------------------------------------------------
    # Sorting key — deterministic urgency ordering
    # ------------------------------------------------------------------

    @staticmethod
    def _sort_key(rec: Recommendation) -> Tuple:
        """
        Deterministic sort key for recommendations.

        Order:
        1. Priority rank ascending (CRITICAL=0 first).
        2. Confidence descending (higher confidence first).
        3. (Proxy) urgency — currently represented by triggering_conditions count desc.
        4. zone_id ascending (None sorted last via a sentinel value).
        5. action_type deterministic order (ACTION_TYPE_ORDER).
        """
        priority_rank = PRIORITY_RANK[rec.priority]
        confidence_desc = -rec.confidence  # negate for descending sort
        evidence_desc = -len(rec.triggering_conditions)
        zone_sort = rec.zone_id if rec.zone_id is not None else 999_999  # None sorts last
        action_rank = ACTION_TYPE_ORDER.get(rec.action_type, 99)

        return (priority_rank, confidence_desc, evidence_desc, zone_sort, action_rank)
