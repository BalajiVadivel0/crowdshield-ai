"""
Crowd simulation scenario profiles.

Each ScenarioType maps to a ScenarioProfile dataclass that defines the
crowd behaviour parameters used by CrowdSimulator to generate readings.

Design intent:
- Scenarios describe crowd CONDITIONS only (density, speed, direction).
- Risk scoring is NOT computed here; that belongs to the Risk Engine.
- Profiles are deterministic numeric ranges; the simulator adds controlled
  noise on top for realism.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ScenarioType(str, Enum):
    """Enumeration of supported crowd simulation scenarios."""

    NORMAL = "NORMAL"
    """Stable crowd, free-flowing movement, low congestion."""

    BUILDING_CONGESTION = "BUILDING_CONGESTION"
    """Gradually increasing density with declining movement speed."""

    SURGE = "SURGE"
    """Sudden, sharp increase in crowd size."""

    REVERSE_FLOW = "REVERSE_FLOW"
    """Opposing crowd streams creating dangerous conflicting movement."""

    BOTTLENECK = "BOTTLENECK"
    """High density with critically reduced throughput and speed."""

    CRITICAL_ESCALATION = "CRITICAL_ESCALATION"
    """Rapid density increase, near-stationary crowd, directional conflict."""


@dataclass(frozen=True)
class ScenarioProfile:
    """
    Defines the crowd behaviour envelope for one simulation scenario.

    All values describe the CROWD CONDITIONS, not the risk level.
    The simulator interpolates linearly between start and end values
    across the requested number of steps.

    Attributes:
        name:                   Scenario identifier.
        description:            Human-readable explanation.
        density_start:          Initial crowd density (% of capacity).
        density_end:            Final crowd density (% of capacity).
        speed_start:            Initial mean movement speed (m/s).
        speed_end:              Final mean movement speed (m/s).
        direction:              Dominant movement direction throughout.
        surge_trigger_step:     Step index at which surge_indicator becomes True.
                                None means surge is never forced by the scenario
                                profile (it may still be computed from growth_rate).
        reverse_flow:           Whether reverse/conflicting flow is present.
        noise_scale:            Maximum symmetric noise applied to density (%).
        speed_noise_scale:      Maximum symmetric noise applied to speed (m/s).
    """

    name: ScenarioType
    description: str

    # Density progression (% of zone capacity)
    density_start: float
    density_end: float

    # Speed progression (m/s)
    speed_start: float
    speed_end: float

    # Direction
    direction: str

    # Optional surge forcing
    surge_trigger_step: Optional[int]

    # Reverse-flow flag
    reverse_flow: bool

    # Noise parameters (for realism)
    noise_scale: float = 2.0
    speed_noise_scale: float = 0.05


# ---------------------------------------------------------------------------
# Scenario catalogue
# ---------------------------------------------------------------------------

SCENARIO_PROFILES: dict[ScenarioType, ScenarioProfile] = {
    ScenarioType.NORMAL: ScenarioProfile(
        name=ScenarioType.NORMAL,
        description=(
            "Stable event crowd. Density remains low-to-moderate. "
            "Movement is consistent and free-flowing."
        ),
        density_start=20.0,
        density_end=30.0,
        speed_start=1.3,
        speed_end=1.1,
        direction="NORTH",
        surge_trigger_step=None,
        reverse_flow=False,
        noise_scale=1.5,
        speed_noise_scale=0.04,
    ),
    ScenarioType.BUILDING_CONGESTION: ScenarioProfile(
        name=ScenarioType.BUILDING_CONGESTION,
        description=(
            "Crowd density steadily increases as the event progresses. "
            "Movement speed declines. Bottleneck conditions emerge later."
        ),
        density_start=35.0,
        density_end=78.0,
        speed_start=1.2,
        speed_end=0.35,
        direction="EAST",
        surge_trigger_step=None,
        reverse_flow=False,
        noise_scale=2.0,
        speed_noise_scale=0.05,
    ),
    ScenarioType.SURGE: ScenarioProfile(
        name=ScenarioType.SURGE,
        description=(
            "A sudden influx of people rapidly fills the zone. "
            "Person count jumps sharply in a short window."
        ),
        density_start=25.0,
        density_end=88.0,
        speed_start=1.4,
        speed_end=0.25,
        direction="SOUTH",
        surge_trigger_step=2,   # surge flag forced from step 2 onwards
        reverse_flow=False,
        noise_scale=3.0,
        speed_noise_scale=0.06,
    ),
    ScenarioType.REVERSE_FLOW: ScenarioProfile(
        name=ScenarioType.REVERSE_FLOW,
        description=(
            "Two opposing crowd streams create conflicting movement. "
            "Direction is CONFLICTED throughout. Speed is low."
        ),
        density_start=55.0,
        density_end=72.0,
        speed_start=0.65,
        speed_end=0.28,
        direction="CONFLICTED",
        surge_trigger_step=None,
        reverse_flow=True,
        noise_scale=2.0,
        speed_noise_scale=0.04,
    ),
    ScenarioType.BOTTLENECK: ScenarioProfile(
        name=ScenarioType.BOTTLENECK,
        description=(
            "Zone is at or above capacity with minimal throughput. "
            "High density and very low speed persist throughout."
        ),
        density_start=72.0,
        density_end=87.0,
        speed_start=0.48,
        speed_end=0.18,
        direction="WEST",
        surge_trigger_step=None,
        reverse_flow=False,
        noise_scale=1.5,
        speed_noise_scale=0.03,
    ),
    ScenarioType.CRITICAL_ESCALATION: ScenarioProfile(
        name=ScenarioType.CRITICAL_ESCALATION,
        description=(
            "Rapidly escalating crowd density approaching capacity. "
            "Movement nearly stops, directional conflict appears. "
            "All danger indicators activate."
        ),
        density_start=40.0,
        density_end=96.0,
        speed_start=1.0,
        speed_end=0.08,
        direction="CONFLICTED",
        surge_trigger_step=1,
        reverse_flow=True,
        noise_scale=2.5,
        speed_noise_scale=0.04,
    ),
}
