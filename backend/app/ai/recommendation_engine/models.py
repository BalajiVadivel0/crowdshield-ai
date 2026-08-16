"""
Recommendation Engine — Enums, thresholds, and result contract.

Defines:
    ActionType               — Enumeration of all supported intervention actions.
    RecommendationPriority   — CRITICAL / HIGH / MEDIUM / LOW urgency levels.
    TriggeringCondition      — Structured description of one signal that activated a rule.
    Recommendation           — Full structured output of one recommended intervention.

Design principles:
- All action types and priority levels are enums to prevent scattered string literals.
- Recommendation is a Pydantic model for direct JSON serialization.
- No database access, no side effects, no randomness — pure data contracts.
- requires_authority_approval is always True; the engine NEVER executes actions.
- Structured for future What-If Simulator compatibility (action_type, zone_id,
  affected_zones, expected_effect, triggering_conditions are all preserved).
"""

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Action Types — all supported intervention recommendations
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    """
    Enumeration of crowd management interventions that authorities may consider.

    Each value corresponds to a physical or procedural action that a trained
    safety officer or event manager could take to reduce crowd risk.
    """

    OPEN_ALTERNATE_EXIT = "OPEN_ALTERNATE_EXIT"
    """Activate additional exits or evacuation routes to relieve pressure."""

    CLOSE_ENTRY_GATE = "CLOSE_ENTRY_GATE"
    """Physically close an entry point to halt additional crowd inflow."""

    RESTRICT_ENTRY = "RESTRICT_ENTRY"
    """Slow or temporarily stop crowd inflow through existing entry points."""

    REDIRECT_CROWD = "REDIRECT_CROWD"
    """Guide crowd movement to alternative paths or zones."""

    DEPLOY_SECURITY = "DEPLOY_SECURITY"
    """Deploy additional security or stewards to the zone for crowd control."""

    ONE_WAY_FLOW = "ONE_WAY_FLOW"
    """Enforce a single directional flow to eliminate opposing crowd streams."""

    CHANGE_BARRICADE = "CHANGE_BARRICADE"
    """Reposition physical barriers to alter crowd flow and reduce bottlenecks."""

    BROADCAST_ANNOUNCEMENT = "BROADCAST_ANNOUNCEMENT"
    """Use PA system or screens to guide/calm crowd and distribute information."""

    MONITOR_ZONE = "MONITOR_ZONE"
    """Increase monitoring frequency for this zone; no immediate action required."""


# ---------------------------------------------------------------------------
# Priority levels — how urgently the recommendation should be acted on
# ---------------------------------------------------------------------------


