"""
Unit tests for CrowdMetricsService.

All tests are deterministic and require no database or external services.
Each test exercises one logical calculation or indicator independently.
"""

import pytest

from app.services.crowd_metrics_service import (
    BOTTLENECK_DENSITY_THRESHOLD,
    BOTTLENECK_SPEED_THRESHOLD,
    DIRECTION_CONFLICTED,
    SURGE_GROWTH_RATE_THRESHOLD,
    CrowdMetricsService,
)


@pytest.fixture
def metrics() -> CrowdMetricsService:
    """Return a fresh CrowdMetricsService instance for each test."""
    return CrowdMetricsService()


# ===========================================================================
# 1. Density calculation
# ===========================================================================


class TestComputeDensity:
    def test_full_capacity_is_100_percent(self, metrics):
        assert metrics.compute_density(person_count=500, zone_capacity=500) == 100.0

    def test_half_capacity_is_50_percent(self, metrics):
        assert metrics.compute_density(person_count=250, zone_capacity=500) == 50.0

    def test_empty_zone_is_zero(self, metrics):
        assert metrics.compute_density(person_count=0, zone_capacity=500) == 0.0

    def test_overflow_is_clamped_to_100(self, metrics):
        # More people than capacity should be clamped, not crash
        result = metrics.compute_density(person_count=600, zone_capacity=500)
        assert result == 100.0

    def test_zero_capacity_returns_zero(self, metrics):
        # Defensive: avoids division-by-zero
        assert metrics.compute_density(person_count=100, zone_capacity=0) == 0.0

    def test_single_person_in_large_zone(self, metrics):
        result = metrics.compute_density(person_count=1, zone_capacity=1000)
        assert result == pytest.approx(0.1, abs=1e-6)


# ===========================================================================
# 2. Growth rate calculation
# ===========================================================================


class TestComputeGrowthRate:
    def test_no_change_is_zero(self, metrics):
        result = metrics.compute_growth_rate(
            current_count=100, previous_count=100, elapsed_seconds=60.0
        )
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_growth_rate_100_percent_per_minute(self, metrics):
        # 100 → 200 in 60 s = +100% per minute
        result = metrics.compute_growth_rate(
            current_count=200, previous_count=100, elapsed_seconds=60.0
        )
        assert result == pytest.approx(100.0, abs=1e-6)

    def test_negative_growth_rate_when_crowd_disperses(self, metrics):
        # 200 → 100 in 60 s = −50% per minute
        result = metrics.compute_growth_rate(
            current_count=100, previous_count=200, elapsed_seconds=60.0
        )
        assert result == pytest.approx(-50.0, abs=1e-6)

    def test_growth_rate_halved_over_two_minutes(self, metrics):
        # Same absolute change, double the time → half the rate
        result_1min = metrics.compute_growth_rate(100, 50, elapsed_seconds=60.0)
        result_2min = metrics.compute_growth_rate(100, 50, elapsed_seconds=120.0)
        assert result_2min == pytest.approx(result_1min / 2, abs=1e-6)

    def test_zero_elapsed_returns_zero(self, metrics):
        result = metrics.compute_growth_rate(200, 100, elapsed_seconds=0.0)
        assert result == 0.0

    def test_previous_count_zero_with_arrivals_returns_100(self, metrics):
        result = metrics.compute_growth_rate(50, 0, elapsed_seconds=60.0)
        assert result == 100.0

    def test_previous_count_zero_no_arrivals_returns_zero(self, metrics):
        result = metrics.compute_growth_rate(0, 0, elapsed_seconds=60.0)
        assert result == 0.0


# ===========================================================================
# 3. Congestion score
# ===========================================================================


class TestComputeCongestionScore:
    def test_zero_density_and_max_speed_is_zero(self, metrics):
        # Empty, fast-moving → no congestion
        result = metrics.compute_congestion_score(density_percent=0.0, average_speed=2.0)
        assert result == pytest.approx(0.0, abs=0.01)

    def test_full_density_and_zero_speed_is_100(self, metrics):
        # Max density, stationary → maximum congestion
        result = metrics.compute_congestion_score(density_percent=100.0, average_speed=0.0)
        assert result == pytest.approx(100.0, abs=0.01)

    def test_score_increases_with_density(self, metrics):
        low = metrics.compute_congestion_score(density_percent=20.0, average_speed=1.0)
        high = metrics.compute_congestion_score(density_percent=80.0, average_speed=1.0)
        assert high > low

    def test_score_increases_as_speed_decreases(self, metrics):
        fast = metrics.compute_congestion_score(density_percent=50.0, average_speed=1.5)
        slow = metrics.compute_congestion_score(density_percent=50.0, average_speed=0.2)
        assert slow > fast

    def test_score_clamped_to_100(self, metrics):
        result = metrics.compute_congestion_score(density_percent=100.0, average_speed=0.0)
        assert result <= 100.0

    def test_score_never_negative(self, metrics):
        result = metrics.compute_congestion_score(density_percent=0.0, average_speed=2.0)
        assert result >= 0.0

    def test_moderate_conditions_produce_midrange_score(self, metrics):
        result = metrics.compute_congestion_score(density_percent=50.0, average_speed=1.0)
        assert 20.0 < result < 80.0


