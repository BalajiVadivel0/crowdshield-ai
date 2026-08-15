"""
Unit tests for the Risk Engine.

Verifies risk feature extraction, normalization, score computation,
risk level mapping, and risk type classification.

Integrates with the CrowdSimulationService to provide realistic,
structured CrowdReadingCreate inputs for testing.
"""

from datetime import datetime, timezone

import pytest

from app.schemas.crowd_reading import CrowdReadingCreate
from app.ai.simulation.scenarios import ScenarioType
from app.ai.simulation.service import CrowdSimulationService
from app.ai.risk_engine.engine import RiskEngine
from app.ai.risk_engine.models import (
    RiskAssessment,
    RiskLevel,
    RiskType,
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_MEDIUM,
    RISK_THRESHOLD_HIGH,
    WEIGHT_DENSITY,
    WEIGHT_GROWTH,
    WEIGHT_MOVEMENT_CONFLICT,
    WEIGHT_SPEED_REDUCTION,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def risk_engine() -> RiskEngine:
    return RiskEngine()


@pytest.fixture
def sim_service() -> CrowdSimulationService:
    return CrowdSimulationService()


def get_scenario_reading(
    sim_service: CrowdSimulationService, scenario: ScenarioType, step: int, total_steps: int = 10
) -> CrowdReadingCreate:
    """Helper to get a deterministic reading from a scenario."""
    readings = sim_service.generate_scenario(
        event_id=1,
        zone_id=101,
        zone_capacity=500,
        scenario=scenario,
        total_steps=total_steps,
        seed=42,  # deterministic
    )
    return readings[step]


# ---------------------------------------------------------------------------
# 1. Very low-risk normal crowd
# ---------------------------------------------------------------------------

def test_very_low_risk_normal_crowd(risk_engine, sim_service):
    # Step 0 of NORMAL is very quiet
    reading = get_scenario_reading(sim_service, ScenarioType.NORMAL, 0)
    result = risk_engine.evaluate(reading)

    assert isinstance(result, RiskAssessment)
    assert result.level == RiskLevel.LOW
    assert result.risk_type == RiskType.STABLE
    assert result.score <= RISK_THRESHOLD_LOW
    assert result.features.density_risk < 50.0
    assert result.features.movement_conflict_risk == 0.0

# ---------------------------------------------------------------------------
# 2. Moderate congestion
# ---------------------------------------------------------------------------

def test_moderate_congestion(risk_engine, sim_service):
    # Mid-step of BUILDING_CONGESTION
    reading = get_scenario_reading(sim_service, ScenarioType.BUILDING_CONGESTION, 5)
    result = risk_engine.evaluate(reading)

    assert result.level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
    # Could be CONGESTION or something else, but definitely not CRITICAL
    assert result.score > RISK_THRESHOLD_LOW

# ---------------------------------------------------------------------------
# 3. High density
# ---------------------------------------------------------------------------

def test_high_density(risk_engine):
    # Construct a specific high density, but normal speed reading
    reading = CrowdReadingCreate(
        event_id=1,
        zone_id=1,
        timestamp=datetime.now(timezone.utc),
        person_count=400,
        density_percent=80.0,
        average_speed=1.0,  # Moving okay
        dominant_direction="NORTH",
        crowd_growth_rate=0.0,
        congestion_score=65.0,
        surge_indicator=False,
        reverse_flow_indicator=False,
        bottleneck_indicator=False,
    )
    result = risk_engine.evaluate(reading)
    
    assert result.risk_type == RiskType.HIGH_DENSITY
    assert result.features.density_risk == 80.0
    assert result.features.movement_conflict_risk == 0.0

# ---------------------------------------------------------------------------
# 4. Sudden surge
# ---------------------------------------------------------------------------

def test_sudden_surge(risk_engine, sim_service):
    # Step 5 of SURGE should have surge_indicator True
    reading = get_scenario_reading(sim_service, ScenarioType.SURGE, 5)
    result = risk_engine.evaluate(reading)

    assert result.features.surge_signal is True
    # If a surge is active and no bottleneck/crush, it should be CROWD_SURGE
    assert result.risk_type == RiskType.CROWD_SURGE

# ---------------------------------------------------------------------------
# 5. Reverse flow
# ---------------------------------------------------------------------------

def test_reverse_flow(risk_engine, sim_service):
    reading = get_scenario_reading(sim_service, ScenarioType.REVERSE_FLOW, 5)
    result = risk_engine.evaluate(reading)

    assert result.features.reverse_flow_signal is True
    assert result.features.movement_conflict_risk == 100.0
    assert result.risk_type == RiskType.REVERSE_FLOW

# ---------------------------------------------------------------------------
# 6. Bottleneck
# ---------------------------------------------------------------------------

def test_bottleneck(risk_engine, sim_service):
    reading = get_scenario_reading(sim_service, ScenarioType.BOTTLENECK, 5)
    result = risk_engine.evaluate(reading)

    assert result.features.bottleneck_signal is True
    # If bottleneck is active and density isn't quite CRUSH level (85+ with <0.25 speed)
    # then it should evaluate to BOTTLENECK.
    assert result.risk_type in (RiskType.BOTTLENECK, RiskType.CROWD_CRUSH)

# ---------------------------------------------------------------------------
# 7. Severe crush-like conditions
# ---------------------------------------------------------------------------

def test_severe_crush(risk_engine, sim_service):
    # The last step of CRITICAL_ESCALATION gets extremely dense and slow
    reading = get_scenario_reading(sim_service, ScenarioType.CRITICAL_ESCALATION, 9)
    result = risk_engine.evaluate(reading)

    assert result.level == RiskLevel.CRITICAL
    assert result.risk_type == RiskType.CROWD_CRUSH
    assert result.score > RISK_THRESHOLD_HIGH

# ---------------------------------------------------------------------------
# 8. Score lower boundary & Clamping
# ---------------------------------------------------------------------------

def test_score_lower_boundary(risk_engine):
    # Use model_construct to bypass Pydantic schema validation so we can test
    # the RiskEngine's own internal clamping logic for negative values.
    reading = CrowdReadingCreate.model_construct(
        event_id=1, zone_id=1, timestamp=datetime.now(timezone.utc),
        person_count=0, density_percent=-10.0,
        average_speed=3.0, dominant_direction="NORTH", crowd_growth_rate=-50.0,
        congestion_score=-5.0, surge_indicator=False, reverse_flow_indicator=False, bottleneck_indicator=False
    )
    result = risk_engine.evaluate(reading)
    
    assert result.score == 0.0
    assert result.level == RiskLevel.LOW
    assert result.features.density_risk == 0.0
    assert result.features.growth_risk == 0.0
    assert result.features.speed_reduction_risk == 0.0

# ---------------------------------------------------------------------------
# 9. Score upper boundary & Clamping
# ---------------------------------------------------------------------------

def test_score_upper_boundary(risk_engine):
    # Use model_construct to test clamping of values beyond expected maximums
    reading = CrowdReadingCreate.model_construct(
        event_id=1, zone_id=1, timestamp=datetime.now(timezone.utc),
        person_count=1000, density_percent=150.0,
        average_speed=0.0, dominant_direction="CONFLICTED", crowd_growth_rate=200.0,
        congestion_score=100.0, surge_indicator=True, reverse_flow_indicator=True, bottleneck_indicator=True
    )
    result = risk_engine.evaluate(reading)
    
    assert result.score == 100.0
    assert result.level == RiskLevel.CRITICAL
    assert result.features.density_risk == 100.0
    assert result.features.growth_risk == 100.0
    assert result.features.movement_conflict_risk == 100.0
    assert result.features.speed_reduction_risk == 100.0

# ---------------------------------------------------------------------------
# 10. Deterministic repeated evaluation
# ---------------------------------------------------------------------------

def test_deterministic_evaluation(risk_engine, sim_service):
    reading = get_scenario_reading(sim_service, ScenarioType.BUILDING_CONGESTION, 3)
    
    res1 = risk_engine.evaluate(reading)
    res2 = risk_engine.evaluate(reading)
    
    assert res1.score == res2.score
    assert res1.level == res2.level
    assert res1.risk_type == res2.risk_type
    assert res1.features.model_dump() == res2.features.model_dump()

# ---------------------------------------------------------------------------
# 11. Explainability/contributing factors
# ---------------------------------------------------------------------------

def test_explainability_output(risk_engine, sim_service):
    reading = get_scenario_reading(sim_service, ScenarioType.CRITICAL_ESCALATION, 9)
    result = risk_engine.evaluate(reading)

    explanation = result.explanation
    assert "Risk Score:" in explanation
    assert "CRITICAL" in explanation
    assert "Dominant Condition: CROWD_CRUSH" in explanation
    assert "Density Risk:" in explanation
    assert "Movement Conflict Risk:" in explanation
    assert "Active Danger Signals:" in explanation
    assert "Surge" in explanation
    assert "Reverse Flow" in explanation
    assert "Bottleneck" in explanation

    # Ensure features exist in structured form too
    assert hasattr(result.features, "density_risk")
    assert hasattr(result.features, "surge_signal")
