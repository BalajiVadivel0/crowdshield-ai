"""
Crowd Simulation Engine.

Generates deterministic, structured CrowdReading data for testing,
demonstration, and integration without requiring real CCTV or YOLO.

Architecture separation:
    CrowdSimulator          — generates crowd CONDITIONS (density, speed, direction)
    CrowdMetricsService     — derives danger INDICATORS from raw conditions
    Risk Engine (future)    — computes RISK SCORE from crowd readings

The simulator produces CrowdReadingCreate objects, not risk assessments.
Risk decisions belong exclusively to the Risk Engine.

Usage:
    sim = CrowdSimulator(seed=42)
    reading = sim.generate_reading(...)
    readings = sim.generate_scenario(...)
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Optional

from app.ai.simulation.scenarios import SCENARIO_PROFILES, ScenarioType
from app.schemas.crowd_reading import CrowdReadingCreate
from app.services.crowd_metrics_service import CrowdMetricsService


class CrowdSimulator:
    """
    Deterministic crowd data generator.

    When a seed is provided, every run produces identical output —
    critical for reproducible demos and unit tests.

    When no seed is provided, output includes controlled randomness
    suitable for realistic live simulation.

    Args:
        seed: Optional integer seed for the internal PRNG. Supply the same
              seed to reproduce any simulation exactly.
    """

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)
        self._metrics = CrowdMetricsService()

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def generate_reading(
        self,
        *,
        event_id: int,
        zone_id: int,
        zone_capacity: int,
        scenario: ScenarioType,
        step: int,
        total_steps: int,
        timestamp: datetime,
        previous_reading: Optional[CrowdReadingCreate] = None,
    ) -> CrowdReadingCreate:
        """
        Generate a single crowd reading for one step within a scenario.

        Args:
            event_id:         Live event identifier.
            zone_id:          Spatial zone within the venue.
            zone_capacity:    Maximum capacity of the zone (persons).
            scenario:         The ScenarioType driving crowd behaviour.
            step:             Current step index (0-based).
            total_steps:      Total number of steps in the scenario.
            timestamp:        UTC datetime for this reading.
            previous_reading: The immediately preceding reading for this zone,
                              used to compute crowd_growth_rate. Pass None for
                              the first reading.

        Returns:
            A validated CrowdReadingCreate instance.
        """
        profile = SCENARIO_PROFILES[scenario]

        # Progress through the scenario: 0.0 at step 0, 1.0 at last step
        progress = step / max(total_steps - 1, 1)

        # --- Density ---
        density_percent = self._interpolate(
            profile.density_start, profile.density_end, progress
        )
        density_percent += self._rng.uniform(
            -profile.noise_scale, profile.noise_scale
        )
        density_percent = max(0.0, min(100.0, density_percent))

        person_count = int(zone_capacity * density_percent / 100.0)

        # --- Speed ---
        average_speed = self._interpolate(
            profile.speed_start, profile.speed_end, progress
        )
        average_speed += self._rng.uniform(
            -profile.speed_noise_scale, profile.speed_noise_scale
        )
        average_speed = max(0.0, average_speed)

        # --- Direction ---
        dominant_direction = profile.direction

        # --- Crowd growth rate ---
        crowd_growth_rate: Optional[float] = None
        if previous_reading is not None:
            elapsed_seconds = (
                timestamp - previous_reading.timestamp
            ).total_seconds()
            if elapsed_seconds > 0:
                crowd_growth_rate = self._metrics.compute_growth_rate(
                    current_count=person_count,
                    previous_count=previous_reading.person_count,
                    elapsed_seconds=elapsed_seconds,
                )

        # --- Congestion score ---
        congestion_score = self._metrics.compute_congestion_score(
            density_percent=density_percent,
            average_speed=average_speed,
        )

        # --- Surge indicator ---
        # Forced by profile at or after surge_trigger_step,
        # OR computed from growth_rate if large enough.
        surge_indicator = (
            profile.surge_trigger_step is not None
            and step >= profile.surge_trigger_step
        )
        if crowd_growth_rate is not None:
            surge_indicator = surge_indicator or self._metrics.is_surge(crowd_growth_rate)

        # --- Reverse flow ---
        reverse_flow_indicator = profile.reverse_flow or self._metrics.is_reverse_flow(
            dominant_direction
        )

        # --- Bottleneck ---
        bottleneck_indicator = self._metrics.is_bottleneck(
            density_percent=density_percent,
            average_speed=average_speed,
        )

        return CrowdReadingCreate(
            event_id=event_id,
            zone_id=zone_id,
            timestamp=timestamp,
            person_count=person_count,
            density_percent=round(density_percent, 2),
            average_speed=round(average_speed, 3),
            dominant_direction=dominant_direction,
            crowd_growth_rate=(
                round(crowd_growth_rate, 3) if crowd_growth_rate is not None else None
            ),
            congestion_score=round(congestion_score, 2),
            surge_indicator=surge_indicator,
            reverse_flow_indicator=reverse_flow_indicator,
            bottleneck_indicator=bottleneck_indicator,
        )

    def generate_scenario(
        self,
        *,
        event_id: int,
        zone_id: int,
        zone_capacity: int,
        scenario: ScenarioType,
        total_steps: int = 10,
        start_time: Optional[datetime] = None,
        step_seconds: int = 30,
    ) -> List[CrowdReadingCreate]:
        """
        Generate a full time-series of crowd readings for a single zone.

        Args:
            event_id:      Live event identifier.
            zone_id:       Spatial zone identifier.
            zone_capacity: Maximum capacity of the zone (persons).
            scenario:      The ScenarioType to simulate.
            total_steps:   Number of time steps to generate.
            start_time:    UTC datetime of the first reading.
                           Defaults to the current UTC time.
            step_seconds:  Seconds between consecutive readings.

        Returns:
            List of CrowdReadingCreate objects in chronological order.
        """
        if start_time is None:
            start_time = datetime.now(tz=timezone.utc)

        readings: List[CrowdReadingCreate] = []
        previous: Optional[CrowdReadingCreate] = None

        for step in range(total_steps):
            timestamp = start_time + timedelta(seconds=step * step_seconds)
            reading = self.generate_reading(
                event_id=event_id,
                zone_id=zone_id,
                zone_capacity=zone_capacity,
                scenario=scenario,
                step=step,
                total_steps=total_steps,
                timestamp=timestamp,
                previous_reading=previous,
            )
            readings.append(reading)
            previous = reading

        return readings

    def generate_event_stream(
        self,
        *,
        event_id: int,
        zone_configs: List[dict],
        scenario: ScenarioType,
        total_steps: int = 20,
        start_time: Optional[datetime] = None,
        step_seconds: int = 30,
    ) -> Iterator[CrowdReadingCreate]:
        """
        Generate an interleaved stream of crowd readings across multiple zones.

        Yields readings in chronological order: all zones at step 0, then
        all zones at step 1, and so on. This matches the expected data
        pattern for a live event with multiple camera-monitored zones.

        Args:
            event_id:     Live event identifier.
            zone_configs: List of dicts with keys:
                          - zone_id (int)
                          - zone_capacity (int)
            scenario:     The ScenarioType applied to all zones.
            total_steps:  Total time steps to simulate.
            start_time:   UTC datetime of the first reading.
            step_seconds: Seconds between consecutive readings.

        Yields:
            CrowdReadingCreate objects in time-then-zone order.
        """
        if start_time is None:
            start_time = datetime.now(tz=timezone.utc)

        # Per-zone state tracking
        previous_by_zone: dict[int, Optional[CrowdReadingCreate]] = {
            cfg["zone_id"]: None for cfg in zone_configs
        }

        for step in range(total_steps):
            timestamp = start_time + timedelta(seconds=step * step_seconds)
            for cfg in zone_configs:
                zone_id = cfg["zone_id"]
                zone_capacity = cfg["zone_capacity"]

                reading = self.generate_reading(
                    event_id=event_id,
                    zone_id=zone_id,
                    zone_capacity=zone_capacity,
                    scenario=scenario,
                    step=step,
                    total_steps=total_steps,
                    timestamp=timestamp,
                    previous_reading=previous_by_zone[zone_id],
                )
                previous_by_zone[zone_id] = reading
                yield reading

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _interpolate(start: float, end: float, progress: float) -> float:
        """
        Linear interpolation from start to end at the given progress (0.0–1.0).
        """
        return start + (end - start) * progress
