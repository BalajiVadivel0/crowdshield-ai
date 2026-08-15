"""
Crowd Metrics Service.

Responsible for deriving crowd behaviour metrics from raw measurement inputs.

Design principles:
- All methods are pure functions (no side effects, no DB access).
- All calculations are deterministic and unit-testable.
- No risk scoring here — that is the Risk Engine's responsibility.
- Input values are expected to have already been validated by Pydantic schemas.

Consumed by:
- CrowdSimulationService (to compute derived fields for simulated readings)
- Future vision pipeline (to compute derived fields from CV detector output)
- Risk Engine (reads the output fields, does not call this service directly)
"""


# ---------------------------------------------------------------------------
# Constants — tunable thresholds for crowd condition detection
# ---------------------------------------------------------------------------

#: Speed above which crowd movement is considered free-flowing (m/s)
MAX_FREE_FLOW_SPEED: float = 2.0

#: Weight of density in the composite congestion score (0–1)
CONGESTION_DENSITY_WEIGHT: float = 0.60

#: Weight of speed deficit in the composite congestion score (0–1)
CONGESTION_SPEED_WEIGHT: float = 0.40

#: Growth rate (% per minute) above which a surge is declared
SURGE_GROWTH_RATE_THRESHOLD: float = 15.0

#: Density (%) above which bottleneck conditions may exist
BOTTLENECK_DENSITY_THRESHOLD: float = 70.0

#: Speed (m/s) below which bottleneck conditions may exist
BOTTLENECK_SPEED_THRESHOLD: float = 0.50

#: Direction string used when opposing crowd flows are detected
DIRECTION_CONFLICTED: str = "CONFLICTED"


