"""
Tests for the CrowdIntelligenceService.
"""

from datetime import datetime, timezone
import pytest

from app.schemas.crowd_reading import CrowdReadingCreate
from app.ai.risk_engine.models import RiskAssessment, RiskLevel, RiskType, RiskFeatures
from app.ai.prediction_engine.models import PredictionResult, TrendDirection, ForecastPoint
from app.services.crowd_intelligence_service import CrowdIntelligenceService
from app.schemas.crowd_intelligence import PropagationStatus


def _make_reading(zone_id: int, person_count: int, density: float, speed: float,
                  surge: bool = False, rev: bool = False, bottleneck: bool = False, congestion: float = 0.0):
    return CrowdReadingCreate(
        event_id=1,
        zone_id=zone_id,
        timestamp=datetime.now(timezone.utc),
        person_count=person_count,
        density_percent=density,
        average_speed=speed,
        congestion_score=congestion,
        surge_indicator=surge,
        reverse_flow_indicator=rev,
        bottleneck_indicator=bottleneck
    )


def _make_assessment(zone_id: int, score: float, level: RiskLevel, risk_type: RiskType):
    return RiskAssessment(
        event_id=1,
        zone_id=zone_id,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        score=score,
        level=level,
        risk_type=risk_type,
        features=RiskFeatures(density_risk=0, growth_risk=0, movement_conflict_risk=0, speed_reduction_risk=0,
                              surge_signal=False, reverse_flow_signal=False, bottleneck_signal=False, congestion_signal=False),
        explanation=""
    )


def _make_prediction(zone_id: int, trend: TrendDirection, time_to_crit: float = None):
    return PredictionResult(
        event_id=1,
        zone_id=zone_id,
        generated_at=datetime.now(timezone.utc),
        confidence=80.0,
        trend_direction=trend,
        forecasts=[
            ForecastPoint(horizon_minutes=5, predicted_score=50, predicted_level=RiskLevel.MEDIUM, predicted_risk_type=RiskType.CONGESTION),
            ForecastPoint(horizon_minutes=10, predicted_score=50, predicted_level=RiskLevel.MEDIUM, predicted_risk_type=RiskType.CONGESTION),
            ForecastPoint(horizon_minutes=15, predicted_score=50, predicted_level=RiskLevel.MEDIUM, predicted_risk_type=RiskType.CONGESTION)
        ],
        time_to_critical_minutes=time_to_crit,
        explanation=""
    )


def test_empty_collection():
    service = CrowdIntelligenceService()
    intel = service.aggregate(1, [], [], [])
    
    assert intel.event_id == 1
    assert intel.overall_risk_score == 0.0
    assert intel.total_people == 0
    assert intel.propagation_status == PropagationStatus.NONE
    assert len(intel.zone_summaries) == 0


def test_single_safe_zone():
    service = CrowdIntelligenceService()
    
    r = _make_reading(1, 10, 20.0, 1.5, congestion=10.0)
    a = _make_assessment(1, 15.0, RiskLevel.LOW, RiskType.STABLE)
    p = _make_prediction(1, TrendDirection.STABLE)
    
    intel = service.aggregate(1, [r], [a], [p])
    
    assert intel.overall_risk_score == 15.0
    assert intel.overall_risk_level == RiskLevel.LOW
    assert intel.highest_risk_zone == 1
    assert intel.event_trend == TrendDirection.STABLE
    assert intel.propagation_status == PropagationStatus.NONE
    assert intel.total_people == 10
    assert intel.average_density == 20.0


def test_multiple_mixed_zones_with_critical_override():
    service = CrowdIntelligenceService()
    
    # Zone 1: Critical
    r1 = _make_reading(1, 100, 95.0, 0.1, congestion=90.0, surge=True, bottleneck=True)
    a1 = _make_assessment(1, 85.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH)
    p1 = _make_prediction(1, TrendDirection.WORSENING, time_to_crit=2.0)
    
    # Zone 2: Medium
    r2 = _make_reading(2, 50, 45.0, 1.0, congestion=40.0)
    a2 = _make_assessment(2, 45.0, RiskLevel.MEDIUM, RiskType.CONGESTION)
    p2 = _make_prediction(2, TrendDirection.WORSENING, time_to_crit=15.0)
    
    # Zone 3: Low
    r3 = _make_reading(3, 10, 10.0, 1.5, congestion=5.0)
    a3 = _make_assessment(3, 15.0, RiskLevel.LOW, RiskType.STABLE)
    p3 = _make_prediction(3, TrendDirection.STABLE)
    
    intel = service.aggregate(1, [r1, r2, r3], [a1, a2, a3], [p1, p2, p3])
    
    # Max score = 85.0. Others = 45, 15. Avg other = 30. Contribution = 30 * 0.15 = 4.5
    # Overall = 85.0 + 4.5 = 89.5
    assert 89.0 < intel.overall_risk_score < 90.0
    assert intel.overall_risk_level == RiskLevel.CRITICAL
    assert intel.highest_risk_zone == 1
    
    # 2 zones worsening, 1 stable -> event trend WORSENING
    assert intel.event_trend == TrendDirection.WORSENING
    
    # 2 zones worsening -> propagation DEVELOPING. But wait, Z1 has congestion > 70. 
    # Congestion zones = 1. Worsening = 2. 
    # Developing rules: worsening >= 2 -> DEVELOPING.
    # Elevated: congestion > 1 and worsening >= 2. Here congestion=1, so not elevated.
    # Severe: critical >= 2. Here critical=1.
    assert intel.propagation_status == PropagationStatus.DEVELOPING
    
    # Flags
    assert "CRITICAL_ZONE_PRESENT" in intel.event_flags
    assert "RAPID_RISK_ESCALATION" in intel.event_flags  # Z1 time to critical is 2.0
    assert "CROWD_SURGE_DETECTED" in intel.event_flags
    
    # Priority
    assert intel.priority_zones == [1, 2, 3]


def test_severe_propagation():
    service = CrowdIntelligenceService()
    
    # 2 critical zones, both worsening
    r1 = _make_reading(1, 100, 95.0, 0.1, congestion=90.0)
    a1 = _make_assessment(1, 85.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH)
    p1 = _make_prediction(1, TrendDirection.WORSENING, time_to_crit=2.0)
    
    r2 = _make_reading(2, 100, 95.0, 0.1, congestion=90.0)
    a2 = _make_assessment(2, 85.0, RiskLevel.CRITICAL, RiskType.CROWD_CRUSH)
    p2 = _make_prediction(2, TrendDirection.WORSENING, time_to_crit=2.0)
    
    intel = service.aggregate(1, [r1, r2], [a1, a2], [p1, p2])
    
    assert intel.propagation_status == PropagationStatus.SEVERE
    assert "RISK_PROPAGATION_DETECTED" in intel.event_flags
    assert "MULTI_ZONE_CONGESTION" in intel.event_flags


def test_reverse_flow_propagation():
    service = CrowdIntelligenceService()
    
    r1 = _make_reading(1, 50, 50.0, 1.0, rev=True)
    a1 = _make_assessment(1, 50.0, RiskLevel.MEDIUM, RiskType.REVERSE_FLOW)
    p1 = _make_prediction(1, TrendDirection.STABLE)
    
    intel = service.aggregate(1, [r1], [a1], [p1])
    
    assert "REVERSE_FLOW_DETECTED" in intel.event_flags
    assert intel.propagation_status == PropagationStatus.DEVELOPING
