"""
Tests for the RecommendationEngine.

Tests:
 1.  Normal zone — no danger signals → MONITOR_ZONE only
 2.  Critical high-density low-speed → crush prevention actions
 3.  Crowd surge → RESTRICT_ENTRY, REDIRECT_CROWD, ONE_WAY_FLOW
 4.  Reverse flow → ONE_WAY_FLOW, REDIRECT_CROWD, BROADCAST_ANNOUNCEMENT
 5.  Bottleneck → OPEN_ALTERNATE_EXIT, REDIRECT_CROWD, CHANGE_BARRICADE
 6.  High density risk type → RESTRICT_ENTRY + MONITOR_ZONE at MEDIUM/HIGH
 7.  Risk propagation (event-level) → event-wide actions, zone_id=None
 8.  No special signals → MONITOR_ZONE at LOW priority
 9.  Priority escalation (WORSENING trend + high density → HIGH priority)
10.  Confidence calculation — components are additive and deterministic
11.  Confidence clamping — must stay within [0.10, 1.00]
12.  Deduplication — same (zone_id, action_type) → keep highest priority
13.  Deterministic ranking — CRITICAL before HIGH before MEDIUM before LOW
14.  Explainability — reason and triggering_conditions are populated
15.  Authority approval flag — always True
16.  Event-level propagation — zone_id is None, NOT a fabricated integer
17.  Real EventCrowdIntelligence integration test (from fixtures)
18.  Full end-to-end integration: Simulation→Risk→Prediction→Intelligence→Recommendation
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest

from app.ai.prediction_engine.engine import PredictionEngine
from app.ai.prediction_engine.models import (
    ForecastPoint,
    PredictionResult,
    TrendDirection,
)
from app.ai.recommendation_engine.engine import RecommendationEngine
from app.ai.recommendation_engine.models import (
    ActionType,
    PRIORITY_RANK,
    Recommendation,
    RecommendationPriority,
    TriggeringCondition,
)
from app.ai.risk_engine.engine import RiskEngine
from app.ai.risk_engine.models import RiskAssessment, RiskFeatures, RiskLevel, RiskType
from app.ai.simulation.scenarios import ScenarioType
from app.ai.simulation.service import CrowdSimulationService
from app.schemas.crowd_intelligence import (
    EventCrowdIntelligence,
    PropagationStatus,
    ZoneSummary,
)
from app.schemas.crowd_reading import CrowdReadingCreate
from app.services.crowd_intelligence_service import CrowdIntelligenceService


# ===========================================================================
# Shared helpers
# ===========================================================================


def _make_zone(
    zone_id: int,
    score: float,
    level: RiskLevel,
    risk_type: RiskType,
    density: float,
    speed: float,
    *,
    congestion: float = 0.0,
    surge: bool = False,
    reverse_flow: bool = False,
    bottleneck: bool = False,
    trend: TrendDirection = TrendDirection.STABLE,
    confidence: float = 75.0,
    time_to_critical: Optional[float] = None,
    pred_5m: float = 0.0,
    pred_10m: float = 0.0,
    pred_15m: float = 0.0,
) -> ZoneSummary:
    return ZoneSummary(
        zone_id=zone_id,
        current_score=score,
        current_level=level,
        current_risk_type=risk_type,
        person_count=int(density * 5),
        density_percent=density,
        average_speed=speed,
        congestion_score=congestion,
        surge_active=surge,
        reverse_flow_active=reverse_flow,
        bottleneck_active=bottleneck,
        trend=trend,
        confidence=confidence,
        predicted_5m_score=pred_5m,
        predicted_10m_score=pred_10m,
        predicted_15m_score=pred_15m,
        time_to_critical=time_to_critical,
        urgency_score=score + (10.0 if trend == TrendDirection.WORSENING else 0.0),
    )


def _make_intel(
    event_id: int,
    zones: List[ZoneSummary],
    overall_score: float,
    overall_level: RiskLevel,
    *,
    event_trend: TrendDirection = TrendDirection.STABLE,
    propagation: PropagationStatus = PropagationStatus.NONE,
    event_flags: Optional[List[str]] = None,
) -> EventCrowdIntelligence:
    flags = event_flags or []
    return EventCrowdIntelligence(
        event_id=event_id,
        generated_at=datetime.now(timezone.utc),
        overall_risk_score=overall_score,
        overall_risk_level=overall_level,
        event_trend=event_trend,
        highest_risk_zone=zones[0].zone_id if zones else None,
        highest_risk_type=zones[0].current_risk_type if zones else None,
        total_people=sum(z.person_count for z in zones),
        average_density=sum(z.density_percent for z in zones) / max(len(zones), 1),
        highest_density=max((z.density_percent for z in zones), default=0.0),
        average_speed=sum(z.average_speed for z in zones) / max(len(zones), 1),
        congestion_zone_count=sum(1 for z in zones if z.congestion_score >= 70),
        critical_zone_count=sum(1 for z in zones if z.current_level == RiskLevel.CRITICAL),
        high_risk_zone_count=sum(1 for z in zones if z.current_level == RiskLevel.HIGH),
        worsening_zone_count=sum(1 for z in zones if z.trend == TrendDirection.WORSENING),
        propagation_status=propagation,
        event_flags=flags,
        zone_summaries=zones,
        priority_zones=[z.zone_id for z in zones],
    )


def _zone_actions(recs: List[Recommendation], zone_id: Optional[int]) -> List[ActionType]:
    return [r.action_type for r in recs if r.zone_id == zone_id]


@pytest.fixture
def engine() -> RecommendationEngine:
    return RecommendationEngine()


# ===========================================================================
# Test 1 — Normal zone, no danger signals
# ===========================================================================


def test_1_normal_zone_produces_only_monitor(engine):
    """A stable LOW zone with no danger signals should produce MONITOR_ZONE at LOW priority."""
    zone = _make_zone(1, 12.0, RiskLevel.LOW, RiskType.STABLE, 18.0, 1.5)
    intel = _make_intel(1, [zone], 12.0, RiskLevel.LOW)

    recs = engine.recommend(intel)

    # Only MONITOR_ZONE expected for a truly safe zone
    assert len(recs) >= 1
    zone_recs = [r for r in recs if r.zone_id == 1]
    actions = {r.action_type for r in zone_recs}
    assert actions == {ActionType.MONITOR_ZONE}
    assert all(r.priority == RecommendationPriority.LOW for r in zone_recs)


# ===========================================================================
# Test 2 — Critical crowd crush condition
# ===========================================================================


def test_2_crush_condition_generates_three_critical_actions(engine):
    """CRITICAL + density>=80% + speed<=0.5 must yield RESTRICT, OPEN_EXIT, DEPLOY_SECURITY at CRITICAL."""
    zone = _make_zone(
        1, 92.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 91.0, 0.2,
        trend=TrendDirection.WORSENING, time_to_critical=3.0
    )
    intel = _make_intel(1, [zone], 92.0, RiskLevel.CRITICAL, event_flags=["CRITICAL_ZONE_PRESENT"])

    recs = engine.recommend(intel)
    zone_actions = _zone_actions(recs, 1)

    assert ActionType.RESTRICT_ENTRY in zone_actions
    assert ActionType.OPEN_ALTERNATE_EXIT in zone_actions
    assert ActionType.DEPLOY_SECURITY in zone_actions

    # All three should be CRITICAL
    crush_recs = [
        r for r in recs
        if r.zone_id == 1
        and r.action_type in {ActionType.RESTRICT_ENTRY, ActionType.OPEN_ALTERNATE_EXIT, ActionType.DEPLOY_SECURITY}
    ]
    assert all(r.priority == RecommendationPriority.CRITICAL for r in crush_recs)


# ===========================================================================
# Test 3 — Crowd surge
# ===========================================================================


def test_3_surge_generates_expected_actions(engine):
    """Active surge_active must trigger RESTRICT_ENTRY, REDIRECT_CROWD, ONE_WAY_FLOW."""
    zone = _make_zone(
        4, 75.0, RiskLevel.HIGH, RiskType.CROWD_SURGE, 65.0, 0.9,
        surge=True, trend=TrendDirection.WORSENING
    )
    intel = _make_intel(1, [zone], 75.0, RiskLevel.HIGH, event_flags=["CROWD_SURGE_DETECTED"])

    recs = engine.recommend(intel)
    zone_actions = _zone_actions(recs, 4)

    assert ActionType.RESTRICT_ENTRY in zone_actions
    assert ActionType.REDIRECT_CROWD in zone_actions
    assert ActionType.ONE_WAY_FLOW in zone_actions


def test_3_surge_at_critical_level_is_critical_priority(engine):
    """Surge on a CRITICAL zone → surge rules produce CRITICAL priority."""
    zone = _make_zone(5, 85.0, RiskLevel.CRITICAL, RiskType.CROWD_SURGE, 88.0, 0.3, surge=True)
    intel = _make_intel(1, [zone], 85.0, RiskLevel.CRITICAL)

    recs = engine.recommend(intel)
    surge_recs = [
        r for r in recs
        if r.zone_id == 5
        and r.action_type in {ActionType.RESTRICT_ENTRY, ActionType.REDIRECT_CROWD, ActionType.ONE_WAY_FLOW}
    ]
    assert all(r.priority == RecommendationPriority.CRITICAL for r in surge_recs)


# ===========================================================================
# Test 4 — Reverse flow
# ===========================================================================


def test_4_reverse_flow_generates_expected_actions(engine):
    """reverse_flow_active must trigger ONE_WAY_FLOW, REDIRECT_CROWD, BROADCAST_ANNOUNCEMENT."""
    zone = _make_zone(
        6, 62.0, RiskLevel.HIGH, RiskType.REVERSE_FLOW, 65.0, 0.55,
        reverse_flow=True
    )
    intel = _make_intel(1, [zone], 62.0, RiskLevel.HIGH, event_flags=["REVERSE_FLOW_DETECTED"])

    recs = engine.recommend(intel)
    zone_actions = _zone_actions(recs, 6)

    assert ActionType.ONE_WAY_FLOW in zone_actions
    assert ActionType.REDIRECT_CROWD in zone_actions
    assert ActionType.BROADCAST_ANNOUNCEMENT in zone_actions


def test_4_reverse_flow_at_critical_escalates_priority(engine):
    """Reverse flow at CRITICAL level → ONE_WAY_FLOW and REDIRECT_CROWD become CRITICAL."""
    zone = _make_zone(
        7, 85.0, RiskLevel.CRITICAL, RiskType.REVERSE_FLOW, 80.0, 0.2,
        reverse_flow=True, trend=TrendDirection.WORSENING
    )
    intel = _make_intel(1, [zone], 85.0, RiskLevel.CRITICAL)

    recs = engine.recommend(intel)
    one_way = [r for r in recs if r.zone_id == 7 and r.action_type == ActionType.ONE_WAY_FLOW]
    redirect = [r for r in recs if r.zone_id == 7 and r.action_type == ActionType.REDIRECT_CROWD]

    assert one_way and one_way[0].priority == RecommendationPriority.CRITICAL
    assert redirect and redirect[0].priority == RecommendationPriority.CRITICAL


# ===========================================================================
# Test 5 — Bottleneck
# ===========================================================================


def test_5_bottleneck_generates_expected_actions(engine):
    """bottleneck_active must trigger OPEN_ALTERNATE_EXIT, REDIRECT_CROWD, CHANGE_BARRICADE."""
    zone = _make_zone(
        8, 68.0, RiskLevel.HIGH, RiskType.BOTTLENECK, 78.0, 0.3,
        bottleneck=True, congestion=75.0
    )
    intel = _make_intel(1, [zone], 68.0, RiskLevel.HIGH)

    recs = engine.recommend(intel)
    zone_actions = _zone_actions(recs, 8)

    assert ActionType.OPEN_ALTERNATE_EXIT in zone_actions
    assert ActionType.REDIRECT_CROWD in zone_actions
    assert ActionType.CHANGE_BARRICADE in zone_actions


# ===========================================================================
# Test 6 — High density risk type
# ===========================================================================


def test_6_high_density_generates_restrict_and_monitor(engine):
    """HIGH_DENSITY risk type must generate RESTRICT_ENTRY and MONITOR_ZONE."""
    zone = _make_zone(
        2, 55.0, RiskLevel.MEDIUM, RiskType.HIGH_DENSITY, 74.0, 0.8
    )
    intel = _make_intel(1, [zone], 55.0, RiskLevel.MEDIUM)

    recs = engine.recommend(intel)
    zone_actions = _zone_actions(recs, 2)

    assert ActionType.RESTRICT_ENTRY in zone_actions
    assert ActionType.MONITOR_ZONE in zone_actions


def test_6_high_density_worsening_raises_to_high_priority(engine):
    """HIGH_DENSITY + WORSENING trend → RESTRICT_ENTRY must be at HIGH priority."""
    zone = _make_zone(
        3, 60.0, RiskLevel.HIGH, RiskType.HIGH_DENSITY, 72.0, 0.7,
        trend=TrendDirection.WORSENING
    )
    intel = _make_intel(1, [zone], 60.0, RiskLevel.HIGH)

    recs = engine.recommend(intel)
    restrict_recs = [
        r for r in recs if r.action_type == ActionType.RESTRICT_ENTRY and r.zone_id == 3
    ]
    assert restrict_recs and restrict_recs[0].priority == RecommendationPriority.HIGH


# ===========================================================================
# Test 7 — Risk propagation (event-level)
# ===========================================================================


def test_7_propagation_severe_generates_event_actions(engine):
    """SEVERE propagation must produce event-wide recommendations."""
    zone1 = _make_zone(1, 90.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 92.0, 0.15, trend=TrendDirection.WORSENING)
    zone2 = _make_zone(2, 88.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 89.0, 0.2, trend=TrendDirection.WORSENING)
    intel = _make_intel(
        1, [zone1, zone2], 90.0, RiskLevel.CRITICAL,
        propagation=PropagationStatus.SEVERE,
        event_flags=["RISK_PROPAGATION_DETECTED", "CRITICAL_ZONE_PRESENT"],
    )

    recs = engine.recommend(intel)
    event_actions = _zone_actions(recs, None)

    assert ActionType.REDIRECT_CROWD in event_actions
    assert ActionType.OPEN_ALTERNATE_EXIT in event_actions
    assert ActionType.DEPLOY_SECURITY in event_actions
    assert ActionType.BROADCAST_ANNOUNCEMENT in event_actions


def test_7_elevated_propagation_also_fires_event_rules(engine):
    """ELEVATED propagation status should also produce event-wide recommendations."""
    zone1 = _make_zone(1, 70.0, RiskLevel.HIGH, RiskType.CONGESTION, 75.0, 0.4, congestion=80.0, trend=TrendDirection.WORSENING)
    zone2 = _make_zone(2, 65.0, RiskLevel.HIGH, RiskType.HIGH_DENSITY, 72.0, 0.5, congestion=72.0, trend=TrendDirection.WORSENING)
    intel = _make_intel(
        1, [zone1, zone2], 70.0, RiskLevel.HIGH,
        propagation=PropagationStatus.ELEVATED,
        event_flags=["RISK_PROPAGATION_DETECTED"],
    )

    recs = engine.recommend(intel)
    event_recs = [r for r in recs if r.zone_id is None]
    assert len(event_recs) > 0


# ===========================================================================
# Test 8 — No special signals → MONITOR_ZONE at LOW
# ===========================================================================


def test_8_no_signals_produces_monitor_low(engine):
    """A zone with no active danger signals must produce MONITOR_ZONE at LOW priority."""
    zone = _make_zone(1, 10.0, RiskLevel.LOW, RiskType.STABLE, 15.0, 1.6, trend=TrendDirection.STABLE)
    intel = _make_intel(1, [zone], 10.0, RiskLevel.LOW)

    recs = engine.recommend(intel)
    zone_recs = [r for r in recs if r.zone_id == 1]

    assert any(r.action_type == ActionType.MONITOR_ZONE for r in zone_recs)
    monitor_recs = [r for r in zone_recs if r.action_type == ActionType.MONITOR_ZONE]
    assert all(r.priority == RecommendationPriority.LOW for r in monitor_recs)

    # No action recommendations (RESTRICT, DEPLOY, etc.) for a safe zone
    dangerous_actions = {
        ActionType.RESTRICT_ENTRY, ActionType.DEPLOY_SECURITY,
        ActionType.OPEN_ALTERNATE_EXIT, ActionType.ONE_WAY_FLOW,
        ActionType.REDIRECT_CROWD, ActionType.CHANGE_BARRICADE,
    }
    zone_action_types = {r.action_type for r in zone_recs}
    assert zone_action_types.isdisjoint(dangerous_actions)


# ===========================================================================
# Test 9 — Priority escalation
# ===========================================================================


def test_9_priority_escalation_worsening_high_density(engine):
    """HIGH_DENSITY with WORSENING trend must escalate to HIGH priority from MEDIUM."""
    zone_stable = _make_zone(10, 55.0, RiskLevel.MEDIUM, RiskType.HIGH_DENSITY, 70.0, 0.8, trend=TrendDirection.STABLE)
    zone_worsening = _make_zone(11, 55.0, RiskLevel.MEDIUM, RiskType.HIGH_DENSITY, 70.0, 0.8, trend=TrendDirection.WORSENING)

    intel_s = _make_intel(1, [zone_stable], 55.0, RiskLevel.MEDIUM)
    intel_w = _make_intel(1, [zone_worsening], 55.0, RiskLevel.MEDIUM)

    recs_s = engine.recommend(intel_s)
    recs_w = engine.recommend(intel_w)

    restrict_s = [r for r in recs_s if r.zone_id == 10 and r.action_type == ActionType.RESTRICT_ENTRY]
    restrict_w = [r for r in recs_w if r.zone_id == 11 and r.action_type == ActionType.RESTRICT_ENTRY]

    assert restrict_s[0].priority == RecommendationPriority.MEDIUM
    assert restrict_w[0].priority == RecommendationPriority.HIGH


# ===========================================================================
# Test 10 — Confidence calculation
# ===========================================================================


def test_10_confidence_components_are_additive(engine):
    """Worsening trend + imminent time_to_critical should produce higher confidence than stable."""
    zone_low = _make_zone(1, 55.0, RiskLevel.MEDIUM, RiskType.HIGH_DENSITY, 70.0, 0.8, trend=TrendDirection.STABLE)
    zone_high = _make_zone(
        2, 55.0, RiskLevel.MEDIUM, RiskType.HIGH_DENSITY, 70.0, 0.8,
        trend=TrendDirection.WORSENING, time_to_critical=8.0, confidence=80.0
    )

    intel_low = _make_intel(1, [zone_low], 55.0, RiskLevel.MEDIUM)
    intel_high = _make_intel(1, [zone_high], 55.0, RiskLevel.MEDIUM)

    recs_low = engine.recommend(intel_low)
    recs_high = engine.recommend(intel_high)

    conf_low = max((r.confidence for r in recs_low if r.zone_id == 1), default=0.0)
    conf_high = max((r.confidence for r in recs_high if r.zone_id == 2), default=0.0)

    assert conf_high > conf_low, "More evidence signals should produce higher confidence"


def test_10_confidence_is_deterministic(engine):
    """Same input must produce identical confidence values on repeated calls."""
    zone = _make_zone(1, 70.0, RiskLevel.HIGH, RiskType.BOTTLENECK, 78.0, 0.3, bottleneck=True, trend=TrendDirection.WORSENING, time_to_critical=7.0)
    intel = _make_intel(1, [zone], 70.0, RiskLevel.HIGH)

    recs1 = engine.recommend(intel)
    recs2 = engine.recommend(intel)

    confs1 = sorted(r.confidence for r in recs1)
    confs2 = sorted(r.confidence for r in recs2)
    assert confs1 == confs2


# ===========================================================================
# Test 11 — Confidence clamping
# ===========================================================================


def test_11_confidence_clamped_to_valid_range(engine):
    """All confidence values must be in [0.0, 1.0]."""
    zone = _make_zone(
        1, 98.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 99.0, 0.05,
        surge=True, reverse_flow=True, bottleneck=True,
        trend=TrendDirection.WORSENING, time_to_critical=1.0, confidence=95.0
    )
    intel = _make_intel(
        1, [zone], 98.0, RiskLevel.CRITICAL,
        propagation=PropagationStatus.SEVERE,
        event_flags=["RISK_PROPAGATION_DETECTED", "CRITICAL_ZONE_PRESENT"],
    )

    recs = engine.recommend(intel)
    for r in recs:
        assert 0.0 <= r.confidence <= 1.0, f"Out-of-range confidence {r.confidence} for {r.recommendation_id}"


def test_11_low_risk_score_critical_zone_moderate_confidence(engine):
    """A CRITICAL zone with a weak prediction should NOT have confidence=1.0."""
    # Simulate: risk score is moderate despite CRITICAL label (edge case)
    zone = _make_zone(
        1, 81.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 82.0, 0.45,
        trend=TrendDirection.STABLE,  # no worsening
        confidence=30.0,              # weak prediction certainty
    )
    intel = _make_intel(1, [zone], 81.0, RiskLevel.CRITICAL)
    recs = engine.recommend(intel)

    crush_recs = [r for r in recs if r.zone_id == 1 and r.priority == RecommendationPriority.CRITICAL]
    assert len(crush_recs) > 0
    # Confidence is floor-bounded at 0.70 for CRITICAL, but not forced to 1.0
    assert all(r.confidence < 1.0 for r in crush_recs), (
        "CRITICAL zone with weak prediction should not have confidence=1.0"
    )
    assert all(r.confidence >= 0.70 for r in crush_recs), (
        "CRITICAL recommendations must be at least 0.70 confident"
    )


# ===========================================================================
# Test 12 — Deduplication
# ===========================================================================


def test_12_no_duplicate_action_per_zone(engine):
    """Output must contain at most one recommendation per (zone_id, action_type) pair."""
    zone = _make_zone(
        1, 92.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 91.0, 0.15,
        surge=True, reverse_flow=True, bottleneck=True,
        trend=TrendDirection.WORSENING, time_to_critical=2.0,
    )
    intel = _make_intel(
        1, [zone], 92.0, RiskLevel.CRITICAL,
        propagation=PropagationStatus.SEVERE,
        event_flags=["RISK_PROPAGATION_DETECTED", "CRITICAL_ZONE_PRESENT"],
    )

    recs = engine.recommend(intel)
    seen = set()
    for r in recs:
        key = (r.zone_id, r.action_type)
        assert key not in seen, f"Duplicate key found: {key}"
        seen.add(key)


def test_12_deduplication_keeps_highest_priority(engine):
    """When multiple rules fire RESTRICT_ENTRY for the same zone, the CRITICAL one wins."""
    # Crush rule (CRITICAL) and surge rule (HIGH) both produce RESTRICT_ENTRY for zone 1.
    # After dedup, the CRITICAL entry must survive.
    zone = _make_zone(
        1, 92.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 91.0, 0.15,
        surge=True, trend=TrendDirection.WORSENING,
    )
    intel = _make_intel(1, [zone], 92.0, RiskLevel.CRITICAL)

    recs = engine.recommend(intel)
    restrict_recs = [r for r in recs if r.zone_id == 1 and r.action_type == ActionType.RESTRICT_ENTRY]

    assert len(restrict_recs) == 1
    assert restrict_recs[0].priority == RecommendationPriority.CRITICAL


def test_12_deduplication_event_level_uses_none_key(engine):
    """Event-level deduplication must use (None, action_type) as the key."""
    zone1 = _make_zone(1, 90.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 92.0, 0.15, trend=TrendDirection.WORSENING)
    zone2 = _make_zone(2, 88.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 89.0, 0.2, trend=TrendDirection.WORSENING)
    intel = _make_intel(
        1, [zone1, zone2], 90.0, RiskLevel.CRITICAL,
        propagation=PropagationStatus.SEVERE,
        event_flags=["RISK_PROPAGATION_DETECTED"],
    )

    recs = engine.recommend(intel)
    event_recs = [r for r in recs if r.zone_id is None]

    seen_actions = set()
    for r in event_recs:
        assert r.action_type not in seen_actions, f"Duplicate event-level action: {r.action_type}"
        seen_actions.add(r.action_type)


# ===========================================================================
# Test 13 — Deterministic ranking
# ===========================================================================


def test_13_recommendations_sorted_critical_first(engine):
    """Output list must be sorted: CRITICAL before HIGH before MEDIUM before LOW."""
    zone_crit = _make_zone(1, 92.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 91.0, 0.1, trend=TrendDirection.WORSENING)
    zone_med = _make_zone(2, 45.0, RiskLevel.MEDIUM, RiskType.HIGH_DENSITY, 50.0, 1.0)

    intel = _make_intel(1, [zone_crit, zone_med], 92.0, RiskLevel.CRITICAL)
    recs = engine.recommend(intel)

    ranks = [PRIORITY_RANK[r.priority] for r in recs]
    assert ranks == sorted(ranks), "Recommendations not sorted by priority rank"


def test_13_same_priority_sorted_by_confidence_descending(engine):
    """Within same priority, higher confidence recommendations must appear first."""
    # Two zones both at HIGH, but different scores (confidence will differ)
    zone_high_conf = _make_zone(
        1, 75.0, RiskLevel.HIGH, RiskType.BOTTLENECK, 78.0, 0.3,
        bottleneck=True, trend=TrendDirection.WORSENING, time_to_critical=8.0, confidence=90.0
    )
    zone_low_conf = _make_zone(
        2, 62.0, RiskLevel.HIGH, RiskType.BOTTLENECK, 72.0, 0.4,
        bottleneck=True, trend=TrendDirection.STABLE, confidence=40.0
    )
    intel = _make_intel(1, [zone_high_conf, zone_low_conf], 75.0, RiskLevel.HIGH)

    recs = engine.recommend(intel)
    high_priority_recs = [r for r in recs if r.priority == RecommendationPriority.HIGH]

    if len(high_priority_recs) >= 2:
        confidences = [r.confidence for r in high_priority_recs]
        # Must be non-increasing (descending or equal)
        for i in range(len(confidences) - 1):
            assert confidences[i] >= confidences[i + 1], (
                f"Confidence not descending at index {i}: {confidences[i]} < {confidences[i + 1]}"
            )


def test_13_output_is_deterministic(engine):
    """Same input must produce identical output on repeated calls."""
    zone = _make_zone(1, 80.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 85.0, 0.2, surge=True, bottleneck=True, trend=TrendDirection.WORSENING)
    intel = _make_intel(1, [zone], 80.0, RiskLevel.CRITICAL)

    recs1 = engine.recommend(intel)
    recs2 = engine.recommend(intel)

    assert [(r.recommendation_id, r.priority, r.confidence) for r in recs1] == \
           [(r.recommendation_id, r.priority, r.confidence) for r in recs2]


# ===========================================================================
# Test 14 — Explainability
# ===========================================================================


def test_14_reason_contains_zone_id_and_density(engine):
    """Every zone-specific recommendation must mention the zone ID and density in its reason."""
    zone = _make_zone(
        42, 82.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 88.0, 0.2,
        trend=TrendDirection.WORSENING, time_to_critical=4.0
    )
    intel = _make_intel(1, [zone], 82.0, RiskLevel.CRITICAL)

    recs = engine.recommend(intel)
    zone_recs = [r for r in recs if r.zone_id == 42]

    for r in zone_recs:
        assert "42" in r.reason, f"Zone ID missing from reason: {r.reason[:80]}"
        assert "88" in r.reason, f"Density missing from reason: {r.reason[:80]}"


def test_14_triggering_conditions_are_populated(engine):
    """Every recommendation must have at least one TriggeringCondition."""
    zone = _make_zone(1, 70.0, RiskLevel.HIGH, RiskType.BOTTLENECK, 78.0, 0.3, bottleneck=True)
    intel = _make_intel(1, [zone], 70.0, RiskLevel.HIGH)

    recs = engine.recommend(intel)

    for r in recs:
        assert len(r.triggering_conditions) >= 1, (
            f"No triggering conditions for {r.recommendation_id}"
        )


def test_14_triggering_conditions_have_required_fields(engine):
    """Each TriggeringCondition must have signal, observed_value, and explanation set."""
    zone = _make_zone(1, 88.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 91.0, 0.15, trend=TrendDirection.WORSENING)
    intel = _make_intel(1, [zone], 88.0, RiskLevel.CRITICAL)

    recs = engine.recommend(intel)
    for r in recs:
        for cond in r.triggering_conditions:
            assert isinstance(cond, TriggeringCondition)
            assert cond.signal, f"Empty signal in {r.recommendation_id}"
            assert cond.explanation, f"Empty explanation in {r.recommendation_id}"
            assert cond.observed_value is not None, f"None observed_value in {r.recommendation_id}"


def test_14_expected_effect_is_non_trivial(engine):
    """expected_effect must be a meaningful string (not a placeholder)."""
    zone = _make_zone(1, 75.0, RiskLevel.HIGH, RiskType.BOTTLENECK, 80.0, 0.3, bottleneck=True)
    intel = _make_intel(1, [zone], 75.0, RiskLevel.HIGH)

    recs = engine.recommend(intel)
    for r in recs:
        assert len(r.expected_effect) > 20, f"expected_effect too short for {r.recommendation_id}"


# ===========================================================================
# Test 15 — Authority approval flag
# ===========================================================================


def test_15_all_recommendations_require_authority_approval(engine):
    """Every recommendation must have requires_authority_approval == True."""
    zone1 = _make_zone(1, 92.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 91.0, 0.1, surge=True, reverse_flow=True, bottleneck=True, trend=TrendDirection.WORSENING)
    zone2 = _make_zone(2, 10.0, RiskLevel.LOW, RiskType.STABLE, 15.0, 1.5)
    intel = _make_intel(
        1, [zone1, zone2], 92.0, RiskLevel.CRITICAL,
        propagation=PropagationStatus.SEVERE,
        event_flags=["RISK_PROPAGATION_DETECTED", "CRITICAL_ZONE_PRESENT"],
    )

    recs = engine.recommend(intel)
    assert len(recs) > 0

    for r in recs:
        assert r.requires_authority_approval is True, (
            f"requires_authority_approval is False for {r.recommendation_id}"
        )


# ===========================================================================
# Test 16 — Event-level propagation uses zone_id=None
# ===========================================================================


def test_16_propagation_zone_id_is_none_not_fabricated(engine):
    """Event-level (propagation) recommendations must have zone_id=None — not -1 or any int."""
    zone1 = _make_zone(1, 90.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 92.0, 0.15, trend=TrendDirection.WORSENING)
    zone2 = _make_zone(2, 88.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH, 89.0, 0.2, trend=TrendDirection.WORSENING)
    intel = _make_intel(
        1, [zone1, zone2], 90.0, RiskLevel.CRITICAL,
        propagation=PropagationStatus.SEVERE,
        event_flags=["RISK_PROPAGATION_DETECTED"],
    )

    recs = engine.recommend(intel)
    event_recs = [r for r in recs if r.zone_id is None]

    # Must have event-level recs
    assert len(event_recs) > 0, "No event-level recommendations found"

    # All event-level recs must have zone_id exactly None
    for r in event_recs:
        assert r.zone_id is None, f"Expected zone_id=None, got zone_id={r.zone_id}"

    # Verify affected_zones lists actual zones, not None
    for r in event_recs:
        assert all(isinstance(z, int) for z in r.affected_zones), (
            "affected_zones should list integer zone IDs"
        )


def test_16_no_propagation_no_event_level_recs(engine):
    """Without propagation flags, no event-level (zone_id=None) recommendations should appear."""
    zone = _make_zone(1, 50.0, RiskLevel.MEDIUM, RiskType.CONGESTION, 55.0, 0.8, congestion=60.0)
    intel = _make_intel(1, [zone], 50.0, RiskLevel.MEDIUM, propagation=PropagationStatus.NONE)

    recs = engine.recommend(intel)
    event_recs = [r for r in recs if r.zone_id is None]

    assert len(event_recs) == 0, f"Unexpected event-level recs: {event_recs}"


# ===========================================================================
# Test 17 — Real EventCrowdIntelligence integration (fixtures-based)
# ===========================================================================


def test_17_real_intelligence_produces_structured_recommendations(engine):
    """
    Integration test using real Member 1 model instances.

    Builds a realistic EventCrowdIntelligence with mixed zone types and
    verifies the engine produces well-structured, valid output.
    """
    zone_crush = _make_zone(
        1, 93.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH,
        92.0, 0.12, surge=True, bottleneck=True, congestion=95.0,
        trend=TrendDirection.WORSENING, time_to_critical=3.0, confidence=90.0,
        pred_5m=95.0, pred_10m=98.0, pred_15m=100.0
    )
    zone_reverse = _make_zone(
        2, 65.0, RiskLevel.HIGH, RiskType.REVERSE_FLOW,
        66.0, 0.45, reverse_flow=True, congestion=70.0,
        trend=TrendDirection.WORSENING, confidence=75.0,
        pred_5m=70.0, pred_10m=73.0, pred_15m=75.0
    )
    zone_safe = _make_zone(3, 12.0, RiskLevel.LOW, RiskType.STABLE, 18.0, 1.5)

    intel = _make_intel(
        event_id=42,
        zones=[zone_crush, zone_reverse, zone_safe],
        overall_score=93.0,
        overall_level=RiskLevel.CRITICAL,
        event_trend=TrendDirection.WORSENING,
        propagation=PropagationStatus.ELEVATED,
        event_flags=[
            "CRITICAL_ZONE_PRESENT",
            "RAPID_RISK_ESCALATION",
            "CROWD_SURGE_DETECTED",
            "REVERSE_FLOW_DETECTED",
            "RISK_PROPAGATION_DETECTED",
        ],
    )

    recs = engine.recommend(intel)

    # --- Basic contract ---
    assert len(recs) > 0
    assert all(r.requires_authority_approval is True for r in recs)

    # --- No duplicates ---
    seen_keys = set()
    for r in recs:
        key = (r.zone_id, r.action_type)
        assert key not in seen_keys, f"Duplicate: {key}"
        seen_keys.add(key)

    # --- Sorted correctly ---
    ranks = [PRIORITY_RANK[r.priority] for r in recs]
    assert ranks == sorted(ranks)

    # --- Critical zone 1 has key actions ---
    z1_actions = _zone_actions(recs, 1)
    assert ActionType.RESTRICT_ENTRY in z1_actions
    assert ActionType.OPEN_ALTERNATE_EXIT in z1_actions
    assert ActionType.DEPLOY_SECURITY in z1_actions

    # --- Reverse flow zone 2 has key actions ---
    z2_actions = _zone_actions(recs, 2)
    assert ActionType.ONE_WAY_FLOW in z2_actions

    # --- Event-wide propagation actions present (zone_id=None) ---
    event_actions = _zone_actions(recs, None)
    assert ActionType.REDIRECT_CROWD in event_actions
    assert ActionType.BROADCAST_ANNOUNCEMENT in event_actions

    # --- Event ID propagated correctly ---
    assert all(r.event_id == 42 for r in recs)

    # --- Triggering conditions populated ---
    for r in recs:
        assert len(r.triggering_conditions) >= 1
        for cond in r.triggering_conditions:
            assert cond.signal
            assert cond.explanation

    # --- Confidence in valid range ---
    for r in recs:
        assert 0.0 <= r.confidence <= 1.0


# ===========================================================================
# Test 18 — Full end-to-end integration
#   Simulation → RiskEngine → PredictionEngine → CrowdIntelligenceService
#               → RecommendationEngine
# ===========================================================================


def test_18_end_to_end_simulation_to_recommendations():
    """
    Full pipeline integration test using real Member 1 engines.

    Generates a CRITICAL_ESCALATION scenario, runs it through the complete
    pipeline, and verifies that the RecommendationEngine produces sensible
    CRITICAL-priority recommendations for the most dangerous zone.

    This test exercises all Member 1 modules without any mocking.
    """
    # Step 1: Simulate crowd readings for a critical escalation scenario
    sim_service = CrowdSimulationService()
    risk_engine = RiskEngine()
    prediction_engine = PredictionEngine(min_observations=3)
    intelligence_service = CrowdIntelligenceService()
    rec_engine = RecommendationEngine()

    event_id = 99
    zone_id = 101
    zone_capacity = 500
    total_steps = 10
    start_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)

    readings = sim_service.generate_scenario(
        event_id=event_id,
        zone_id=zone_id,
        zone_capacity=zone_capacity,
        scenario=ScenarioType.CRITICAL_ESCALATION,
        total_steps=total_steps,
        start_time=start_time,
        step_seconds=60,
        seed=42,
    )
    assert len(readings) == total_steps

    # Step 2: Run each reading through RiskEngine
    assessments = [risk_engine.evaluate(r) for r in readings]

    # Step 3: Run PredictionEngine over the accumulated history
    prediction = prediction_engine.predict(assessments)

    # Step 4: Aggregate into EventCrowdIntelligence
    last_reading = readings[-1]
    last_assessment = assessments[-1]
    intel = intelligence_service.aggregate(
        event_id=event_id,
        readings=[last_reading],
        assessments=[last_assessment],
        predictions=[prediction],
    )

    # Step 5: Recommend
    recs = rec_engine.recommend(intel)

    # --- Structural checks ---
    assert isinstance(recs, list)
    assert all(isinstance(r, Recommendation) for r in recs)
    assert all(r.requires_authority_approval is True for r in recs)

    # --- No duplicates ---
    seen = set()
    for r in recs:
        key = (r.zone_id, r.action_type)
        assert key not in seen, f"Duplicate key: {key}"
        seen.add(key)

    # --- Sorted ---
    ranks = [PRIORITY_RANK[r.priority] for r in recs]
    assert ranks == sorted(ranks)

    # --- Critical escalation scenario must produce at least one CRITICAL or HIGH rec ---
    high_or_critical = [
        r for r in recs
        if r.priority in (RecommendationPriority.CRITICAL, RecommendationPriority.HIGH)
    ]
    assert len(high_or_critical) >= 1, (
        "CRITICAL_ESCALATION scenario should produce at least one HIGH/CRITICAL recommendation"
    )

    # --- All confidences valid ---
    for r in recs:
        assert 0.0 <= r.confidence <= 1.0

    # --- Triggering conditions set ---
    for r in recs:
        assert len(r.triggering_conditions) >= 1

    # --- Event ID consistent ---
    assert all(r.event_id == event_id for r in recs)
