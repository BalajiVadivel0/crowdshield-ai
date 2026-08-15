"""
Unit tests for the crowd simulation engine.

Tests cover:
- All six scenario types
- Determinism (seed reproducibility)
- Multi-zone event stream
- CrowdSimulationService validation and service interface
- Structural integrity of generated CrowdReadingCreate objects

No database, no YOLO, no external services required.
All tests are deterministic when a seed is supplied.
"""

from datetime import datetime, timezone

import pytest

from app.ai.simulation.scenarios import ScenarioType
from app.ai.simulation.crowd_simulator import CrowdSimulator
from app.ai.simulation.service import CrowdSimulationService
from app.schemas.crowd_reading import CrowdReadingCreate


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SEED = 42
EVENT_ID = 1
ZONE_ID = 101
ZONE_CAPACITY = 500
TOTAL_STEPS = 10
FIXED_START = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def simulator() -> CrowdSimulator:
    return CrowdSimulator(seed=SEED)


@pytest.fixture
def service() -> CrowdSimulationService:
    return CrowdSimulationService()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_scenario(
    scenario: ScenarioType,
    steps: int = TOTAL_STEPS,
    seed: int = SEED,
) -> list[CrowdReadingCreate]:
    sim = CrowdSimulator(seed=seed)
    return sim.generate_scenario(
        event_id=EVENT_ID,
        zone_id=ZONE_ID,
        zone_capacity=ZONE_CAPACITY,
        scenario=scenario,
        total_steps=steps,
        start_time=FIXED_START,
        step_seconds=30,
    )


# ===========================================================================
# 1. Schema / structural integrity
# ===========================================================================


class TestReadingStructure:
    def test_reading_is_crowd_reading_create(self, simulator):
        reading = simulator.generate_reading(
            event_id=EVENT_ID,
            zone_id=ZONE_ID,
            zone_capacity=ZONE_CAPACITY,
            scenario=ScenarioType.NORMAL,
            step=0,
            total_steps=TOTAL_STEPS,
            timestamp=FIXED_START,
        )
        assert isinstance(reading, CrowdReadingCreate)

    def test_all_required_fields_present(self, simulator):
        reading = simulator.generate_reading(
            event_id=EVENT_ID,
            zone_id=ZONE_ID,
            zone_capacity=ZONE_CAPACITY,
            scenario=ScenarioType.NORMAL,
            step=0,
            total_steps=TOTAL_STEPS,
            timestamp=FIXED_START,
        )
        assert reading.event_id == EVENT_ID
        assert reading.zone_id == ZONE_ID
        assert reading.timestamp == FIXED_START
        assert reading.person_count >= 0
        assert 0.0 <= reading.density_percent <= 100.0
        assert reading.average_speed >= 0.0
        assert 0.0 <= reading.congestion_score <= 100.0

    def test_first_reading_has_no_growth_rate(self, simulator):
        reading = simulator.generate_reading(
            event_id=EVENT_ID,
            zone_id=ZONE_ID,
            zone_capacity=ZONE_CAPACITY,
            scenario=ScenarioType.NORMAL,
            step=0,
            total_steps=TOTAL_STEPS,
            timestamp=FIXED_START,
            previous_reading=None,
        )
        assert reading.crowd_growth_rate is None

    def test_second_reading_has_growth_rate(self, simulator):
        readings = run_scenario(ScenarioType.NORMAL, steps=3)
        assert readings[0].crowd_growth_rate is None
        assert readings[1].crowd_growth_rate is not None
        assert readings[2].crowd_growth_rate is not None


# ===========================================================================
# 2. Determinism
# ===========================================================================


class TestDeterminism:
    def test_same_seed_produces_identical_output(self):
        readings_a = run_scenario(ScenarioType.SURGE, seed=42)
        readings_b = run_scenario(ScenarioType.SURGE, seed=42)

        for a, b in zip(readings_a, readings_b):
            assert a.density_percent == b.density_percent
            assert a.average_speed == b.average_speed
            assert a.person_count == b.person_count
            assert a.congestion_score == b.congestion_score

    def test_different_seeds_produce_different_output(self):
        readings_a = run_scenario(ScenarioType.NORMAL, seed=1)
        readings_b = run_scenario(ScenarioType.NORMAL, seed=99)
        # At least one reading should differ (noise makes this virtually certain)
        densities_a = [r.density_percent for r in readings_a]
        densities_b = [r.density_percent for r in readings_b]
        assert densities_a != densities_b


# ===========================================================================
# 3. Scenario: NORMAL
# ===========================================================================


