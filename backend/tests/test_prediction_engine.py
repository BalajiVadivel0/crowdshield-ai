"""
Unit tests for the Near-Term Prediction Engine.

Integrates with the CrowdSimulationService and RiskEngine to test
full realistic pipelines (Simulation -> Risk -> Prediction) and edge cases.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.crowd_reading import CrowdReadingCreate
from app.ai.simulation.scenarios import ScenarioType
from app.ai.simulation.service import CrowdSimulationService
from app.ai.risk_engine.engine import RiskEngine
from app.ai.risk_engine.models import RiskAssessment, RiskLevel, RiskType
from app.ai.prediction_engine.engine import PredictionEngine
from app.ai.prediction_engine.models import TrendDirection, PredictionResult

# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sim_service() -> CrowdSimulationService:
    return CrowdSimulationService()


@pytest.fixture
def risk_engine() -> RiskEngine:
    return RiskEngine()


@pytest.fixture
def prediction_engine() -> PredictionEngine:
    return PredictionEngine(min_observations=3, trend_deadband=0.5)


def run_pipeline(
    scenario: ScenarioType,
    steps: int,
    sim_service: CrowdSimulationService,
    risk_engine: RiskEngine,
    step_seconds: int = 60
) -> list[RiskAssessment]:
    """Generates a sequence of risk assessments from a simulation scenario."""
    readings = sim_service.generate_scenario(
        event_id=1,
        zone_id=101,
        zone_capacity=500,
        scenario=scenario,
        total_steps=steps,
        step_seconds=step_seconds,
        seed=42
    )
    return [risk_engine.evaluate(r) for r in readings]

def mock_assessment(score: float, minutes_offset: int, density: float = 30.0) -> RiskAssessment:
    """Creates a mock RiskAssessment for specific boundary/edge case testing."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)
    reading = CrowdReadingCreate.model_construct(
        event_id=1, zone_id=1, timestamp=dt,
        person_count=100, density_percent=density,
        average_speed=1.5, dominant_direction="NORTH", crowd_growth_rate=0.0,
        congestion_score=20.0, surge_indicator=False, reverse_flow_indicator=False, bottleneck_indicator=False
    )
    # Construct a valid RiskAssessment manually for edge cases where we want exact scores
    re = RiskEngine()
    ass = re.evaluate(reading)
    # Manually override the score and features for the test
    ass.score = score
    ass.features.density_risk = density
    return ass

# ---------------------------------------------------------------------------
# Edge Cases & History Requirements
# ---------------------------------------------------------------------------

def test_empty_history(prediction_engine):
    result = prediction_engine.predict([])
    assert result.confidence == 0.0
    assert "INSUFFICIENT_DATA" in result.explanation

def test_insufficient_history(prediction_engine):
    history = [mock_assessment(20.0, 0)]
    result = prediction_engine.predict(history)
    assert result.confidence == 0.0
    assert "INSUFFICIENT_DATA" in result.explanation

def test_duplicate_timestamps(prediction_engine):
    # Pass 3 observations but they all have the exact same timestamp
    # (So unique timestamps < min_observations)
    ass1 = mock_assessment(20.0, 0)
    history = [ass1, ass1, ass1]
    result = prediction_engine.predict(history)
    assert result.confidence == 0.0
    assert "INSUFFICIENT_DATA" in result.explanation

def test_unsorted_input(prediction_engine):
    # Provide unsorted history; the engine should sort it and compute correctly
    h1 = mock_assessment(20.0, 0)
    h2 = mock_assessment(30.0, 1)
    h3 = mock_assessment(40.0, 2)
    result = prediction_engine.predict([h3, h1, h2]) # Unsorted
    # Trend should be exactly +10 points/min
    assert result.trend_direction == TrendDirection.WORSENING
    assert result.supporting_metrics.score_trend_slope == pytest.approx(10.0, 0.1)

# ---------------------------------------------------------------------------
# Trend Directions
# ---------------------------------------------------------------------------

def test_stable_sequence(prediction_engine):
    history = [
        mock_assessment(30.0, 0),
        mock_assessment(30.0, 1),
        mock_assessment(30.0, 2),
    ]
    result = prediction_engine.predict(history)
    assert result.trend_direction == TrendDirection.STABLE
    assert result.forecasts[0].predicted_score == 30.0

def test_increasing_risk_sequence(prediction_engine):
    history = [
        mock_assessment(30.0, 0),
        mock_assessment(32.0, 1),
        mock_assessment(34.0, 2),
    ]
    result = prediction_engine.predict(history)
    assert result.trend_direction == TrendDirection.WORSENING
    assert result.supporting_metrics.score_trend_slope == pytest.approx(2.0, 0.1)
    
