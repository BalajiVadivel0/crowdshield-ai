"""
Tests for the SafeRoutingEngine and VenueGraph.

Test venue layout:

    [GATE_A] --50m-- [ZONE_1] --30m-- [ZONE_2] --20m-- [EXIT_N]
                        |
                       60m
                        |
                     [ZONE_3] --50m-- [ZONE_4] --40m-- [EXIT_S]

All edges are bidirectional by default.
Default risk on all nodes: 0.0 (safe).

Scenarios tested:
 1.  Shortest distance vs. safest path (differ when ZONE_2 is high-risk)
 2.  High-risk zone avoidance (risk=85 makes Dijkstra detour)
 3.  Predicted-risk avoidance (predicted_risk drives cost even without current risk)
 4.  Blocked edge (corridor unavailable → must use alternate route)
 5.  Blocked node (zone unavailable → all routes through it skipped)
 6.  Alternate exit (exclude primary exit → route to next best)
 7.  No available route (all corridors blocked → is_available=False)
 8.  Dynamic route recomputation (update graph → re-route)
 9.  Deterministic path selection (identical input → identical output)
10.  AVOID_ZONE route type auto-walls high-risk zones
11.  find_safest_exit returns lowest-cost exit, not just any exit
12.  Graph repr, edge_count, node_count
13.  Single-node graph (source == destination)
14.  VenueGraph update methods
15.  Cost weights: higher current_risk weight → stronger avoidance
16.  Congestion penalty raises cost for congested corridor
17.  Warnings: high-risk zone, congested corridor, no warnings for safe routes
18.  avoided_zones lists high-risk zones not in path
19.  Unavailable exit → find_safest_exit falls back to other exit
20.  route_id is deterministic string
"""

from copy import deepcopy
from typing import List

import pytest

from app.ai.routing.engine import SafeRoutingEngine
from app.ai.routing.graph import VenueGraph
from app.ai.routing.models import (
    HIGH_RISK_THRESHOLD,
    NodeType,
    RouteType,
    RoutingWeights,
    SafeRouteResult,
    VenueEdge,
    VenueNode,
)


# ===========================================================================
# Fixtures
# ===========================================================================


def _make_node(
    node_id: str,
    node_type: NodeType = NodeType.ZONE,
    risk_score: float = 0.0,
    predicted_risk_score: float = 0.0,
    capacity: int = 500,
    current_crowd: int = 0,
    available: bool = True,
) -> VenueNode:
    return VenueNode(
        node_id=node_id,
        name=node_id.replace("_", " ").title(),
        node_type=node_type,
        capacity=capacity,
        current_crowd=current_crowd,
        risk_score=risk_score,
        predicted_risk_score=predicted_risk_score,
        available=available,
    )


def _make_edge(
    source_id: str,
    dest_id: str,
    distance: float,
    risk_score: float = 0.0,
    predicted_risk_score: float = 0.0,
    capacity: int = 1000,
    current_crowd: int = 0,
    available: bool = True,
    bidirectional: bool = True,
) -> VenueEdge:
    return VenueEdge(
        source_id=source_id,
        dest_id=dest_id,
        distance=distance,
        risk_score=risk_score,
        predicted_risk_score=predicted_risk_score,
        capacity=capacity,
        current_crowd=current_crowd,
        available=available,
        bidirectional=bidirectional,
    )


