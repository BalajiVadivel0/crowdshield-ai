"""
Crowd Simulation Service.

A clean, stateless service interface over CrowdSimulator.

Responsibility boundary:
    CrowdSimulationService   — public API; validates inputs, delegates to simulator
    CrowdSimulator           — internal engine; generates crowd condition data
    CrowdMetricsService      — computes indicators; used internally by the simulator

External callers (background workers, test harnesses, future API endpoints)
should import and use CrowdSimulationService rather than CrowdSimulator
directly.
"""

from datetime import datetime, timezone
from typing import Iterator, List, Optional

from app.ai.simulation.crowd_simulator import CrowdSimulator
from app.ai.simulation.scenarios import SCENARIO_PROFILES, ScenarioType
from app.schemas.crowd_reading import CrowdReadingCreate


class CrowdSimulationService:
    """
    Public service API for crowd data simulation.

    Provides three entry points:
    - generate_reading():      One reading for one zone at one step.
    - generate_scenario():     Full time-series for one zone.
    - generate_event_stream(): Interleaved time-series across multiple zones.

    Pass the same `seed` to reproduce any simulation exactly.
    Pass `seed=None` for realistic non-deterministic output.
    """

    def generate_reading(
        self,
        *,
        event_id: int,
        zone_id: int,
        zone_capacity: int,
        scenario: ScenarioType,
        step: int,
        total_steps: int,
        timestamp: Optional[datetime] = None,
        previous_reading: Optional[CrowdReadingCreate] = None,
        seed: Optional[int] = None,
    ) -> CrowdReadingCreate:
        """
        Generate a single crowd reading at a specified step in a scenario.

        Args:
            event_id:         Live event identifier.
            zone_id:          Spatial zone within the venue.
            zone_capacity:    Maximum safe capacity (persons).
            scenario:         The crowd scenario to simulate.
            step:             Current step index (0-based).
            total_steps:      Total steps in the scenario (for interpolation).
            timestamp:        UTC timestamp for this reading. Defaults to now.
            previous_reading: Prior reading for this zone (for growth rate).
            seed:             PRNG seed for reproducibility.

        Returns:
            CrowdReadingCreate — validated reading for this step.
        """
        if timestamp is None:
            timestamp = datetime.now(tz=timezone.utc)
        if total_steps < 1:
            raise ValueError("total_steps must be at least 1.")
        if step < 0 or step >= total_steps:
            raise ValueError(f"step must be in range [0, {total_steps - 1}].")
        if zone_capacity <= 0:
            raise ValueError("zone_capacity must be a positive integer.")

        sim = CrowdSimulator(seed=seed)
        return sim.generate_reading(
            event_id=event_id,
            zone_id=zone_id,
            zone_capacity=zone_capacity,
            scenario=scenario,
            step=step,
            total_steps=total_steps,
            timestamp=timestamp,
            previous_reading=previous_reading,
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
        seed: Optional[int] = None,
    ) -> List[CrowdReadingCreate]:
        """
        Generate a complete time-series for a single zone under one scenario.

        Args:
            event_id:      Live event identifier.
            zone_id:       Spatial zone identifier.
            zone_capacity: Maximum capacity (persons).
            scenario:      Crowd scenario to apply.
            total_steps:   Number of readings to generate.
            start_time:    UTC start timestamp. Defaults to now.
            step_seconds:  Interval between readings in seconds.
            seed:          PRNG seed.

        Returns:
            Chronologically ordered list of CrowdReadingCreate objects.
        """
        if total_steps < 1:
            raise ValueError("total_steps must be at least 1.")
        if zone_capacity <= 0:
            raise ValueError("zone_capacity must be a positive integer.")
        if step_seconds <= 0:
            raise ValueError("step_seconds must be positive.")
        if start_time is None:
            start_time = datetime.now(tz=timezone.utc)

        sim = CrowdSimulator(seed=seed)
        return sim.generate_scenario(
            event_id=event_id,
            zone_id=zone_id,
            zone_capacity=zone_capacity,
            scenario=scenario,
            total_steps=total_steps,
            start_time=start_time,
            step_seconds=step_seconds,
        )

    def generate_event_stream(
        self,
        *,
        event_id: int,
        zone_configs: List[dict],
        scenario: ScenarioType,
        total_steps: int = 20,
        start_time: Optional[datetime] = None,
        step_seconds: int = 30,
        seed: Optional[int] = None,
    ) -> Iterator[CrowdReadingCreate]:
        """
        Generate an interleaved crowd reading stream across multiple zones.

        Useful for simulating a full event where multiple venue zones are
        monitored simultaneously. Yields readings in time-then-zone order.

        Args:
            event_id:     Live event identifier.
            zone_configs: List of dicts, each with:
                          - zone_id (int): Zone identifier.
                          - zone_capacity (int): Zone max capacity.
            scenario:     Crowd scenario to apply to all zones.
            total_steps:  Number of time steps to simulate.
            start_time:   UTC start timestamp. Defaults to now.
            step_seconds: Interval between time steps.
            seed:         PRNG seed.

        Yields:
            CrowdReadingCreate objects in chronological order (all zones
            per step before advancing to the next step).

        Raises:
            ValueError: If zone_configs is empty or required fields are missing.
        """
        if not zone_configs:
            raise ValueError("zone_configs must contain at least one zone.")
        for cfg in zone_configs:
            if "zone_id" not in cfg or "zone_capacity" not in cfg:
                raise ValueError(
                    "Each zone_config must have 'zone_id' and 'zone_capacity' keys."
                )
            if cfg["zone_capacity"] <= 0:
                raise ValueError("zone_capacity must be a positive integer.")
        if total_steps < 1:
            raise ValueError("total_steps must be at least 1.")
        if step_seconds <= 0:
            raise ValueError("step_seconds must be positive.")
        if start_time is None:
            start_time = datetime.now(tz=timezone.utc)

        sim = CrowdSimulator(seed=seed)
        yield from sim.generate_event_stream(
            event_id=event_id,
            zone_configs=zone_configs,
            scenario=scenario,
            total_steps=total_steps,
            start_time=start_time,
            step_seconds=step_seconds,
        )

    def list_scenarios(self) -> List[dict]:
        """
        Return metadata for all available simulation scenarios.

        Useful for populating UI dropdowns or API documentation.
        """
        return [
            {
                "type": profile.name.value,
                "description": profile.description,
                "density_range": [profile.density_start, profile.density_end],
                "speed_range": [profile.speed_start, profile.speed_end],
                "reverse_flow": profile.reverse_flow,
            }
            for profile in SCENARIO_PROFILES.values()
        ]
