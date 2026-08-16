"""
SafeRoutingEngine — Dijkstra-based safest-path finder for crowd evacuation.

Answers the question:
    "Which evacuation route is safest right now?"

NOT: "Which route is shortest?"

The engine penalises edges by:
    distance           — physical length of the corridor
    current risk       — live risk score from the intelligence pipeline
    predicted risk     — forward-looking risk score
    congestion         — current crowd / corridor capacity

All logic is deterministic and stateless — the same graph and weights
always produce the same result. The graph is NEVER mutated by the engine.

Design:
- Dijkstra's algorithm with a priority queue (heapq).
- Tie-breaking is lexicographic on node_id to ensure determinism.
- Blocked nodes and explicit avoid_zone_ids are skipped as walls.
- AVOID_ZONE route type automatically walls off high-risk zones.
- Event-level routing (find_safest_exit) tries all available exits and
  returns the one with the lowest total cost.

DO NOT modify Member 1 modules.
"""

import heapq
from typing import Dict, List, Optional, Set, Tuple

from app.ai.routing.graph import VenueGraph
from app.ai.routing.models import (
    CRITICAL_RISK_PENALTY,
    CRITICAL_RISK_THRESHOLD,
    HIGH_CONGESTION_THRESHOLD,
    HIGH_RISK_THRESHOLD,
    LONG_ROUTE_THRESHOLD_SECONDS,
    UNAVAILABLE_ROUTE_COST,
    WALKING_SPEED_MS,
    NodeType,
    RouteType,
    RoutingWeights,
    SafeRouteResult,
    VenueEdge,
    VenueNode,
)