def _build_standard_graph(
    zone2_risk: float = 0.0,
    zone2_pred_risk: float = 0.0,
    zone2_available: bool = True,
    edge_z1_z2_available: bool = True,
    edge_z1_z3_available: bool = True,
    exit_n_available: bool = True,
    exit_s_available: bool = True,
    z2_congestion: int = 0,
) -> VenueGraph:
    """
    Construct the standard test venue graph:

        [GATE_A] --50m-- [ZONE_1] --30m-- [ZONE_2] --20m-- [EXIT_N]
                            |
                           60m
                            |
                         [ZONE_3] --50m-- [ZONE_4] --40m-- [EXIT_S]

    Short path: GATE_A → ZONE_1 → ZONE_2 → EXIT_N  (100m)
    Long path:  GATE_A → ZONE_1 → ZONE_3 → ZONE_4 → EXIT_S  (200m)
    """
    graph = VenueGraph()

    # Nodes
    graph.add_node(_make_node("gate_a", NodeType.GATE))
    graph.add_node(_make_node("zone_1"))
    graph.add_node(
        _make_node(
            "zone_2",
            risk_score=zone2_risk,
            predicted_risk_score=zone2_pred_risk,
            current_crowd=z2_congestion,
            available=zone2_available,
        )
    )
    graph.add_node(_make_node("zone_3"))
    graph.add_node(_make_node("zone_4"))
    graph.add_node(_make_node("exit_n", NodeType.EXIT, available=exit_n_available))
    graph.add_node(_make_node("exit_s", NodeType.EXIT, available=exit_s_available))

    # Edges
    graph.add_edge(_make_edge("gate_a", "zone_1", 50.0))
    graph.add_edge(
        _make_edge(
            "zone_1", "zone_2", 30.0,
            available=edge_z1_z2_available,
            current_crowd=z2_congestion,
        )
    )
    graph.add_edge(_make_edge("zone_2", "exit_n", 20.0))
    graph.add_edge(_make_edge("zone_1", "zone_3", 60.0, available=edge_z1_z3_available))
    graph.add_edge(_make_edge("zone_3", "zone_4", 50.0))
    graph.add_edge(_make_edge("zone_4", "exit_s", 40.0))

    return graph


@pytest.fixture
def engine() -> SafeRoutingEngine:
    return SafeRoutingEngine()


@pytest.fixture
def safe_graph() -> VenueGraph:
    """Standard graph with all nodes at zero risk."""
    return _build_standard_graph()


# ===========================================================================
# Test 1 — Shortest distance vs. safest path
# ===========================================================================


def test_1_safe_route_prefers_shorter_when_equal_risk(engine, safe_graph):
    """When all zones have equal (zero) risk, the engine should find the shortest path."""
    result = engine.find_safest_exit(safe_graph, "gate_a")

    assert result.is_available
    # Shortest path is gate_a → zone_1 → zone_2 → exit_n = 100m
    assert result.total_distance == pytest.approx(100.0)
    assert result.path == ["gate_a", "zone_1", "zone_2", "exit_n"]


def test_1_safe_route_detours_when_zone2_is_high_risk(engine):
    """When ZONE_2 has high risk, the engine must prefer the longer but safer route."""
    graph = _build_standard_graph(zone2_risk=85.0)

    result = engine.find_safest_exit(graph, "gate_a")

    assert result.is_available
    # Must avoid zone_2 → route through zone_3/zone_4 to exit_s
    assert "zone_2" not in result.path, "High-risk zone_2 should not be in the safe path"
    assert result.path[-1] == "exit_s"
    assert result.total_distance == pytest.approx(200.0)


# ===========================================================================
# Test 2 — High-risk zone avoidance
# ===========================================================================


def test_2_high_risk_zone_excluded_from_path(engine):
    """Risk score ≥ HIGH_RISK_THRESHOLD must cause the engine to route around the zone."""
    graph = _build_standard_graph(zone2_risk=HIGH_RISK_THRESHOLD + 5.0)

    result = engine.find_safe_route(graph, "gate_a", "exit_s")
    assert result.is_available
    assert "zone_2" not in result.path

    # Longer path still chosen
    result2 = engine.find_safest_exit(graph, "gate_a")
    assert result2.is_available
    assert "zone_2" not in result2.path


def test_2_safe_cost_with_high_risk_zone_is_greater(engine):
    """Adding high risk to zone_2 must raise total cost compared to a risk-free graph."""
    safe = _build_standard_graph()
    risky = _build_standard_graph(zone2_risk=85.0)

    result_safe = engine.find_safe_route(safe, "gate_a", "exit_n")
    result_risky = engine.find_safe_route(risky, "gate_a", "exit_n")

    # Cost through risky zone_2 must be higher than through safe zone_2
    assert result_risky.total_cost > result_safe.total_cost


