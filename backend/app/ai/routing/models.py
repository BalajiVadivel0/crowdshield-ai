"""
Safe Routing Engine — data contracts and constants.

Defines:
    NodeType            — Venue node categories (ZONE, GATE, EXIT).
    RouteType           — Routing intent (SAFE_EXIT, ALTERNATE_EXIT, AVOID_ZONE,
                          ONE_WAY_REDIRECTION).
    VenueNode           — A node in the venue graph.
    VenueEdge           — A directed, weighted edge (corridor / path).
    RoutingWeights      — Configurable cost-function weights.
    SafeRouteResult     — Complete output of the routing engine.

Constants:
    All thresholds and defaults are centralised here so the engine
    contains NO magic numbers.

Design notes:
- Zone, gate, and exit nodes carry current and predicted risk scores
  (0–100) so the engine needs no direct dependency on RiskEngine output.
  Callers populate these fields from whatever source they prefer.
- Edges carry capacity and current crowd so congestion can be factored
  into cost without an external lookup.
- SafeRouteResult is structured for future What-If Simulator consumption
  (path, affected_zones, expected route metrics).
- is_available=False indicates that no viable route was found; callers
  MUST check this field before acting on the result.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Centralized constants — no magic numbers anywhere else
# ---------------------------------------------------------------------------

#: Default weights for the cost function
DEFAULT_WEIGHT_DISTANCE: float = 1.0
DEFAULT_WEIGHT_CURRENT_RISK: float = 2.0
DEFAULT_WEIGHT_PREDICTED_RISK: float = 1.5
DEFAULT_WEIGHT_CONGESTION: float = 1.0

#: Risk score (0–100) at or above which a zone is considered elevated risk
HIGH_RISK_THRESHOLD: float = 65.0

#: Risk score (0–100) at or above which a CRITICAL penalty is applied
CRITICAL_RISK_THRESHOLD: float = 80.0

#: Extra cost added when routing through a CRITICAL zone — makes Dijkstra
#: strongly prefer alternate routes without completely blocking them.
CRITICAL_RISK_PENALTY: float = 500.0

#: Conservative crowd walking speed used for estimated_time_seconds
WALKING_SPEED_MS: float = 1.0  # m/s

#: Congestion ratio at or above which a warning is emitted
HIGH_CONGESTION_THRESHOLD: float = 0.80

#: Estimated route duration (seconds) above which a warning is emitted
LONG_ROUTE_THRESHOLD_SECONDS: float = 600.0  # 10 minutes

#: Sentinel total_cost for unavailable routes (finite, JSON-safe)
UNAVAILABLE_ROUTE_COST: float = 1_000_000.0

#: Effective capacity factor for RESTRICTED connections
RESTRICTED_CAPACITY_FACTOR: float = 0.5


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NodeType(str, Enum):
    """
    Category of a node in the venue graph.

    ZONE  — An area of the venue where crowd gathers (e.g., Stage Area, Foyer).
    GATE  — An entry point into the venue or a transition node between zones.
    EXIT  — A designated egress point (the algorithm's valid destinations).
    """

    ZONE = "ZONE"
    GATE = "GATE"
    EXIT = "EXIT"


class RouteType(str, Enum):
    """
    Intent classification for a routing request.

    SAFE_EXIT          — Find the safest route to the nearest available exit.
    ALTERNATE_EXIT     — Find an alternative exit (e.g., primary exit blocked).
    AVOID_ZONE         — Find a route that bypasses high-risk zones.
    ONE_WAY_REDIRECTION — Route that enforces directed flow (one-way corridors).
    """

    SAFE_EXIT = "SAFE_EXIT"
    ALTERNATE_EXIT = "ALTERNATE_EXIT"
    AVOID_ZONE = "AVOID_ZONE"
    ONE_WAY_REDIRECTION = "ONE_WAY_REDIRECTION"


# ---------------------------------------------------------------------------
# Graph elements
# ---------------------------------------------------------------------------


class VenueNode(BaseModel):
    """
    A node in the venue graph.

    A node may represent a crowd zone, an entry/exit gate, or an emergency exit.
    Risk scores are populated externally from the risk/prediction pipeline.

    Fields:
        node_id              — Unique string identifier (e.g., "zone_1", "exit_north").
        name                 — Human-readable label for display and warnings.
        node_type            — ZONE, GATE, or EXIT.
        capacity             — Maximum safe occupancy (persons). 0 = unknown.
        current_crowd        — Current person count in this node area.
        risk_score           — Current risk score [0–100] from the risk engine.
        predicted_risk_score — Predicted risk score [0–100] from the prediction engine.
        available            — False when this node is blocked/unsafe and must not
                               be included in any route.
    """

    node_id: str = Field(description="Unique node identifier.")
    name: str = Field(description="Human-readable node label.")
    node_type: NodeType = Field(description="Node category: ZONE, GATE, or EXIT.")
    capacity: int = Field(default=0, ge=0, description="Maximum safe occupancy (persons).")
    current_crowd: int = Field(default=0, ge=0, description="Current person count.")
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Current risk score 0–100.")
    predicted_risk_score: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Predicted risk score 0–100."
    )
    available: bool = Field(
        default=True, description="False when node is blocked and must be excluded from routing."
    )


class VenueEdge(BaseModel):
    """
    A directed, weighted edge (corridor or path) connecting two nodes.

    Cost components are used by the routing engine's cost function.
    A bidirectional corridor is represented as two directed edges.

    Fields:
        source_id            — ID of the source node.
        dest_id              — ID of the destination node.
        distance             — Physical length of the corridor in metres.
        capacity             — Maximum throughput in persons per unit time.
        current_crowd        — Current number of persons in this corridor.
        risk_score           — Current risk score [0–100] for this corridor.
        predicted_risk_score — Predicted risk score [0–100].
        available            — False when this corridor is physically blocked.
        bidirectional        — When True, the graph also stores the reverse edge.
        flow_direction       — Optional directional hint (e.g. "NORTH", "TOWARD_EXIT").
                               Used for ONE_WAY_REDIRECTION display; not enforced by routing.
    """

    source_id: str = Field(description="Source node ID.")
    dest_id: str = Field(description="Destination node ID.")
    distance: float = Field(gt=0.0, description="Corridor length in metres.")
    capacity: int = Field(default=1000, ge=0, description="Throughput capacity (persons).")
    current_crowd: int = Field(default=0, ge=0, description="Current persons in corridor.")
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Current risk 0–100.")
    predicted_risk_score: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Predicted risk 0–100."
    )
    available: bool = Field(default=True, description="False when corridor is physically blocked.")
    status: str = Field(default="OPEN", description="Connection status: OPEN, CLOSED, or RESTRICTED.")
    bidirectional: bool = Field(
        default=True,
        description="When True, add_edge() will also insert the reverse direction.",
    )
    flow_direction: Optional[str] = Field(
        default=None,
        description="Optional directional hint for display/enforcement (e.g. 'NORTH').",
    )

    @property
    def effective_capacity(self) -> int:
        """Calculate effective capacity based on status."""
        if self.status == "CLOSED" or not self.available:
            return 0
        if self.status == "RESTRICTED":
            return int(self.capacity * RESTRICTED_CAPACITY_FACTOR)
        return self.capacity



# ---------------------------------------------------------------------------
# Cost-function weights — fully configurable per request
# ---------------------------------------------------------------------------


class RoutingWeights(BaseModel):
    """
    Configurable multipliers for each component of the edge cost function.

    Cost formula::

        edge_cost = distance          * weight_distance
                  + combined_risk     * weight_current_risk     / 100 * 100
                  + combined_pred     * weight_predicted_risk   / 100 * 100
                  + congestion_ratio  * weight_congestion              * 100

    Higher weights make the engine more strongly avoid that dimension.

    Defaults:
        distance       1.0  — baseline: 1 unit per metre
        current_risk   2.0  — penalty: up to 200 units for CRITICAL (2× distance sensitivity)
        predicted_risk 1.5  — forward-looking: up to 150 units for predicted CRITICAL
        congestion     1.0  — up to 100 units at full congestion
    """

    weight_distance: float = Field(
        default=DEFAULT_WEIGHT_DISTANCE, gt=0.0, description="Cost per metre of corridor length."
    )
    weight_current_risk: float = Field(
        default=DEFAULT_WEIGHT_CURRENT_RISK, ge=0.0, description="Multiplier for current risk penalty."
    )
    weight_predicted_risk: float = Field(
        default=DEFAULT_WEIGHT_PREDICTED_RISK, ge=0.0, description="Multiplier for predicted risk penalty."
    )
    weight_congestion: float = Field(
        default=DEFAULT_WEIGHT_CONGESTION, ge=0.0, description="Multiplier for congestion penalty."
    )


# ---------------------------------------------------------------------------
# Routing result
# ---------------------------------------------------------------------------


class SafeRouteResult(BaseModel):
    """
    Complete output of the SafeRoutingEngine.

    Structured for:
    - Direct use by safety authorities.
    - Future What-If Simulator consumption (path, affected_zones, metrics).

    IMPORTANT:
    Check `is_available` before using any other field.
    When `is_available=False` no viable route was found.

    Fields:
        route_id             — Deterministic string ID for this result.
        source               — Starting node ID.
        destination          — Target node ID (or "ANY_EXIT" for find_safest_exit).
        path                 — Ordered list of node IDs from source to destination.
        total_distance       — Sum of edge distances along the path (metres).
        total_cost           — Aggregate Dijkstra cost (dimensionless, lower = better).
        safety_score         — 100 − maximum_zone_risk. Higher = safer.
        maximum_zone_risk    — Highest risk score encountered along the path (0–100).
        estimated_time_seconds — total_distance / WALKING_SPEED_MS.
        warnings             — Human-readable alerts about elevated risk or congestion.
        avoided_zones        — Node IDs with high risk that were NOT in the chosen path.
        route_type           — The RouteType intent that produced this result.
        is_available         — False when no viable route was found.
    """

    route_id: str = Field(description="Deterministic route identifier.")
    source: str = Field(description="Starting node ID.")
    destination: str = Field(description="Target node ID.")
    path: List[str] = Field(description="Ordered node IDs from source to destination.")
    total_distance: float = Field(description="Total corridor length in metres.")
    total_cost: float = Field(description="Total Dijkstra cost (lower = better/safer).")
    safety_score: float = Field(
        description="Safety score 0–100 (100 − maximum_zone_risk). Higher is safer."
    )
    maximum_zone_risk: float = Field(
        description="Highest risk score encountered along the path (0–100)."
    )
    estimated_time_seconds: float = Field(
        description="Estimated traversal time in seconds at crowd walking pace."
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Human-readable alerts about risk or congestion along the route.",
    )
    avoided_zones: List[str] = Field(
        default_factory=list,
        description="Zone IDs with elevated risk that are NOT in this path.",
    )
    route_type: RouteType = Field(description="The routing intent that produced this result.")
    is_available: bool = Field(
        default=True,
        description="False when no viable route was found. Check this before using any other field.",
    )
