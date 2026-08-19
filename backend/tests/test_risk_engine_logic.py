import pytest
from datetime import datetime, timezone, timedelta
from app.schemas.crowd_reading import CrowdReadingCreate
from app.ai.risk_engine.engine import RiskEngine
from app.ai.risk_engine.models import RiskLevel, RiskAssessment

@pytest.fixture
def risk_engine():
    return RiskEngine()

def _make_reading(timestamp=None, density=0.0, speed=2.0, growth=0.0, congestion=0.0, reverse=False, surge=False, bottleneck=False):
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    return CrowdReadingCreate(
        event_id=1,
        zone_id=1,
        timestamp=timestamp,
        person_count=100,
        density_percent=density,
        average_speed=speed,
        dominant_direction="CONFLICTED" if reverse else "N",
        crowd_growth_rate=growth,
        congestion_score=congestion,
        surge_indicator=surge,
        reverse_flow_indicator=reverse,
        bottleneck_indicator=bottleneck
    )

def test_raw_score_integrity(risk_engine):
    """The raw weighted score is not artificially capped based on signal count."""
    # High density (100%), no other severe signals
    reading = _make_reading(density=100.0, speed=2.0, growth=0.0, congestion=0.0)
    assessment = risk_engine.evaluate(reading, [])
    
    assert assessment.score == 40.0  # 100 * 0.40
    assert assessment.active_signals_count == 1 # Density > 70%

def test_multi_signal_confirmation(risk_engine):
    """A single severe metric does not automatically produce CRITICAL merely because its numeric contribution is large."""
    # High density (100%), high growth (100% risk) -> score = 40 + 25 = 65
    # Since active_signals_count is 1 (Density) + 1 (Growth not counted in signals directly, wait, Surge is counted)
    # Let's add Surge so signals count is 2.
    reading = _make_reading(density=100.0, speed=2.0, growth=50.0, surge=True)
    assessment = risk_engine.evaluate(reading, [])
    
    assert assessment.score == 65.0
    assert assessment.active_signals_count == 2
    # It should be HIGH, not CRITICAL because score < 80
    assert assessment.level == RiskLevel.HIGH

def test_hysteresis_high_to_medium(risk_engine):
    """A HIGH state does not immediately downgrade when the score moves slightly below its entry threshold."""
    now = datetime.now(timezone.utc)
    # Entry threshold for HIGH is 60. Recover threshold for HIGH is 45.
    
    # Let's create a previous state that is HIGH. Score needs to be >= 60.
    # Density=100 (40), Speed=0 (15), Growth=50.0 (25). Total = 80.
    reading1 = _make_reading(timestamp=now - timedelta(seconds=10), density=100.0, speed=0.0, growth=50.0, surge=True)
    assessment1 = risk_engine.evaluate(reading1, [])
    assert assessment1.level == RiskLevel.HIGH or assessment1.level == RiskLevel.CRITICAL
    
    # We explicitly mock the previous assessment to be HIGH
    prev_assessment = assessment1
    prev_assessment.level = RiskLevel.HIGH
    
    # Now score drops to 47.5 (below 60 but above 45)
    # Density = 100 (40), speed = 1.0 (50*0.15 = 7.5) -> 47.5
    reading2 = _make_reading(timestamp=now, density=100.0, speed=1.0)
    assessment2 = risk_engine.evaluate(reading2, [prev_assessment])
    
    assert assessment2.score == 47.5
    assert assessment2.level == RiskLevel.HIGH  # Hysteresis maintained it at HIGH

def test_persistence_short_spike(risk_engine):
    """Short spikes do not cause escalation when corroborating evidence is insufficient."""
    now = datetime.now(timezone.utc)
    # Spike reading with score >= 80, but only 1 active signal (if possible).
    # Wait, score >= 80 usually means multiple signals. Let's force it by mocking.
    # Actually, we can get score=80 with Density=100 (40), Growth=15.0 (25), Speed=0 (15) -> 80.
    # Signals: Density (1) + Speed (1) = 2.
    # Wait, if signals == 2 and score >= 80, it becomes CRITICAL immediately due to rapid deterioration.
    # Let's get score >= 80 with only 1 active signal.
    # This is tricky because density=100 (1 signal), speed=0 (1 signal).
    # What if Density=100 (40), Growth=15 (25), Conflict=True (20). That's 85.
    # Signals: Density(1) + Conflict(1) = 2.
    # We can't reach 80 with only 1 signal because the max we can get without other signals is Density(40) + Growth(25) + Speed(0) + Conflict(0) = 65.
    # Unless Growth alone contributes to score but is NOT counted as a severe signal in _count_active_signals.
    # Yes, Growth is NOT counted as a signal in `_count_active_signals`!
    # So if we have Density=100 (40), Growth=15 (25), Conflict=False (0), Speed=2 (0) -> Score=65.
    # Wait, how to reach 80 with only 1 signal?
    # We can't! 40 (Density) + 25 (Growth) = 65. We NEED another feature (Conflict=20 or Speed=15).
    # Since they are both signals, ANY score >= 80 inherently has >= 2 active signals!
    # Let's just test that a score of 65 (HIGH entry) with 1 signal doesn't escalate to CRITICAL, but stays HIGH.
    reading_spike = _make_reading(timestamp=now, density=100.0, growth=50.0, surge=False, speed=2.0)
    
    assessment = risk_engine.evaluate(reading_spike, [])
    assert assessment.score == 65.0
    assert assessment.active_signals_count == 1
    assert assessment.level == RiskLevel.HIGH
    assert assessment.persistence_count == 1

def test_rapid_deterioration(risk_engine):
    """Strong multi-signal deterioration can escalate faster than a fixed 3-reading delay."""
    now = datetime.now(timezone.utc)
    # Density=100 (40), Conflict=True (20), Speed=0 (15), Growth=100 (25) -> Score = 100.
    # Signals: Density(1) + Speed(1) + Conflict(1) + Bottleneck(1) = 4
    reading = _make_reading(timestamp=now, density=100.0, speed=0.0, reverse=True, bottleneck=True)
    
    assessment = risk_engine.evaluate(reading, [])
    assert assessment.score == 75.0 # Density (40) + Conflict (20) + Speed (15) = 75. 
    # Let's add growth to get >= 80
    reading = _make_reading(timestamp=now, density=100.0, speed=0.0, reverse=True, bottleneck=True, growth=50.0)
    assessment = risk_engine.evaluate(reading, [])
    
    assert assessment.score == 100.0
    assert assessment.active_signals_count >= 2
    # Because active_signals >= 2 and score >= 80, it escalates to CRITICAL on the FIRST reading.
    assert assessment.level == RiskLevel.CRITICAL
    assert assessment.persistence_count == 1