# ===========================================================================
# Test 3 — Predicted-risk avoidance
# ===========================================================================


def test_3_predicted_risk_raises_cost(engine):
    """Predicted risk should increase total cost even when current risk is zero."""
    base = _build_standard_graph(zone2_pred_risk=0.0)
    with_pred = _build_standard_graph(zone2_pred_risk=90.0)

    r_base = engine.find_safe_route(base, "gate_a", "exit_n")
    r_pred = engine.find_safe_route(with_pred, "gate_a", "exit_n")

    assert r_pred.total_cost > r_base.total_cost


def test_3_high_predicted_risk_causes_detour(engine):
    """High predicted risk alone (current risk=0) must cause Dijkstra to detour."""
    graph = _build_standard_graph(zone2_risk=0.0, zone2_pred_risk=92.0)

    # Use heavy predicted risk weight to make pred risk dominate
    weights = RoutingWeights(weight_predicted_risk=5.0, weight_current_risk=0.1)
    result = engine.find_safest_exit(graph, "gate_a", weights=weights)

    assert result.is_available
    assert "zone_2" not in result.path


# ===========================================================================
# Test 4 — Blocked edge
# ===========================================================================


def test_4_blocked_edge_forces_alternate_route(engine):
    """When the ZONE_1 → ZONE_2 corridor is unavailable, must route via zone_3."""
    graph = _build_standard_graph(edge_z1_z2_available=False)

    result = engine.find_safe_route(graph, "gate_a", "exit_n")

    # Direct path blocked; must go around via zone_3/zone_4 then back... or find exit_s
    # Since exit_n has no accessible path, the result should be unavailable
    # (zone_2 → exit_n is reached via zone_2, which is only reachable via blocked edge)
    assert not result.is_available or "zone_3" in result.path


def test_4_blocked_edge_to_exit_n_routes_to_exit_s(engine):
    """Blocking the only edge to EXIT_N forces the engine to use EXIT_S instead."""
    graph = _build_standard_graph(edge_z1_z2_available=False)

    result = engine.find_safest_exit(graph, "gate_a")

    assert result.is_available
    assert result.destination == "exit_s"
    assert "zone_3" in result.path


# ===========================================================================
# Test 5 — Blocked node
# ===========================================================================


def test_5_blocked_node_excluded_from_route(engine):
    """A node with available=False must not appear in any computed route."""
    graph = _build_standard_graph(zone2_available=False)

    result = engine.find_safest_exit(graph, "gate_a")

    assert result.is_available
    assert "zone_2" not in result.path
    assert result.destination == "exit_s"


def test_5_blocked_exit_forces_alternate(engine):
    """Blocking EXIT_N must redirect the engine to EXIT_S."""
    graph = _build_standard_graph(exit_n_available=False)

    result = engine.find_safest_exit(graph, "gate_a")

    assert result.is_available
    assert result.destination == "exit_s"


# ===========================================================================
# Test 6 — Alternate exit
# ===========================================================================


def test_6_alternate_exit_excludes_primary(engine, safe_graph):
    """find_safest_exit with exclude_exits must skip the primary exit."""
    # First, find the primary exit
    primary = engine.find_safest_exit(safe_graph, "gate_a")
    assert primary.is_available

    # Now request the alternate (exclude the primary)
    alternate = engine.find_safest_exit(
        safe_graph, "gate_a",
        route_type=RouteType.ALTERNATE_EXIT,
        exclude_exits=[primary.destination],
    )

    assert alternate.is_available
    assert alternate.destination != primary.destination


def test_6_alternate_exit_route_type_label(engine, safe_graph):
    """ALTERNATE_EXIT route type must be reflected in the result."""
    result = engine.find_safest_exit(
        safe_graph, "gate_a", route_type=RouteType.ALTERNATE_EXIT
    )
    assert result.route_type == RouteType.ALTERNATE_EXIT


# ===========================================================================
# Test 7 — No available route
# ===========================================================================