# ===========================================================================
# 4. Surge detection
# ===========================================================================


class TestIsSurge:
    def test_growth_above_threshold_is_surge(self, metrics):
        assert metrics.is_surge(SURGE_GROWTH_RATE_THRESHOLD + 1.0) is True

    def test_growth_at_threshold_is_not_surge(self, metrics):
        # Boundary: strictly greater than threshold
        assert metrics.is_surge(SURGE_GROWTH_RATE_THRESHOLD) is False

    def test_growth_below_threshold_is_not_surge(self, metrics):
        assert metrics.is_surge(5.0) is False

    def test_negative_growth_is_not_surge(self, metrics):
        assert metrics.is_surge(-10.0) is False

    def test_custom_threshold(self, metrics):
        assert metrics.is_surge(growth_rate=20.0, threshold=25.0) is False
        assert metrics.is_surge(growth_rate=30.0, threshold=25.0) is True


# ===========================================================================
# 5. Reverse flow detection
# ===========================================================================


class TestIsReverseFlow:
    def test_conflicted_is_reverse_flow(self, metrics):
        assert metrics.is_reverse_flow(DIRECTION_CONFLICTED) is True

    def test_conflicted_case_insensitive(self, metrics):
        assert metrics.is_reverse_flow("conflicted") is True
        assert metrics.is_reverse_flow("Conflicted") is True

    def test_cardinal_directions_are_not_reverse_flow(self, metrics):
        for direction in ("NORTH", "SOUTH", "EAST", "WEST", "N", "NE", "SW"):
            assert metrics.is_reverse_flow(direction) is False, (
                f"Expected False for direction '{direction}'"
            )


# ===========================================================================
# 6. Bottleneck detection
# ===========================================================================


class TestIsBottleneck:
    def test_high_density_low_speed_is_bottleneck(self, metrics):
        assert metrics.is_bottleneck(
            density_percent=BOTTLENECK_DENSITY_THRESHOLD,
            average_speed=BOTTLENECK_SPEED_THRESHOLD,
        ) is True

    def test_low_density_low_speed_is_not_bottleneck(self, metrics):
        assert metrics.is_bottleneck(density_percent=30.0, average_speed=0.2) is False

    def test_high_density_high_speed_is_not_bottleneck(self, metrics):
        assert metrics.is_bottleneck(density_percent=80.0, average_speed=1.5) is False

    def test_just_below_density_threshold_is_not_bottleneck(self, metrics):
        assert metrics.is_bottleneck(
            density_percent=BOTTLENECK_DENSITY_THRESHOLD - 0.1,
            average_speed=0.1,
        ) is False

    def test_just_above_speed_threshold_is_not_bottleneck(self, metrics):
        assert metrics.is_bottleneck(
            density_percent=90.0,
            average_speed=BOTTLENECK_SPEED_THRESHOLD + 0.01,
        ) is False

    def test_custom_thresholds(self, metrics):
        assert metrics.is_bottleneck(
            density_percent=50.0,
            average_speed=0.3,
            density_threshold=50.0,
            speed_threshold=0.5,
        ) is True


# ===========================================================================
# 7. compute_all_indicators — integration helper
# ===========================================================================


class TestComputeAllIndicators:
    def test_normal_conditions_all_false(self, metrics):
        result = metrics.compute_all_indicators(
            density_percent=30.0,
            average_speed=1.3,
            dominant_direction="NORTH",
            growth_rate=5.0,
        )
        assert result == {
            "surge_indicator": False,
            "reverse_flow_indicator": False,
            "bottleneck_indicator": False,
        }

    def test_critical_conditions_all_true(self, metrics):
        result = metrics.compute_all_indicators(
            density_percent=90.0,
            average_speed=0.1,
            dominant_direction="CONFLICTED",
            growth_rate=50.0,
        )
        assert result["surge_indicator"] is True
        assert result["reverse_flow_indicator"] is True
        assert result["bottleneck_indicator"] is True

    def test_none_growth_rate_does_not_trigger_surge(self, metrics):
        result = metrics.compute_all_indicators(
            density_percent=50.0,
            average_speed=1.0,
            dominant_direction="NORTH",
            growth_rate=None,
        )
        assert result["surge_indicator"] is False
