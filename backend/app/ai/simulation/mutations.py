"""
Graph Mutations for Scenario Simulation.

Provides structures and builders to translate recommendation actions into
mathematical mutations on the VenueGraph.
"""

from typing import List, Optional

from pydantic import BaseModel

from app.ai.routing.graph import VenueGraph
from app.ai.recommendation_engine.models import ActionType


class GraphMutation(BaseModel):
    """
    Represents a specific structural change to the VenueGraph.
    Only provided fields are updated.
    """
    edge_source: Optional[str] = None
    edge_dest: Optional[str] = None
    node_id: Optional[str] = None
    
    new_status: Optional[str] = None
    new_capacity: Optional[int] = None
    new_bidirectional: Optional[bool] = None
    new_available: Optional[bool] = None


class MutationBuilder:
    """
    Builds validated graph mutations from recommendation actions.
    """

    @staticmethod
    def build_mutations(action: ActionType, target_zone_id: Optional[str], graph: VenueGraph) -> List[GraphMutation]:
        """
        Map an ActionType and target to a set of graph mutations.
        Returns a list of GraphMutation. Raises ValueError if the action is invalid or unsupported.
        """
        if not target_zone_id:
            raise ValueError("Target zone ID is required for simulation mutations.")

        # Ensure target node exists
        if target_zone_id not in graph.nodes:
            raise ValueError(f"Target node '{target_zone_id}' not found in graph.")

        if action == ActionType.OPEN_ALTERNATE_EXIT:
            return MutationBuilder._build_open_exit(target_zone_id, graph)
        elif action == ActionType.CLOSE_ENTRY_GATE:
            return MutationBuilder._build_close_entry(target_zone_id, graph)
        elif action == ActionType.RESTRICT_ENTRY:
            return MutationBuilder._build_restrict_entry(target_zone_id, graph)
        elif action == ActionType.ONE_WAY_FLOW:
            return MutationBuilder._build_one_way_flow(target_zone_id, graph)
        else:
            raise ValueError(f"Simulation not supported for action type: {action}")

    @staticmethod
    def _build_open_exit(target_zone_id: str, graph: VenueGraph) -> List[GraphMutation]:
        """
        Mutate an existing edge to an exit node so it is OPEN.
        Finds the first connection from the target zone to an exit.
        """
        edges = graph.get_edges_from(target_zone_id)
        exit_edges = [e for e in edges if graph.nodes[e.dest_id].node_type.value == "EXIT"]
        
        if not exit_edges:
            raise ValueError(f"No existing exit connection found for zone '{target_zone_id}'.")
            
        target_edge = exit_edges[0]
        return [
            GraphMutation(
                edge_source=target_edge.source_id,
                edge_dest=target_edge.dest_id,
                new_status="OPEN",
                new_available=True
            )
        ]

    @staticmethod
    def _build_close_entry(target_zone_id: str, graph: VenueGraph) -> List[GraphMutation]:
        """
        Close all incoming entry connections to the target zone.
        Looks for GATEs first, if none found, closes incoming from ZONEs.
        """
        mutations = []
        target_node = graph.nodes[target_zone_id]
        
        # If target is a GATE, we close its outgoing edges (or the node itself)
        if target_node.node_type.value == "GATE":
            mutations.append(GraphMutation(node_id=target_zone_id, new_available=False))
            for edge in graph.get_edges_from(target_zone_id):
                mutations.append(GraphMutation(
                    edge_source=edge.source_id,
                    edge_dest=edge.dest_id,
                    new_status="CLOSED",
                    new_available=False
                ))
            return mutations
            
        found = False
        # Try finding GATEs first
        for src, edges in graph._outgoing.items():
            src_node = graph.nodes[src]
            if src_node.node_type.value == "GATE":
                for edge in edges:
                    if edge.dest_id == target_zone_id:
                        mutations.append(GraphMutation(
                            edge_source=edge.source_id,
                            edge_dest=edge.dest_id,
                            new_status="CLOSED",
                            new_available=False
                        ))
                        found = True
                        
        # Fallback: close incoming from ZONEs
        if not found:
            for src, edges in graph._outgoing.items():
                for edge in edges:
                    if edge.dest_id == target_zone_id:
                        mutations.append(GraphMutation(
                            edge_source=edge.source_id,
                            edge_dest=edge.dest_id,
                            new_status="CLOSED",
                            new_available=False
                        ))
                        found = True
                        
        if not found:
            raise ValueError(f"No entry connection found for target '{target_zone_id}'.")
            
        return mutations

    @staticmethod
    def _build_restrict_entry(target_zone_id: str, graph: VenueGraph) -> List[GraphMutation]:
        """
        Restrict incoming entry connections.
        """
        mutations = []
        target_node = graph.nodes[target_zone_id]
        
        if target_node.node_type.value == "GATE":
            for edge in graph.get_edges_from(target_zone_id):
                mutations.append(GraphMutation(
                    edge_source=edge.source_id,
                    edge_dest=edge.dest_id,
                    new_status="RESTRICTED"
                ))
            return mutations

        found = False
        # Try finding GATEs first
        for src, edges in graph._outgoing.items():
            src_node = graph.nodes[src]
            if src_node.node_type.value == "GATE":
                for edge in edges:
                    if edge.dest_id == target_zone_id:
                        mutations.append(GraphMutation(
                            edge_source=edge.source_id,
                            edge_dest=edge.dest_id,
                            new_status="RESTRICTED"
                        ))
                        found = True
                        
        # Fallback: restrict incoming from ZONEs
        if not found:
            for src, edges in graph._outgoing.items():
                for edge in edges:
                    if edge.dest_id == target_zone_id:
                        mutations.append(GraphMutation(
                            edge_source=edge.source_id,
                            edge_dest=edge.dest_id,
                            new_status="RESTRICTED"
                        ))
                        found = True
                        
        if not found:
            raise ValueError(f"No entry connection found for target '{target_zone_id}'.")
            
        return mutations

    @staticmethod
    def _build_one_way_flow(target_zone_id: str, graph: VenueGraph) -> List[GraphMutation]:
        """
        Make flow outgoing only from the target zone by closing incoming edges.
        Close all incoming edges from other ZONEs.
        """
        mutations = []
        found = False
        for src, edges in graph._outgoing.items():
            src_node = graph.nodes[src]
            if src_node.node_type.value == "ZONE":
                for edge in edges:
                    if edge.dest_id == target_zone_id:
                        # Close the inward edge
                        mutations.append(GraphMutation(
                            edge_source=edge.source_id,
                            edge_dest=edge.dest_id,
                            new_status="CLOSED",
                            new_available=False
                        ))
                        found = True
        
        if not found:
            raise ValueError(f"No incoming zone connections found to enforce one-way flow for zone '{target_zone_id}'.")
            
        return mutations


def apply_mutations(graph: VenueGraph, mutations: List[GraphMutation]) -> None:
    """
    Apply a list of GraphMutations to the given graph.
    Assumes the graph is already a clone.
    """
    for mutation in mutations:
        if mutation.node_id:
            updates = {}
            if mutation.new_available is not None:
                updates["available"] = mutation.new_available
            graph.update_node(mutation.node_id, **updates)
            
        if mutation.edge_source and mutation.edge_dest:
            edges = graph._outgoing.get(mutation.edge_source, [])
            for i, edge in enumerate(edges):
                if edge.dest_id == mutation.edge_dest:
                    updates = {}
                    if mutation.new_status is not None:
                        updates["status"] = mutation.new_status
                    if mutation.new_capacity is not None:
                        updates["capacity"] = mutation.new_capacity
                    if mutation.new_bidirectional is not None:
                        updates["bidirectional"] = mutation.new_bidirectional
                    if mutation.new_available is not None:
                        updates["available"] = mutation.new_available
                        
                    edges[i] = edge.model_copy(update=updates)