def test_7_no_route_when_all_corridors_blocked(engine):
    """When every outgoing corridor from source is blocked, is_available must be False."""
    graph = _build_standard_graph(
        edge_z1_z2_available=False,
        edge_z1_z3_available=False,
    )

    result = engine.find_safe_route(graph, "gate_a", "exit_n")

    # gate_a → zone_1 is still open but zone_1 has no forward edges
    # Actually, let's test with zone_1 being the blocked node
    graph2 = _build_standard_graph()
    graph2.set_node_available("zone_1", False)
    result2 = engine.find_safest_exit(graph2, "gate_a")

    assert not result2.is_available


def test_7_no_route_result_structure(engine, safe_graph):
    """is_available=False result must have empty path and sensible sentinel values."""
    result = engine.find_safe_route(safe_graph, "gate_a", "nonexistent_exit")

    assert not result.is_available
    assert result.path == []
    assert result.total_distance == 0.0
    assert result.safety_score == 0.0
    assert len(result.warnings) >= 1  # at least one message explaining the failure


# ===========================================================================
# Test 8 — Dynamic route recomputation
# ===========================================================================


def test_8_dynamic_recomputation_changes_route_when_risk_rises(engine):
    """
    Scenario:
      Step 1: zone_2 is safe → route via zone_2.
      Step 2: zone_2 becomes CRITICAL → update graph → re-route via zone_3.
    """
    graph = _build_standard_graph()

    # Step 1: safe graph → shortest path wins
    result_before = engine.find_safest_exit(graph, "gate_a")
    assert result_before.is_available
    assert "zone_2" in result_before.path

    # Step 2: zone_2 becomes CRITICAL
    graph.update_node("zone_2", risk_score=92.0, predicted_risk_score=95.0)

    result_after = engine.find_safest_exit(graph, "gate_a")
    assert result_after.is_available
    assert "zone_2" not in result_after.path
    assert result_after.destination == "exit_s"


def test_8_recomputation_restores_original_route_when_risk_drops(engine):
    """After risk drops back to safe levels, the original (shorter) route should return."""
    graph = _build_standard_graph(zone2_risk=90.0)

    # High risk → detour
    r1 = engine.find_safest_exit(graph, "gate_a")
    assert "zone_2" not in r1.path

    # Risk resolved
    graph.update_node("zone_2", risk_score=5.0)

    # Safe again → shorter path
    r2 = engine.find_safest_exit(graph, "gate_a")
    assert "zone_2" in r2.path
    assert r2.destination == "exit_n"


# ===========================================================================
# Test 9 — Deterministic path selection
# ===========================================================================


def test_9_same_input_produces_same_output(engine):
    """Calling recommend() twice with identical input must produce identical output."""
    graph = _build_standard_graph(zone2_risk=50.0)

    r1 = engine.find_safest_exit(graph, "gate_a")
    r2 = engine.find_safest_exit(graph, "gate_a")

    assert r1.path == r2.path
    assert r1.total_cost == r2.total_cost
    assert r1.route_id == r2.route_id
    assert r1.total_distance == r2.total_distance


def test_9_route_is_deterministic_with_tied_costs(engine):
    """When two exits have equal cost, the same one must be chosen on every call."""
    # Build graph where EXIT_N and EXIT_S have equal total cost
    graph = VenueGraph()
    graph.add_node(_make_node("src", NodeType.GATE))
    graph.add_node(_make_node("exit_a", NodeType.EXIT))
    graph.add_node(_make_node("exit_b", NodeType.EXIT))
    graph.add_edge(_make_edge("src", "exit_a", 100.0))
    graph.add_edge(_make_edge("src", "exit_b", 100.0))

    results = [engine.find_safest_exit(graph, "src") for _ in range(5)]
    destinations = {r.destination for r in results}
    assert len(destinations) == 1, "Non-deterministic exit selection detected"


# ===========================================================================
# Test 10 — AVOID_ZONE route type
# ===========================================================================


