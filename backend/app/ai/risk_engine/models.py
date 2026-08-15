"""
Risk Engine — Enums, thresholds, and result contract.

Defines:
    RiskLevel       — LOW / MEDIUM / HIGH / CRITICAL
    RiskType        — Classification of the dominant crowd risk condition
    RiskFeatures    — Normalized feature values extracted from a CrowdReading
    RiskAssessment  — Full structured output of one risk evaluation

Design principles:
- All thresholds are named constants in one place.
- Enums prevent scattered string literals.
- RiskAssessment is a Pydantic model so it can be serialised to JSON
  directly for API responses and WebSocket messages.
- No database access, no recommendations, no alerts — pure data contracts.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Risk level thresholds — change here to tune globally
# ---------------------------------------------------------------------------

#: Upper bound (inclusive) of the LOW risk band
RISK_THRESHOLD_LOW: float = 30.0

#: Upper bound (inclusive) of the MEDIUM risk band
RISK_THRESHOLD_MEDIUM: float = 60.0

#: Upper bound (inclusive) of the HIGH risk band
RISK_THRESHOLD_HIGH: float = 80.0

# Anything above RISK_THRESHOLD_HIGH is CRITICAL (up to 100)

# ---------------------------------------------------------------------------
# Composite score weights — must sum to 1.0
# ---------------------------------------------------------------------------

#: Weight of the density risk component
WEIGHT_DENSITY: float = 0.40

#: Weight of the growth risk component
WEIGHT_GROWTH: float = 0.25

#: Weight of the movement conflict risk component
WEIGHT_MOVEMENT_CONFLICT: float = 0.20

#: Weight of the speed reduction risk component
WEIGHT_SPEED_REDUCTION: float = 0.15

# Quick sanity check (will raise at import if weights are edited incorrectly)
_WEIGHT_SUM = WEIGHT_DENSITY + WEIGHT_GROWTH + WEIGHT_MOVEMENT_CONFLICT + WEIGHT_SPEED_REDUCTION
assert abs(_WEIGHT_SUM - 1.0) < 1e-9, (
    f"Risk weight components must sum to 1.0, got {_WEIGHT_SUM}"
)

# ---------------------------------------------------------------------------
# Normalization reference values
# ---------------------------------------------------------------------------

#: Growth rate (% per minute) mapped to maximum growth risk (100)
MAX_GROWTH_RATE_REFERENCE: float = 50.0

#: Speed (m/s) at which speed-reduction risk is 0 (fully free-flowing)
MAX_FREE_FLOW_SPEED_REFERENCE: float = 2.0

# ---------------------------------------------------------------------------
# Risk type classification thresholds
# ---------------------------------------------------------------------------

#: Minimum density (%) for HIGH_DENSITY classification
DENSITY_RISK_HIGH_THRESHOLD: float = 70.0

#: Minimum congestion score for CONGESTION classification
CONGESTION_RISK_THRESHOLD: float = 60.0

#: Minimum density + speed combo threshold for CROWD_CRUSH classification
CROWD_CRUSH_DENSITY_THRESHOLD: float = 85.0
CROWD_CRUSH_SPEED_THRESHOLD: float = 0.25  # m/s

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """
    Categorical risk level derived from the composite risk score.

    Score mapping:
        0  – 30  → LOW
        31 – 60  → MEDIUM
        61 – 80  → HIGH
        81 – 100 → CRITICAL
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskType(str, Enum):
    """
    Classification of the dominant crowd risk condition.

    Determined by the strongest combination of crowd signals.
    Not every high score is a stampede — each type has a specific
    signal pattern that triggers it.
    """

    STABLE = "STABLE"
    """Normal crowd conditions, no significant risk signals."""

    CONGESTION = "CONGESTION"
    """Elevated congestion score without a single dominant signal."""

    HIGH_DENSITY = "HIGH_DENSITY"
    """Zone is heavily loaded but movement is still present."""

    CROWD_SURGE = "CROWD_SURGE"
    """Sudden, rapid influx of people detected."""

    REVERSE_FLOW = "REVERSE_FLOW"
    """Opposing crowd streams causing conflicting directional movement."""

    BOTTLENECK = "BOTTLENECK"
    """High density with critically reduced throughput and speed."""

    MOVEMENT_ANOMALY = "MOVEMENT_ANOMALY"
    """Unusual movement pattern not fitting other specific categories."""

    CROWD_CRUSH = "CROWD_CRUSH"
    """Extreme density with near-zero movement — highest severity condition."""


# ---------------------------------------------------------------------------
# Internal feature representation
# ---------------------------------------------------------------------------


class RiskFeatures(BaseModel):
    """
    Normalized risk features extracted from a CrowdReading.

    All numeric feature values are on a 0–100 scale before weighting.
    These are the inputs to the composite risk formula.

    Fields:
        density_risk            — Risk contribution from crowd density.
        growth_risk             — Risk contribution from crowd growth rate.
        movement_conflict_risk  — Risk contribution from directional conflict.
        speed_reduction_risk    — Risk contribution from reduced movement speed.

    Boolean signal pass-throughs (directly from CrowdReading indicators):
        surge_signal            — CrowdReading.surge_indicator
        reverse_flow_signal     — CrowdReading.reverse_flow_indicator
        bottleneck_signal       — CrowdReading.bottleneck_indicator
        congestion_signal       — Whether congestion_score exceeds threshold
    """

    # Normalized 0–100 components
    density_risk: float = Field(ge=0.0, le=100.0)
    growth_risk: float = Field(ge=0.0, le=100.0)
    movement_conflict_risk: float = Field(ge=0.0, le=100.0)
    speed_reduction_risk: float = Field(ge=0.0, le=100.0)

    # Boolean signals from crowd reading
    surge_signal: bool
    reverse_flow_signal: bool
    bottleneck_signal: bool
    congestion_signal: bool


# ---------------------------------------------------------------------------
# Risk Assessment — the full output contract
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    """
    Structured result of one risk evaluation.

    This is the primary output of the RiskEngine and the input to all
    downstream services (recommendations, alerts, dashboard, persistence).

    Explainability:
        The `features` field contains each contributing factor so that
        downstream consumers (dashboards, alerts, logs) can explain
        WHY a particular score was assigned, not just what the score is.

    Fields:
        score           — Composite risk score, 0–100 (higher = more dangerous).
        level           — Categorical risk level (LOW/MEDIUM/HIGH/CRITICAL).
        risk_type       — Dominant risk condition classification.
        features        — Per-component feature values used to compute the score.
        explanation     — Human-readable breakdown of contributing factors.
        event_id        — Forwarded from the source CrowdReading.
        zone_id         — Forwarded from the source CrowdReading.
    """

    # Core risk result
    score: float = Field(ge=0.0, le=100.0, description="Composite risk score (0–100).")
    level: RiskLevel = Field(description="Categorical risk level.")
    risk_type: RiskType = Field(description="Dominant crowd risk condition.")

    # Explainability
    features: RiskFeatures = Field(description="Per-component feature values (all 0–100).")
    explanation: str = Field(description="Human-readable summary of risk factors.")

    # Context forwarded from source reading
    event_id: int
    zone_id: int

    # Optional: source timestamp for traceability
    source_timestamp: Optional[str] = Field(
        default=None,
        description="ISO-format UTC timestamp of the source CrowdReading.",
    )