class TestNormalScenario:
    def test_produces_correct_step_count(self):
        readings = run_scenario(ScenarioType.NORMAL, steps=8)
        assert len(readings) == 8

    def test_density_in_expected_range(self):
        readings = run_scenario(ScenarioType.NORMAL)
        for r in readings:
            assert 10.0 <= r.density_percent <= 45.0, (
                f"Normal scenario density out of range: {r.density_percent}"
            )

    def test_speed_remains_reasonable(self):
        readings = run_scenario(ScenarioType.NORMAL)
        for r in readings:
            assert r.average_speed >= 0.8, (
                f"Normal scenario speed too low: {r.average_speed}"
            )

    def test_no_structural_danger_indicators_set(self):
        """
        In NORMAL scenario:
        - reverse_flow_indicator must always be False (direction is never CONFLICTED)
        - bottleneck_indicator must always be False (density and speed stay safe)
        - surge_indicator MAY fire if the computed growth_rate from noisy counts
          briefly crosses the threshold, which is valid behaviour. We only assert
          the structural indicators that the scenario profile hard-defines as safe.
        """
        readings = run_scenario(ScenarioType.NORMAL)
        for r in readings:
            assert r.reverse_flow_indicator is False
            assert r.bottleneck_indicator is False

    def test_timestamps_are_monotonically_increasing(self):
        readings = run_scenario(ScenarioType.NORMAL)
        for i in range(1, len(readings)):
            assert readings[i].timestamp > readings[i - 1].timestamp


# ===========================================================================
# 4. Scenario: BUILDING_CONGESTION
# ===========================================================================


class TestBuildingCongestionScenario:
    def test_density_increases_over_time(self):
        readings = run_scenario(ScenarioType.BUILDING_CONGESTION, steps=10)
        # First-third average vs last-third average
        early = sum(r.density_percent for r in readings[:3]) / 3
        late = sum(r.density_percent for r in readings[-3:]) / 3
        assert late > early, "Density should increase in BUILDING_CONGESTION"

    def test_speed_decreases_over_time(self):
        readings = run_scenario(ScenarioType.BUILDING_CONGESTION, steps=10)
        early_speed = sum(r.average_speed for r in readings[:3]) / 3
        late_speed = sum(r.average_speed for r in readings[-3:]) / 3
        assert late_speed < early_speed, "Speed should decrease in BUILDING_CONGESTION"

    def test_bottleneck_triggers_at_high_density(self):
        readings = run_scenario(ScenarioType.BUILDING_CONGESTION, steps=10)
        # Late-stage readings should trigger bottleneck
        late_readings = readings[-3:]
        assert any(r.bottleneck_indicator for r in late_readings), (
            "Expected bottleneck_indicator to be True in late BUILDING_CONGESTION steps"
        )

    def test_congestion_score_increases(self):
        readings = run_scenario(ScenarioType.BUILDING_CONGESTION, steps=10)
        early_cong = sum(r.congestion_score for r in readings[:3]) / 3
        late_cong = sum(r.congestion_score for r in readings[-3:]) / 3
        assert late_cong > early_cong


# ===========================================================================
# 5. Scenario: SURGE
# ===========================================================================


class TestSurgeScenario:
    def test_surge_indicator_set_after_trigger_step(self):
        readings = run_scenario(ScenarioType.SURGE, steps=10)
        # Profile triggers surge at step 2
        for r in readings[2:]:
            assert r.surge_indicator is True, (
                f"Expected surge_indicator=True at step ≥ 2, got {r}"
            )

    def test_density_jumps_significantly(self):
        readings = run_scenario(ScenarioType.SURGE, steps=10)
        first_density = readings[0].density_percent
        last_density = readings[-1].density_percent
        assert last_density - first_density > 40.0, (
            f"Expected density jump > 40%, got {last_density - first_density:.1f}%"
        )

    def test_person_count_grows_substantially(self):
        readings = run_scenario(ScenarioType.SURGE, steps=10)
        assert readings[-1].person_count > readings[0].person_count * 2


# ===========================================================================
# 6. Scenario: REVERSE_FLOW
# ===========================================================================


class TestReverseFlowScenario:
    def test_all_readings_have_conflicted_direction(self):
        readings = run_scenario(ScenarioType.REVERSE_FLOW)
        for r in readings:
            assert r.dominant_direction == "CONFLICTED"

    def test_reverse_flow_indicator_always_true(self):
        readings = run_scenario(ScenarioType.REVERSE_FLOW)
        for r in readings:
            assert r.reverse_flow_indicator is True

    def test_density_in_elevated_range(self):
        readings = run_scenario(ScenarioType.REVERSE_FLOW)
        for r in readings:
            assert r.density_percent > 45.0


# ===========================================================================
# 7. Scenario: BOTTLENECK
# ===========================================================================


class TestBottleneckScenario:
    def test_bottleneck_indicator_always_true(self):
        readings = run_scenario(ScenarioType.BOTTLENECK)
        for r in readings:
            assert r.bottleneck_indicator is True, (
                f"Expected bottleneck throughout, density={r.density_percent:.1f}, "
                f"speed={r.average_speed:.3f}"
            )

    def test_speed_critically_low_throughout(self):
        readings = run_scenario(ScenarioType.BOTTLENECK)
        for r in readings:
            assert r.average_speed <= 0.55

    def test_density_stays_high(self):
        readings = run_scenario(ScenarioType.BOTTLENECK)
        for r in readings:
            assert r.density_percent >= 65.0


# ===========================================================================
# 8. Scenario: CRITICAL_ESCALATION
# ===========================================================================