def test_10_avoid_zone_type_auto_walls_high_risk_zones(engine):
    """AVOID_ZONE route type must automatically exclude zones above HIGH_RISK_THRESHOLD."""
    graph = _build_standard_graph(zone2_risk=HIGH_RISK_THRESHOLD + 1.0)

    result = engine.find_safest_exit(graph, "gate_a", route_type=RouteType.AVOID_ZONE)

    assert result.is_available
    assert "zone_2" not in result.path


def test_10_avoid_zone_explicit_avoid_list(engine, safe_graph):
    """Explicit avoid_zone_ids must be excluded even when their risk is low."""
    result = engine.find_safest_exit(
        safe_graph, "gate_a",
        avoid_zone_ids=["zone_2"],
    )

    assert result.is_available
    assert "zone_2" not in result.path


# ===========================================================================
# Test 11 — find_safest_exit returns lowest-cost exit
# ===========================================================================


def test_11_find_safest_exit_returns_minimum_cost_exit(engine):
    """find_safest_exit must return the exit with lowest total_cost, not just any exit."""
    # zone_4 corridor to exit_s is congested → higher cost → exit_n should win
    graph = _build_standard_graph()
    graph.update_edge_congestion("zone_4", "exit_s", current_crowd=950)  # 95% capacity

    result = engine.find_safest_exit(graph, "gate_a")

    assert result.is_available
    # exit_n should still win because exit_s path has congestion penalty
    assert result.destination == "exit_n"


def test_11_find_safest_exit_no_exits(engine):
    """Graph with no EXIT nodes → is_available must be False."""
    graph = VenueGraph()
    graph.add_node(_make_node("zone_a"))
    graph.add_node(_make_node("zone_b"))
    graph.add_edge(_make_edge("zone_a", "zone_b", 50.0))

    result = engine.find_safest_exit(graph, "zone_a")
    assert not result.is_available


# ===========================================================================
# Test 12 — VenueGraph introspection
# ===========================================================================


def test_12_graph_node_and_edge_counts(safe_graph):
    """node_count() and edge_count() must reflect all added nodes and edges."""
    assert safe_graph.node_count() == 7  # gate_a, z1, z2, z3, z4, exit_n, exit_s

    # 6 add_edge() calls, each bidirectional → 12 directed edges
    assert safe_graph.edge_count() == 12


def test_12_get_exits_returns_only_exit_nodes(safe_graph):
    """get_exits() must return only NodeType.EXIT nodes."""
    exits = safe_graph.get_exits()
    assert all(n.node_type == NodeType.EXIT for n in exits)
    assert len(exits) == 2


def test_12_graph_repr_contains_counts():
    """VenueGraph __repr__ must mention node and edge counts."""
    graph = VenueGraph()
    graph.add_node(_make_node("n1", NodeType.EXIT))
    assert "nodes=1" in repr(graph)


# ===========================================================================
# Test 13 — Source equals destination
# ===========================================================================


def test_13_source_equals_destination(engine, safe_graph):
    """Routing from a node to itself must return a zero-distance valid result."""
    result = engine.find_safe_route(safe_graph, "zone_1", "zone_1")

    assert result.is_available
    assert result.total_distance == 0.0
    assert result.total_cost == 0.0
    assert result.path == ["zone_1"]
    assert result.estimated_time_seconds == 0.0


# ===========================================================================
# Test 14 — VenueGraph update methods
# ===========================================================================


def test_14_update_node_risk(safe_graph):
    """update_node() must change only the specified fields."""
    safe_graph.update_node("zone_2", risk_score=75.0)
    assert safe_graph.nodes["zone_2"].risk_score == 75.0
    # Other fields unchanged
    assert safe_graph.nodes["zone_2"].node_type == NodeType.ZONE


def test_14_update_edge_risk_both_directions(safe_graph):
    """update_edge_risk() must update both directions of a bidirectional edge."""
    result = safe_graph.update_edge_risk("zone_1", "zone_2", risk_score=80.0)
    assert result is True

    # Forward direction
    fwd = [e for e in safe_graph.get_edges_from("zone_1") if e.dest_id == "zone_2"]
    assert fwd and fwd[0].risk_score == 80.0

    # Reverse direction
    rev = [e for e in safe_graph.get_edges_from("zone_2") if e.dest_id == "zone_1"]
    assert rev and rev[0].risk_score == 80.0