class CrowdMetricsService:
    """
    Stateless service for computing crowd behaviour metrics.

    All public methods accept raw measurement values and return a
    single derived metric. Compose them in the simulation or vision
    pipeline to build a complete CrowdReadingCreate payload.
    """

    # ------------------------------------------------------------------
    # 1. Density
    # ------------------------------------------------------------------

    def compute_density(self, person_count: int, zone_capacity: int) -> float:
        """
        Compute crowd density as a percentage of zone capacity.

        Args:
            person_count:   Number of persons currently in the zone.
            zone_capacity:  Maximum safe capacity of the zone (persons).

        Returns:
            Density percentage clamped to [0.0, 100.0].
        """
        if zone_capacity <= 0:
            return 0.0
        raw = (person_count / zone_capacity) * 100.0
        return max(0.0, min(100.0, raw))

    # ------------------------------------------------------------------
    # 2. Crowd growth rate
    # ------------------------------------------------------------------

    def compute_growth_rate(
        self,
        current_count: int,
        previous_count: int,
        elapsed_seconds: float,
    ) -> float:
        """
        Compute the percentage change in crowd size per minute.

        A positive value means the crowd is growing; negative means dispersing.

        Args:
            current_count:    Person count at the current timestamp.
            previous_count:   Person count at the previous timestamp.
            elapsed_seconds:  Wall-clock seconds between the two readings.

        Returns:
            Growth rate in percent per minute.
            Returns 0.0 when elapsed_seconds ≤ 0 or previous_count is 0.
        """
        if elapsed_seconds <= 0:
            return 0.0
        if previous_count == 0:
            # Zone was empty; treat any new arrivals as maximum positive growth
            return 100.0 if current_count > 0 else 0.0

        delta_percent = ((current_count - previous_count) / previous_count) * 100.0
        minutes_elapsed = elapsed_seconds / 60.0
        return delta_percent / minutes_elapsed

    # ------------------------------------------------------------------
    # 3. Average movement speed (pass-through with bounds check)
    # ------------------------------------------------------------------

    def validate_speed(self, speed: float) -> float:
        """
        Clamp a speed value to a physically plausible range.

        Args:
            speed: Raw speed value (m/s).

        Returns:
            Speed clamped to [0.0, MAX_FREE_FLOW_SPEED].
        """
        return max(0.0, min(MAX_FREE_FLOW_SPEED, speed))

    # ------------------------------------------------------------------
    # 4. Direction (helper for CONFLICTED detection)
    # ------------------------------------------------------------------

    def is_conflicted_direction(self, dominant_direction: str) -> bool:
        """
        Return True when the dominant direction signals opposing crowd flows.

        Args:
            dominant_direction: Direction string from the measurement.

        Returns:
            True if direction is CONFLICTED.
        """
        return dominant_direction.upper() == DIRECTION_CONFLICTED

    # ------------------------------------------------------------------
    # 5. Congestion score
    # ------------------------------------------------------------------

    def compute_congestion_score(
        self,
        density_percent: float,
        average_speed: float,
        max_speed: float = MAX_FREE_FLOW_SPEED,
    ) -> float:
        """
        Compute a composite congestion score on a 0–100 scale.

        The score combines:
        - Crowd density (60% weight): higher density → higher congestion.
        - Speed deficit (40% weight): slower movement → higher congestion.

        Args:
            density_percent: Crowd density as % of zone capacity.
            average_speed:   Mean movement speed (m/s).
            max_speed:       Reference free-flow speed used to normalise the
                             speed deficit. Defaults to MAX_FREE_FLOW_SPEED.

        Returns:
            Congestion score clamped to [0.0, 100.0].
        """
        density_component = density_percent * CONGESTION_DENSITY_WEIGHT

        # Speed deficit: 0 when moving freely, 1 when stationary
        normalised_speed = min(average_speed / max(max_speed, 0.001), 1.0)
        speed_deficit = 1.0 - normalised_speed
        speed_component = speed_deficit * 100.0 * CONGESTION_SPEED_WEIGHT

        raw_score = density_component + speed_component
        return max(0.0, min(100.0, raw_score))

    # ------------------------------------------------------------------
    # 6. Surge detection
    # ------------------------------------------------------------------

    def is_surge(
        self,
        growth_rate: float,
        threshold: float = SURGE_GROWTH_RATE_THRESHOLD,
    ) -> bool:
        """
        Detect a sudden crowd surge.

        A surge is defined as rapid crowd growth that exceeds a safe
        rate of increase. It does not yet indicate imminent danger
        by itself — the Risk Engine combines this with other signals.

        Args:
            growth_rate: % change per minute (from compute_growth_rate).
            threshold:   Growth rate above which a surge is declared.

        Returns:
            True when growth_rate > threshold.
        """
        return growth_rate > threshold

    # ------------------------------------------------------------------
    # 7. Reverse flow detection
    # ------------------------------------------------------------------

    def is_reverse_flow(self, dominant_direction: str) -> bool:
        """
        Detect opposing/reverse crowd flow.

        Reverse flow occurs when the crowd contains significant opposing
        streams, which the vision layer encodes as CONFLICTED.

        Args:
            dominant_direction: Direction string from the measurement.

        Returns:
            True when the direction indicates conflicting flows.
        """
        return self.is_conflicted_direction(dominant_direction)

    # ------------------------------------------------------------------
    # 8. Bottleneck detection
    # ------------------------------------------------------------------

    def is_bottleneck(
        self,
        density_percent: float,
        average_speed: float,
        density_threshold: float = BOTTLENECK_DENSITY_THRESHOLD,
        speed_threshold: float = BOTTLENECK_SPEED_THRESHOLD,
    ) -> bool:
        """
        Detect a crowd bottleneck condition.

        A bottleneck exists when the zone is heavily loaded (high density)
        AND the crowd is barely moving (low speed). Both conditions must
        be true simultaneously.

        Args:
            density_percent:  Current density (%).
            average_speed:    Current mean speed (m/s).
            density_threshold: Minimum density to consider a bottleneck.
            speed_threshold:   Maximum speed still considered a bottleneck.

        Returns:
            True when density ≥ density_threshold AND speed ≤ speed_threshold.
        """
        return density_percent >= density_threshold and average_speed <= speed_threshold

    # ------------------------------------------------------------------
    # Convenience: compute all indicators in one call
    # ------------------------------------------------------------------

    def compute_all_indicators(
        self,
        density_percent: float,
        average_speed: float,
        dominant_direction: str,
        growth_rate: float | None,
    ) -> dict:
        """
        Compute all boolean danger indicators in a single call.

        Args:
            density_percent:    Zone density (%).
            average_speed:      Mean movement speed (m/s).
            dominant_direction: Primary direction string.
            growth_rate:        % per minute growth rate, or None if unavailable.

        Returns:
            dict with keys: surge_indicator, reverse_flow_indicator, bottleneck_indicator.
        """
        surge = False
        if growth_rate is not None:
            surge = self.is_surge(growth_rate)

        return {
            "surge_indicator": surge,
            "reverse_flow_indicator": self.is_reverse_flow(dominant_direction),
            "bottleneck_indicator": self.is_bottleneck(density_percent, average_speed),
        }