class RecommendationPriority(str, Enum):
    """
    Urgency level assigned to a recommendation.

    Priority must never be random — it is derived deterministically from
    the combination of current risk level, trend direction, and time-to-critical.

    Levels:
        CRITICAL — Immediate action required; imminent danger.
        HIGH     — Urgent; conditions are severely elevated or worsening fast.
        MEDIUM   — Elevated concern; conditions are deteriorating.
        LOW      — Precautionary; situation is being monitored.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ---------------------------------------------------------------------------
# Priority ordering — used internally for deduplication and sorting
# ---------------------------------------------------------------------------

#: Numeric rank for priority comparison (lower number = higher urgency)
PRIORITY_RANK: dict[RecommendationPriority, int] = {
    RecommendationPriority.CRITICAL: 0,
    RecommendationPriority.HIGH: 1,
    RecommendationPriority.MEDIUM: 2,
    RecommendationPriority.LOW: 3,
}

#: Deterministic ordering of ActionType for tie-breaking within same priority
ACTION_TYPE_ORDER: dict[ActionType, int] = {
    ActionType.OPEN_ALTERNATE_EXIT: 0,
    ActionType.CLOSE_ENTRY_GATE: 1,
    ActionType.RESTRICT_ENTRY: 2,
    ActionType.REDIRECT_CROWD: 3,
    ActionType.DEPLOY_SECURITY: 4,
    ActionType.ONE_WAY_FLOW: 5,
    ActionType.CHANGE_BARRICADE: 6,
    ActionType.BROADCAST_ANNOUNCEMENT: 7,
    ActionType.MONITOR_ZONE: 8,
}


# ---------------------------------------------------------------------------
# Rule-level thresholds — all in one place, no magic numbers in engine code
# ---------------------------------------------------------------------------

#: Density (%) at or above which a CRITICAL zone is considered crush-risk
CRUSH_DENSITY_THRESHOLD: float = 80.0

#: Speed (m/s) at or below which a CRITICAL zone is considered crush-risk
CRUSH_SPEED_THRESHOLD: float = 0.50

#: Confidence boost when trend is WORSENING
CONFIDENCE_WORSENING_BOOST: float = 0.10

#: Confidence boost when time-to-critical is less than this value (minutes)
CONFIDENCE_IMMINENT_BOOST: float = 0.15
CONFIDENCE_IMMINENT_THRESHOLD_MINUTES: float = 15.0

#: Confidence boost when prediction engine confidence is high
CONFIDENCE_HIGH_PREDICTION_BOOST: float = 0.05
CONFIDENCE_HIGH_PREDICTION_THRESHOLD: float = 70.0

#: Minimum confidence floors per priority level
CONFIDENCE_FLOOR: dict[str, float] = {
    "CRITICAL": 0.70,
    "HIGH": 0.50,
    "MEDIUM": 0.30,
    "LOW": 0.10,
}


# ---------------------------------------------------------------------------
# TriggeringCondition — one observed signal that fired a rule
# ---------------------------------------------------------------------------


class TriggeringCondition(BaseModel):
    """
    Structured description of a single crowd signal that contributed to
    triggering this recommendation.

    A recommendation may carry multiple TriggeringConditions, one per
    active signal (density, speed, surge, reverse_flow, etc.).

    Fields:
        signal          — Machine-readable name of the observed signal
                          (e.g. "density_percent", "surge_active", "risk_level").
        observed_value  — The value that was measured when the rule fired.
                          Can be numeric (e.g. 91.0) or boolean (True) or string ("CRITICAL").
        threshold       — The threshold value that was crossed or equalled.
                          None when the signal is boolean or categorical.
        explanation     — Human-readable sentence explaining what this signal means
                          in context (e.g. "Zone density exceeds the 80% crush threshold.").
    """

    signal: str = Field(
        description="Machine-readable name of the crowd signal that fired the rule."
    )
    observed_value: Any = Field(
        description="Observed value of the signal at trigger time."
    )
    threshold: Optional[Any] = Field(
        default=None,
        description="Threshold value that was crossed. None for boolean/categorical signals.",
    )
    explanation: str = Field(
        description="Human-readable explanation of why this signal is dangerous."
    )


# ---------------------------------------------------------------------------
# Recommendation — the full output contract
# ---------------------------------------------------------------------------


class Recommendation(BaseModel):
    """
    A single structured intervention recommendation.

    This is the primary output of the RecommendationEngine. Every field
    exists to give authorities the full context they need to make an
    informed decision. The engine NEVER executes any action directly.

    Structured for future What-If Simulator consumption:
    - action_type, zone_id, affected_zones, expected_effect, and
      triggering_conditions are all preserved for downstream use.

    Fields:
        recommendation_id       — Deterministic unique ID (action + zone string).
        event_id                — Forwarded from the source EventCrowdIntelligence.
        zone_id                 — Zone where the intervention applies. None = event-wide.
        action_type             — The specific intervention being recommended.
        priority                — Urgency of this recommendation (CRITICAL/HIGH/MEDIUM/LOW).
        confidence              — Certainty score [0.0, 1.0] derived from signal strength.
                                  Represents strength of evidence, NOT probability of success.
        reason                  — Human-readable explanation of WHY this is recommended.
        triggering_conditions   — List of structured signals that activated this rule.
        expected_effect         — What outcome the intervention may produce (not guaranteed).
        affected_zones          — Zone IDs that this intervention is likely to impact.
        requires_authority_approval — Always True; the engine never executes actions.
    """

    # Identity
    recommendation_id: str = Field(
        description="Deterministic unique ID derived from action_type and zone scope."
    )
    event_id: int = Field(description="The live event this recommendation is for.")
    zone_id: Optional[int] = Field(
        default=None,
        description=(
            "Primary zone this recommendation targets. "
            "None for event-wide (cross-zone) actions."
        ),
    )

    # Action
    action_type: ActionType = Field(description="The specific intervention action.")
    priority: RecommendationPriority = Field(description="Urgency level.")

    # Confidence — evidence-based, deterministic
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Deterministic certainty score [0.0, 1.0] reflecting signal strength. "
            "Represents strength of evidence for this recommendation, "
            "NOT probability of preventing a disaster."
        ),
    )

    # Explanation
    reason: str = Field(description="Human-readable explanation of the recommendation.")
    triggering_conditions: List[TriggeringCondition] = Field(
        description="Structured list of crowd signals that activated this rule."
    )
    expected_effect: str = Field(
        description=(
            "Anticipated (not guaranteed) outcome if the intervention is applied. "
            "Authorities should exercise professional judgment."
        )
    )

    # Scope — preserved for What-If Simulator compatibility
    affected_zones: List[int] = Field(
        default_factory=list,
        description="Zone IDs that this intervention will likely affect.",
    )

    # Authority safety gate — ALWAYS True
    requires_authority_approval: bool = Field(
        default=True,
        description=(
            "Always True. This system recommends; it never activates gates, "
            "dispatches personnel, sends alerts, or triggers announcements automatically."
        ),
    )