class TestCriticalEscalationScenario:
    def test_all_indicators_active_in_final_steps(self):
        readings = run_scenario(ScenarioType.CRITICAL_ESCALATION, steps=10)
        final = readings[-1]
        assert final.surge_indicator is True
        assert final.reverse_flow_indicator is True
        assert final.bottleneck_indicator is True

    def test_direction_is_conflicted_throughout(self):
        readings = run_scenario(ScenarioType.CRITICAL_ESCALATION)
        for r in readings:
            assert r.dominant_direction == "CONFLICTED"

    def test_density_escalates_to_critical_level(self):
        readings = run_scenario(ScenarioType.CRITICAL_ESCALATION, steps=10)
        assert readings[-1].density_percent > 80.0

    def test_speed_drops_to_near_zero(self):
        readings = run_scenario(ScenarioType.CRITICAL_ESCALATION, steps=10)
        assert readings[-1].average_speed < 0.30

    def test_congestion_score_reaches_high_level(self):
        readings = run_scenario(ScenarioType.CRITICAL_ESCALATION, steps=10)
        assert readings[-1].congestion_score > 70.0


# ===========================================================================
# 9. Multi-zone event stream
# ===========================================================================


class TestEventStream:
    def test_stream_produces_readings_for_all_zones(self):
        sim = CrowdSimulator(seed=SEED)
        zone_configs = [
            {"zone_id": 1, "zone_capacity": 300},
            {"zone_id": 2, "zone_capacity": 500},
            {"zone_id": 3, "zone_capacity": 200},
        ]
        readings = list(
            sim.generate_event_stream(
                event_id=1,
                zone_configs=zone_configs,
                scenario=ScenarioType.BUILDING_CONGESTION,
                total_steps=5,
                start_time=FIXED_START,
                step_seconds=30,
            )
        )
        # Expect total_steps × num_zones readings
        assert len(readings) == 5 * 3

    def test_stream_covers_all_zone_ids(self):
        sim = CrowdSimulator(seed=SEED)
        zone_configs = [
            {"zone_id": 10, "zone_capacity": 400},
            {"zone_id": 20, "zone_capacity": 400},
        ]
        readings = list(
            sim.generate_event_stream(
                event_id=2,
                zone_configs=zone_configs,
                scenario=ScenarioType.NORMAL,
                total_steps=3,
                start_time=FIXED_START,
            )
        )
        zone_ids = {r.zone_id for r in readings}
        assert zone_ids == {10, 20}

    def test_zone_capacity_affects_person_count(self):
        sim = CrowdSimulator(seed=SEED)
        zone_configs = [
            {"zone_id": 1, "zone_capacity": 100},
            {"zone_id": 2, "zone_capacity": 1000},
        ]
        readings = list(
            sim.generate_event_stream(
                event_id=3,
                zone_configs=zone_configs,
                scenario=ScenarioType.SURGE,
                total_steps=5,
                start_time=FIXED_START,
            )
        )
        small_zone = [r for r in readings if r.zone_id == 1]
        large_zone = [r for r in readings if r.zone_id == 2]
        # Large zone should have more people on average
        avg_small = sum(r.person_count for r in small_zone) / len(small_zone)
        avg_large = sum(r.person_count for r in large_zone) / len(large_zone)
        assert avg_large > avg_small


# ===========================================================================
# 10. CrowdSimulationService validation
# ===========================================================================


class TestSimulationServiceValidation:
    def test_negative_step_raises(self, service):
        with pytest.raises(ValueError, match="step must be in range"):
            service.generate_reading(
                event_id=1,
                zone_id=1,
                zone_capacity=500,
                scenario=ScenarioType.NORMAL,
                step=-1,
                total_steps=10,
            )

    def test_step_equals_total_steps_raises(self, service):
        with pytest.raises(ValueError):
            service.generate_reading(
                event_id=1,
                zone_id=1,
                zone_capacity=500,
                scenario=ScenarioType.NORMAL,
                step=10,
                total_steps=10,
            )

    def test_zero_zone_capacity_raises(self, service):
        with pytest.raises(ValueError, match="zone_capacity"):
            service.generate_scenario(
                event_id=1,
                zone_id=1,
                zone_capacity=0,
                scenario=ScenarioType.NORMAL,
            )

    def test_empty_zone_configs_raises(self, service):
        with pytest.raises(ValueError, match="zone_configs"):
            list(
                service.generate_event_stream(
                    event_id=1,
                    zone_configs=[],
                    scenario=ScenarioType.NORMAL,
                )
            )

    def test_missing_zone_capacity_key_raises(self, service):
        with pytest.raises(ValueError, match="zone_capacity"):
            list(
                service.generate_event_stream(
                    event_id=1,
                    zone_configs=[{"zone_id": 1}],  # missing zone_capacity
                    scenario=ScenarioType.NORMAL,
                )
            )

    def test_list_scenarios_returns_all_types(self, service):
        scenarios = service.list_scenarios()
        types = {s["type"] for s in scenarios}
        expected = {s.value for s in ScenarioType}
        assert types == expected