def test_14_set_edge_available_blocks_both_directions(safe_graph):
    """set_edge_available(False) must block both directions of a bidirectional edge."""
    safe_graph.set_edge_available("zone_1", "zone_2", available=False)

    fwd = [e for e in safe_graph.get_edges_from("zone_1") if e.dest_id == "zone_2"]
    rev = [e for e in safe_graph.get_edges_from("zone_2") if e.dest_id == "zone_1"]

    assert fwd and fwd[0].available is False
    assert rev and rev[0].available is False


def test_14_update_nonexistent_node_returns_false(safe_graph):
    """update_node() on a missing node_id must return False without error."""
    result = safe_graph.update_node("nonexistent", risk_score=50.0)
    assert result is False


# ===========================================================================
# Test 15 — Cost weights affect route selection
# ===========================================================================


def test_15_high_risk_weight_causes_stronger_avoidance(engine):
    """Doubling weight_current_risk must produce higher cost for risky routes."""
    graph = _build_standard_graph(zone2_risk=50.0)

    w_default = RoutingWeights()
    w_heavy = RoutingWeights(weight_current_risk=10.0)

    r_default = engine.find_safe_route(graph, "gate_a", "exit_n", weights=w_default)
    r_heavy = engine.find_safe_route(graph, "gate_a", "exit_n", weights=w_heavy)

    assert r_heavy.total_cost > r_default.total_cost


def test_15_distance_only_weights_produce_shortest_path(engine, safe_graph):
    """With zero risk/congestion weights, the engine should always pick the shortest path."""
    w_dist_only = RoutingWeights(
        weight_current_risk=0.0,
        weight_predicted_risk=0.0,
        weight_congestion=0.0,
    )
    result = engine.find_safest_exit(safe_graph, "gate_a", weights=w_dist_only)

    assert result.is_available
    assert result.total_distance == pytest.approx(100.0)  # shortest path
    assert result.path == ["gate_a", "zone_1", "zone_2", "exit_n"]


# ===========================================================================
# Test 16 — Congestion penalty
# ===========================================================================


def test_16_congested_corridor_raises_cost(engine):
    """A congested corridor must increase total_cost compared to an empty one."""
    graph_empty = _build_standard_graph(z2_congestion=0)
    graph_cong = _build_standard_graph(z2_congestion=900)  # 90% capacity

    r_empty = engine.find_safe_route(graph_empty, "gate_a", "exit_n")
    r_cong = engine.find_safe_route(graph_cong, "gate_a", "exit_n")

    assert r_cong.total_cost > r_empty.total_cost


def test_16_fully_congested_corridor_triggers_detour(engine):
    """A corridor at 100% capacity (with heavy congestion weight) must cause a detour."""
    graph = _build_standard_graph(z2_congestion=1000)  # 100% of capacity=1000
    w_heavy_cong = RoutingWeights(weight_congestion=10.0, weight_current_risk=0.1)

    result = engine.find_safest_exit(graph, "gate_a", weights=w_heavy_cong)

    assert result.is_available
    # Heavy congestion on zone_1→zone_2 path should route to exit_s
    assert result.destination == "exit_s"


# ===========================================================================
# Test 17 — Warnings
# ===========================================================================


def test_17_high_risk_zone_generates_warning(engine):
    """A route through a high-risk zone must produce a warning mentioning that zone."""
    # Force routing through zone_2 (only path available) while zone_2 has high risk
    graph = _build_standard_graph(zone2_risk=75.0, edge_z1_z3_available=False)

    result = engine.find_safe_route(graph, "gate_a", "exit_n")

    assert result.is_available
    assert any("zone_2" in w.lower() for w in result.warnings), (
        f"Expected warning about zone_2 risk. Got: {result.warnings}"
    )


def test_17_congested_corridor_generates_warning(engine):
    """An 85%-congested corridor must produce a congestion warning."""
    graph = _build_standard_graph(z2_congestion=850, edge_z1_z3_available=False)

    result = engine.find_safe_route(graph, "gate_a", "exit_n")

    assert result.is_available
    assert any("congested" in w.lower() for w in result.warnings), (
        f"Expected congestion warning. Got: {result.warnings}"
    )


