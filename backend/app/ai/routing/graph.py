"""
VenueGraph — directed weighted graph representing a crowd venue.

Nodes represent zones, gates, and exits.
Edges represent corridors, paths, or passage links.

Design principles:
- Mutable in-place via update_* methods (for dynamic recomputation).
- Bidirectional edges are stored as two directed edges; both directions
  are updated together by update_edge_risk() and set_edge_available().
- Nodes and edges are stored as Pydantic models; updates use model_copy()
  to preserve immutability semantics at the field level.
- No routing logic here — this is a pure data structure.
"""

from typing import Dict, List, Optional

from app.ai.routing.models import NodeType, VenueEdge, VenueNode


class VenueGraph:
    """
    Directed weighted graph for venue crowd routing.

    Edges are stored in a directed adjacency list. Bidirectional corridors
    are represented as a pair of directed edges. Both directions are updated
    together when update_edge_risk() or set_edge_available() are called.

    Usage::

        graph = VenueGraph()
        graph.add_node(VenueNode(node_id="zone_1", name="Zone 1", node_type=NodeType.ZONE))
        graph.add_node(VenueNode(node_id="exit_n", name="Exit North", node_type=NodeType.EXIT))
        graph.add_edge(VenueEdge(source_id="zone_1", dest_id="exit_n", distance=50.0))
        # Bidirectional by default → also stores exit_n → zone_1

        graph.update_edge_risk("zone_1", "exit_n", risk_score=70.0)
        graph.set_edge_available("zone_1", "exit_n", available=False)
    """

    def __init__(self) -> None:
        #: All venue nodes keyed by node_id
        self.nodes: Dict[str, VenueNode] = {}

        #: Directed adjacency list: source_id → list of outgoing VenueEdge
        self._outgoing: Dict[str, List[VenueEdge]] = {}

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(self, node: VenueNode) -> None:
        """
        Add or replace a node in the graph.

        If a node with the same node_id already exists, it is overwritten.
        An empty adjacency list is initialised for the node.
        """
        self.nodes[node.node_id] = node
        if node.node_id not in self._outgoing:
            self._outgoing[node.node_id] = []

    def add_edge(self, edge: VenueEdge) -> None:
        """
        Add a directed edge to the graph.

        If edge.bidirectional is True, the reverse edge (dest → source) is
        also added automatically using the same distance/risk/congestion values.

        Source and destination nodes must exist; a ValueError is raised otherwise.
        """
        if edge.source_id not in self.nodes:
            raise ValueError(
                f"Source node '{edge.source_id}' not found. Add nodes before edges."
            )
        if edge.dest_id not in self.nodes:
            raise ValueError(
                f"Destination node '{edge.dest_id}' not found. Add nodes before edges."
            )

        # Ensure adjacency list slot exists
        if edge.source_id not in self._outgoing:
            self._outgoing[edge.source_id] = []

        self._outgoing[edge.source_id].append(edge)

        # Add reverse direction for bidirectional corridors
        if edge.bidirectional:
            if edge.dest_id not in self._outgoing:
                self._outgoing[edge.dest_id] = []

            reverse = edge.model_copy(
                update={
                    "source_id": edge.dest_id,
                    "dest_id": edge.source_id,
                    "bidirectional": False,  # prevent infinite recursion
                }
            )
            self._outgoing[edge.dest_id].append(reverse)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_edges_from(self, node_id: str) -> List[VenueEdge]:
        """Return all outgoing edges from node_id (empty list if none)."""
        return self._outgoing.get(node_id, [])

    def get_exits(self) -> List[VenueNode]:
        """Return all available EXIT nodes, sorted by node_id for determinism."""
        return sorted(
            [n for n in self.nodes.values() if n.node_type == NodeType.EXIT and n.available],
            key=lambda n: n.node_id,
        )

    # ------------------------------------------------------------------
    # Dynamic updates — for real-time risk recomputation
    # ------------------------------------------------------------------

    def update_node(self, node_id: str, **kwargs) -> bool:
        """
        Update one or more fields of an existing node.

        Returns True if the node was found and updated, False otherwise.

        Common use cases::

            graph.update_node("zone_2", risk_score=90.0)
            graph.update_node("zone_2", available=False)
            graph.update_node("zone_2", risk_score=85.0, predicted_risk_score=92.0)
        """
        if node_id not in self.nodes:
            return False
        self.nodes[node_id] = self.nodes[node_id].model_copy(update=kwargs)
        return True

    def update_edge_risk(
        self,
        source_id: str,
        dest_id: str,
        risk_score: float,
        predicted_risk_score: Optional[float] = None,
    ) -> bool:
        """
        Update the risk score (and optionally predicted risk) of an edge.

        Both directions are updated for bidirectional corridors.
        Returns True if at least one edge was updated.
        """
        updated = False
        update_dict: dict = {"risk_score": risk_score}
        if predicted_risk_score is not None:
            update_dict["predicted_risk_score"] = predicted_risk_score

        # Update both directions (handles bidirectional corridors cleanly)
        for src, dst in [(source_id, dest_id), (dest_id, source_id)]:
            edges = self._outgoing.get(src, [])
            for i, edge in enumerate(edges):
                if edge.dest_id == dst:
                    edges[i] = edge.model_copy(update=update_dict)
                    updated = True

        return updated

    def set_edge_available(
        self,
        source_id: str,
        dest_id: str,
        available: bool,
    ) -> bool:
        """
        Set the availability of an edge (both directions for bidirectional).

        Use available=False to model a physically blocked corridor.
        Returns True if at least one edge was updated.
        """
        updated = False
        for src, dst in [(source_id, dest_id), (dest_id, source_id)]:
            edges = self._outgoing.get(src, [])
            for i, edge in enumerate(edges):
                if edge.dest_id == dst:
                    edges[i] = edge.model_copy(update={"available": available})
                    updated = True
        return updated

    def set_node_available(self, node_id: str, available: bool) -> bool:
        """
        Mark a node as available or blocked.

        Blocked nodes are excluded from routing regardless of edge availability.
        Returns True if the node was found.
        """
        return self.update_node(node_id, available=available)

    def update_edge_congestion(
        self,
        source_id: str,
        dest_id: str,
        current_crowd: int,
    ) -> bool:
        """
        Update the current crowd count (congestion) on an edge.

        Both directions updated for bidirectional corridors.
        Returns True if at least one edge was updated.
        """
        updated = False
        for src, dst in [(source_id, dest_id), (dest_id, source_id)]:
            edges = self._outgoing.get(src, [])
            for i, edge in enumerate(edges):
                if edge.dest_id == dst:
                    edges[i] = edge.model_copy(update={"current_crowd": current_crowd})
                    updated = True
        return updated

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        """Total number of nodes in the graph."""
        return len(self.nodes)

    def edge_count(self) -> int:
        """Total number of directed edges stored (bidirectional = 2 entries)."""
        return sum(len(edges) for edges in self._outgoing.values())

    def __repr__(self) -> str:
        return (
            f"VenueGraph(nodes={self.node_count()}, "
            f"directed_edges={self.edge_count()}, "
            f"exits={len(self.get_exits())})"
        )

    def clone(self) -> "VenueGraph":
        """
        Create a deep copy of the venue graph.
        
        Since nodes and edges are Pydantic models, we use model_copy(deep=True)
        to ensure full isolation. Mutating the clone will not affect the original.
        """
        new_graph = VenueGraph()
        
        # Deep copy nodes
        for node in self.nodes.values():
            new_graph.add_node(node.model_copy(deep=True))
            
        # Deep copy edges (only outgoing needed as bidirectional adds both)
        for edges in self._outgoing.values():
            for edge in edges:
                new_graph._outgoing[edge.source_id].append(edge.model_copy(deep=True))
                
        return new_graph