class SafeRoutingEngine:
    """
    Stateless, deterministic engine for computing safest evacuation routes.

    Usage::

        engine = SafeRoutingEngine()
        result = engine.find_safe_route(graph, "zone_1", "exit_north")
        result = engine.find_safest_exit(graph, "zone_1")

    The engine does NOT store state between calls. The VenueGraph is the
    sole source of truth — update it externally and call recommend() again
    to get dynamically recomputed routes.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_safe_route(
        self,
        graph: VenueGraph,
        source_id: str,
        destination_id: str,
        route_type: RouteType = RouteType.SAFE_EXIT,
        weights: Optional[RoutingWeights] = None,
        avoid_zone_ids: Optional[List[str]] = None,
    ) -> SafeRouteResult:
        """
        Find the safest route from source_id to destination_id.

        Safest ≠ Shortest. The cost function penalises high-risk and congested
        corridors, so Dijkstra may choose a longer physical path that avoids
        danger zones.

        Args:
            graph:           The current venue graph.
            source_id:       Starting node ID.
            destination_id:  Target node ID.
            route_type:      SAFE_EXIT, ALTERNATE_EXIT, AVOID_ZONE,
                             or ONE_WAY_REDIRECTION.
            weights:         Custom cost weights. Defaults to RoutingWeights().
            avoid_zone_ids:  Additional node IDs to treat as walls (on top of
                             any automatic avoidance for AVOID_ZONE type).

        Returns:
            SafeRouteResult. Check is_available before using path/metrics.
        """
        if weights is None:
            weights = RoutingWeights()

        # --- Input validation ---
        if source_id not in graph.nodes:
            return self._no_route(
                source_id, destination_id, route_type,
                f"Source node '{source_id}' does not exist in the venue graph.",
            )
        if destination_id not in graph.nodes:
            return self._no_route(
                source_id, destination_id, route_type,
                f"Destination node '{destination_id}' does not exist in the venue graph.",
            )

        # --- Trivial case ---
        if source_id == destination_id:
            node = graph.nodes[source_id]
            return SafeRouteResult(
                route_id=f"route_{source_id}_{destination_id}_{route_type.value.lower()}",
                source=source_id,
                destination=destination_id,
                path=[source_id],
                total_distance=0.0,
                total_cost=0.0,
                safety_score=round(max(0.0, 100.0 - node.risk_score), 2),
                maximum_zone_risk=node.risk_score,
                estimated_time_seconds=0.0,
                warnings=[],
                avoided_zones=[],
                route_type=route_type,
                is_available=True,
            )

        # --- Build blocked-node set ---
        blocked: Set[str] = set(avoid_zone_ids or [])

        # AVOID_ZONE: auto-wall all high-risk zones
        if route_type == RouteType.AVOID_ZONE:
            for nid, node in graph.nodes.items():
                if node.node_type == NodeType.ZONE and node.risk_score >= HIGH_RISK_THRESHOLD:
                    blocked.add(nid)

        # Never block source or destination
        blocked.discard(source_id)
        blocked.discard(destination_id)

        # --- Dijkstra ---
        distances, previous = self._dijkstra(graph, source_id, blocked, weights)

        if distances.get(destination_id, float("inf")) == float("inf"):
            return self._no_route(
                source_id, destination_id, route_type,
                "No viable route to the destination — all paths are blocked or unavailable.",
            )

        # --- Reconstruct path ---
        path = self._reconstruct_path(previous, source_id, destination_id)
        if not path:
            return self._no_route(
                source_id, destination_id, route_type,
                "Path reconstruction failed — internal routing error.",
            )

        # --- Collect avoided high-risk zones (in graph but NOT in path) ---
        avoided_zones = sorted(
            nid
            for nid, node in graph.nodes.items()
            if node.node_type == NodeType.ZONE
            and node.risk_score >= HIGH_RISK_THRESHOLD
            and nid not in path
        )

        return self._build_result(
            graph,
            path,
            source_id,
            destination_id,
            distances[destination_id],
            route_type,
            avoided_zones,
        )

    def find_safest_exit(
        self,
        graph: VenueGraph,
        source_id: str,
        route_type: RouteType = RouteType.SAFE_EXIT,
        weights: Optional[RoutingWeights] = None,
        avoid_zone_ids: Optional[List[str]] = None,
        exclude_exits: Optional[List[str]] = None,
    ) -> SafeRouteResult:
        """
        Find the safest available exit from source_id.

        Tries every available EXIT node in the graph and returns the route
        with the lowest total Dijkstra cost (i.e., the safest reachable exit,
        not necessarily the closest one).

        Args:
            graph:          The current venue graph.
            source_id:      Starting node ID.
            route_type:     Routing intent label.
            weights:        Custom cost weights.
            avoid_zone_ids: Nodes to treat as walls.
            exclude_exits:  Exit node IDs to skip (for ALTERNATE_EXIT routing).

        Returns:
            SafeRouteResult to the best exit. Check is_available.
        """
        exits = graph.get_exits()

        if not exits:
            return self._no_route(
                source_id, "ANY_EXIT", route_type,
                "No available EXIT nodes found in the venue graph.",
            )

        excluded: Set[str] = set(exclude_exits or [])

        best: Optional[SafeRouteResult] = None
        for exit_node in exits:
            if exit_node.node_id in excluded:
                continue
            result = self.find_safe_route(
                graph, source_id, exit_node.node_id, route_type, weights, avoid_zone_ids
            )
            if not result.is_available:
                continue
            if best is None or result.total_cost < best.total_cost:
                best = result

        if best is None:
            return self._no_route(
                source_id, "ANY_EXIT", route_type,
                "All exits are unreachable from the source node.",
            )

        return best

    # ------------------------------------------------------------------
    # Dijkstra's algorithm
    # ------------------------------------------------------------------

    def _dijkstra(
        self,
        graph: VenueGraph,
        source_id: str,
        blocked_nodes: Set[str],
        weights: RoutingWeights,
    ) -> Tuple[Dict[str, float], Dict[str, Optional[str]]]:
        """
        Standard Dijkstra's algorithm with a min-heap priority queue.

        Tie-breaking on (cost, node_id) ensures deterministic output when
        multiple nodes have the same tentative distance.

        Returns:
            distances: dict mapping node_id → minimum cost from source.
            previous:  dict mapping node_id → predecessor node_id in
                       the shortest path tree.
        """
        distances: Dict[str, float] = {nid: float("inf") for nid in graph.nodes}
        previous: Dict[str, Optional[str]] = {nid: None for nid in graph.nodes}
        distances[source_id] = 0.0

        # Heap entries: (cost, node_id) — node_id breaks ties deterministically
        heap: List[Tuple[float, str]] = [(0.0, source_id)]
        visited: Set[str] = set()

        while heap:
            cost, current_id = heapq.heappop(heap)

            if current_id in visited:
                continue
            visited.add(current_id)

            for edge in graph.get_edges_from(current_id):
                if not edge.available:
                    continue

                neighbor_id = edge.dest_id
                if neighbor_id in blocked_nodes:
                    continue

                neighbor_node = graph.nodes.get(neighbor_id)
                if neighbor_node is None or not neighbor_node.available:
                    continue

                edge_cost = self._compute_edge_cost(edge, neighbor_node, weights)
                new_cost = cost + edge_cost

                if new_cost < distances[neighbor_id]:
                    distances[neighbor_id] = new_cost
                    previous[neighbor_id] = current_id
                    heapq.heappush(heap, (new_cost, neighbor_id))

        return distances, previous

    # ------------------------------------------------------------------
    # Cost function — no magic numbers (all constants from models.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_edge_cost(
        edge: VenueEdge,
        dest_node: VenueNode,
        weights: RoutingWeights,
    ) -> float:
        """
        Compute the cost of traversing one edge to a destination node.

        Cost components:
        1. Distance    — edge.distance * weight_distance
        2. Current risk  — max(edge.risk_score, dest_node.risk_score) scaled × weight
        3. Predicted risk — max(edge.predicted_risk_score, dest_node.predicted_risk_score) × weight
        4. Congestion  — (current_crowd / capacity) × 100 × weight
        5. Critical penalty — extra penalty when risk ≥ CRITICAL_RISK_THRESHOLD

        By taking the max of edge and node risk, risk that is localised on a
        corridor OR in a zone is equally penalised.
        """
        # 1. Distance
        dist_cost = edge.distance * weights.weight_distance

        # 2. Combined current risk (edge + destination node)
        combined_risk = max(edge.risk_score, dest_node.risk_score)
        risk_cost = (combined_risk / 100.0) * 100.0 * weights.weight_current_risk

        # 3. Combined predicted risk
        combined_pred = max(edge.predicted_risk_score, dest_node.predicted_risk_score)
        pred_cost = (combined_pred / 100.0) * 100.0 * weights.weight_predicted_risk

        # 4. Congestion
        if edge.capacity > 0:
            congestion_ratio = min(1.0, edge.current_crowd / edge.capacity)
        else:
            congestion_ratio = 1.0  # zero-capacity corridor = fully congested
        cong_cost = congestion_ratio * 100.0 * weights.weight_congestion

        # 5. Critical risk penalty (strongly discourages but does not hard-block)
        critical_penalty = 0.0
        if combined_risk >= CRITICAL_RISK_THRESHOLD:
            critical_penalty = CRITICAL_RISK_PENALTY

        return dist_cost + risk_cost + pred_cost + cong_cost + critical_penalty

    # ------------------------------------------------------------------
    # Path reconstruction
    # ------------------------------------------------------------------

    @staticmethod
    def _reconstruct_path(
        previous: Dict[str, Optional[str]],
        source_id: str,
        dest_id: str,
    ) -> List[str]:
        """
        Walk the predecessor dict backwards from dest to source.

        Returns an empty list if no path was found (dest never reached source).
        """
        path: List[str] = []
        current: Optional[str] = dest_id

        while current is not None:
            path.append(current)
            current = previous.get(current)

        path.reverse()

        if not path or path[0] != source_id:
            return []  # destination is unreachable

        return path

    # ------------------------------------------------------------------
    # Result builder
    # ------------------------------------------------------------------

    def _build_result(
        self,
        graph: VenueGraph,
        path: List[str],
        source_id: str,
        destination_id: str,
        total_cost: float,
        route_type: RouteType,
        avoided_zones: List[str],
    ) -> SafeRouteResult:
        """Compute all metrics for a successfully found path and assemble the result."""

        # Total physical distance and max risk along path
        total_distance = 0.0
        max_risk = 0.0

        # Include risk of source node
        source_node = graph.nodes.get(source_id)
        if source_node:
            max_risk = max(max_risk, source_node.risk_score)

        # Walk edges along the path
        for i in range(len(path) - 1):
            src, dst = path[i], path[i + 1]
            for edge in graph.get_edges_from(src):
                if edge.dest_id == dst:
                    total_distance += edge.distance
                    break

            dest_node = graph.nodes.get(dst)
            if dest_node:
                max_risk = max(max_risk, dest_node.risk_score)

        # Safety score
        safety_score = round(max(0.0, 100.0 - max_risk), 2)

        # Estimated traversal time
        estimated_time = total_distance / WALKING_SPEED_MS

        # Warnings
        warnings = self._generate_warnings(graph, path, estimated_time)

        return SafeRouteResult(
            route_id=(
                f"route_{source_id}_{destination_id}_{route_type.value.lower()}"
            ),
            source=source_id,
            destination=destination_id,
            path=path,
            total_distance=round(total_distance, 2),
            total_cost=round(total_cost, 3),
            safety_score=safety_score,
            maximum_zone_risk=round(max_risk, 2),
            estimated_time_seconds=round(estimated_time, 1),
            warnings=warnings,
            avoided_zones=avoided_zones,
            route_type=route_type,
            is_available=True,
        )

    # ------------------------------------------------------------------
    # Warning generation
    # ------------------------------------------------------------------

    def _generate_warnings(
        self,
        graph: VenueGraph,
        path: List[str],
        estimated_time_seconds: float,
    ) -> List[str]:
        """
        Produce human-readable warnings for risk, congestion, and duration.

        Warnings are informational — they do NOT prevent routing. Authorities
        should review warnings before acting on a route recommendation.
        """
        warnings: List[str] = []

        for node_id in path:
            node = graph.nodes.get(node_id)
            if node is None or node.node_type != NodeType.ZONE:
                continue

            if node.risk_score >= CRITICAL_RISK_THRESHOLD:
                warnings.append(
                    f"Route passes through CRITICAL zone '{node_id}' "
                    f"(risk score {node.risk_score:.0f}/100). "
                    "No safer path was available. Exercise extreme caution."
                )
            elif node.risk_score >= HIGH_RISK_THRESHOLD:
                warnings.append(
                    f"Route passes through elevated-risk zone '{node_id}' "
                    f"(risk score {node.risk_score:.0f}/100). Monitor conditions closely."
                )

        # Check corridor congestion
        for i in range(len(path) - 1):
            src, dst = path[i], path[i + 1]
            for edge in graph.get_edges_from(src):
                if edge.dest_id == dst:
                    if edge.capacity > 0:
                        ratio = edge.current_crowd / edge.capacity
                        if ratio >= HIGH_CONGESTION_THRESHOLD:
                            warnings.append(
                                f"Corridor '{src}' → '{dst}' is congested "
                                f"({ratio:.0%} of capacity). "
                                "Throughput may be limited."
                            )
                    break

        # Duration warning
        if estimated_time_seconds > LONG_ROUTE_THRESHOLD_SECONDS:
            minutes = estimated_time_seconds / 60.0
            warnings.append(
                f"Extended evacuation time estimated (~{minutes:.0f} minutes). "
                "Consider activating additional exits to reduce load."
            )

        return warnings

    # ------------------------------------------------------------------
    # Unavailable route sentinel
    # ------------------------------------------------------------------

    @staticmethod
    def _no_route(
        source_id: str,
        destination_id: str,
        route_type: RouteType,
        message: str,
    ) -> SafeRouteResult:
        """Return a SafeRouteResult that signals no viable route was found."""
        return SafeRouteResult(
            route_id=f"route_{source_id}_{destination_id}_unavailable",
            source=source_id,
            destination=destination_id,
            path=[],
            total_distance=0.0,
            total_cost=UNAVAILABLE_ROUTE_COST,
            safety_score=0.0,
            maximum_zone_risk=100.0,
            estimated_time_seconds=0.0,
            warnings=[message],
            avoided_zones=[],
            route_type=route_type,
            is_available=False,
        )