def test_decreasing_risk_sequence(prediction_engine):
    history = [
        mock_assessment(50.0, 0),
        mock_assessment(45.0, 1),
        mock_assessment(40.0, 2),
    ]
    result = prediction_engine.predict(history)
    assert result.trend_direction == TrendDirection.IMPROVING
    assert result.supporting_metrics.score_trend_slope == pytest.approx(-5.0, 0.1)

# ---------------------------------------------------------------------------
# Forecasting & Boundaries
# ---------------------------------------------------------------------------

def test_risk_score_clamping(prediction_engine):
    # A massive spike that would predict > 100
    history = [
        mock_assessment(80.0, 0),
        mock_assessment(90.0, 1),
        mock_assessment(100.0, 2),
    ]
    result = prediction_engine.predict(history)
    # The +5 min forecast should be clamped to 100, not 150
    assert result.forecasts[0].predicted_score == 100.0

def test_forecast_horizons_exist(prediction_engine):
    history = [
        mock_assessment(40.0, 0),
        mock_assessment(41.0, 1),
        mock_assessment(42.0, 2),
    ]
    result = prediction_engine.predict(history)
    assert len(result.forecasts) == 3
    assert result.forecasts[0].horizon_minutes == 5
    assert result.forecasts[1].horizon_minutes == 10
    assert result.forecasts[2].horizon_minutes == 15

# ---------------------------------------------------------------------------
# Time to Critical
# ---------------------------------------------------------------------------

def test_critical_threshold_time_estimate(prediction_engine):
    # Current score is 60, trend is +5 per min.
    # Risk threshold high is 80. Critical starts at >80.
    # So 80 - 60 = 20 points. 20 / 5 = 4 minutes.
    history = [
        mock_assessment(50.0, 0),
        mock_assessment(55.0, 1),
        mock_assessment(60.0, 2),
    ]
    result = prediction_engine.predict(history)
    assert result.time_to_critical_minutes is not None
    # 80.01 - 60.0 = 20.01 / 5 = 4.002
    assert result.time_to_critical_minutes == pytest.approx(4.0, 0.1)

def test_no_time_to_critical_for_improving_trend(prediction_engine):
    history = [
        mock_assessment(70.0, 0),
        mock_assessment(65.0, 1),
        mock_assessment(60.0, 2),
    ]
    result = prediction_engine.predict(history)
    assert result.time_to_critical_minutes is None

def test_no_time_to_critical_if_already_critical(prediction_engine):
    history = [
        mock_assessment(85.0, 0),
        mock_assessment(90.0, 1),
        mock_assessment(95.0, 2),
    ]
    result = prediction_engine.predict(history)
    assert result.time_to_critical_minutes is None

# ---------------------------------------------------------------------------
# Realistic Pipeline Tests
# ---------------------------------------------------------------------------

def test_pipeline_normal(sim_service, risk_engine, prediction_engine):
    history = run_pipeline(ScenarioType.NORMAL, 5, sim_service, risk_engine)
    result = prediction_engine.predict(history)
    
    assert result.confidence > 0.0
    assert result.trend_direction in (TrendDirection.STABLE, TrendDirection.IMPROVING, TrendDirection.WORSENING)
    assert result.forecasts[0].predicted_score < 40.0
    if result.time_to_critical_minutes is not None:
        # If random fluctuation causes a small positive slope, critical should still be far away
        assert result.time_to_critical_minutes > 15.0

def test_pipeline_building_congestion(sim_service, risk_engine, prediction_engine):
    history = run_pipeline(ScenarioType.BUILDING_CONGESTION, 10, sim_service, risk_engine)
    # Take the last 5 steps as history window
    result = prediction_engine.predict(history[-5:])
    
    assert result.trend_direction == TrendDirection.WORSENING
    # Because density and congestion are rising steadily
    assert result.supporting_metrics.score_trend_slope > 0

def test_pipeline_critical_escalation(sim_service, risk_engine, prediction_engine):
    history = run_pipeline(ScenarioType.CRITICAL_ESCALATION, 6, sim_service, risk_engine)
    result = prediction_engine.predict(history)
    
    assert result.trend_direction == TrendDirection.WORSENING
    # The projected risk type should likely become CROWD_CRUSH given the aggressive trend
    f15 = result.forecasts[-1]
    assert f15.predicted_level == RiskLevel.CRITICAL
    assert f15.predicted_risk_type == RiskType.CROWD_CRUSH

def test_deterministic_confidence(sim_service, risk_engine, prediction_engine):
    history = run_pipeline(ScenarioType.NORMAL, 5, sim_service, risk_engine)
    res1 = prediction_engine.predict(history)
    res2 = prediction_engine.predict(history)
    assert res1.confidence == res2.confidence