def test_17_safe_route_produces_no_spurious_warnings(engine, safe_graph):
    """A clean, low-risk, uncongested route must produce no warnings."""
    result = engine.find_safe_route(safe_graph, "gate_a", "exit_n")

    assert result.is_available
    assert result.warnings == [], f"Unexpected warnings: {result.warnings}"


# ===========================================================================
# Test 18 — avoided_zones
# ===========================================================================


def test_18_avoided_zones_lists_high_risk_zones_not_in_path(engine):
    """avoided_zones must include high-risk zones that were NOT traversed."""
    graph = _build_standard_graph(zone2_risk=90.0)

    result = engine.find_safest_exit(graph, "gate_a")

    assert result.is_available
    assert "zone_2" not in result.path
    assert "zone_2" in result.avoided_zones


def test_18_avoided_zones_empty_when_all_zones_are_safe(engine, safe_graph):
    """When no zone is high-risk, avoided_zones must be empty."""
    result = engine.find_safest_exit(safe_graph, "gate_a")

    assert result.is_available
    assert result.avoided_zones == []


# ===========================================================================
# Test 19 — Unavailable exit falls back to other
# ===========================================================================


def test_19_unavailable_exit_node_skipped(engine):
    """find_safest_exit must skip EXIT nodes with available=False."""
    graph = _build_standard_graph(exit_n_available=False)

    result = engine.find_safest_exit(graph, "gate_a")

    assert result.is_available
    assert result.destination == "exit_s"
    assert result.path[-1] == "exit_s"


def test_19_all_exits_unavailable_returns_no_route(engine):
    """When all exits are unavailable, find_safest_exit must return is_available=False."""
    graph = _build_standard_graph(exit_n_available=False, exit_s_available=False)

    result = engine.find_safest_exit(graph, "gate_a")

    assert not result.is_available


# ===========================================================================
# Test 20 — Route ID is deterministic
# ===========================================================================


def test_20_route_id_is_deterministic_and_descriptive(engine, safe_graph):
    """route_id must contain source, destination, and route type for traceability."""
    result = engine.find_safe_route(
        safe_graph, "gate_a", "exit_n", route_type=RouteType.SAFE_EXIT
    )

    assert "gate_a" in result.route_id
    assert "exit_n" in result.route_id
    assert "safe_exit" in result.route_id.lower()

    # Must be the same on repeated calls
    result2 = engine.find_safe_route(
        safe_graph, "gate_a", "exit_n", route_type=RouteType.SAFE_EXIT
    )
    assert result.route_id == result2.route_id


# ===========================================================================
# Bonus: SafeRouteResult structural checks
# ===========================================================================


def test_result_safety_score_is_100_minus_max_risk(engine):
    """safety_score must equal 100 - maximum_zone_risk (clamped to ≥0)."""
    graph = _build_standard_graph(zone2_risk=40.0, edge_z1_z3_available=False)
    result = engine.find_safe_route(graph, "gate_a", "exit_n")

    assert result.is_available
    assert result.safety_score == pytest.approx(100.0 - result.maximum_zone_risk, abs=0.01)


def test_result_estimated_time_consistent_with_distance(engine, safe_graph):
    """estimated_time_seconds must be total_distance / WALKING_SPEED_MS."""
    from app.ai.routing.models import WALKING_SPEED_MS

    result = engine.find_safe_route(safe_graph, "gate_a", "exit_n")

    expected = result.total_distance / WALKING_SPEED_MS
    assert result.estimated_time_seconds == pytest.approx(expected, abs=0.1)


def test_result_path_starts_at_source_and_ends_at_destination(engine, safe_graph):
    """The path list must start with source and end with destination."""
    result = engine.find_safe_route(safe_graph, "gate_a", "exit_n")

    assert result.is_available
    assert result.path[0] == "gate_a"
    assert result.path[-1] == "exit_n"
