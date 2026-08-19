"""
Network Propagation Engine.

Models how crowd pressure and risk spread physically through the VenueGraph over time.
Provides a composable layer for network-aware risk forecasting.
"""

from copy import deepcopy
from typing import Dict, List, Set, Tuple

from app.ai.risk_engine.models import RiskAssessment
from app.ai.routing.graph import VenueGraph
from app.ai.prediction_engine.models import PropagationResult


class NetworkPropagationEngine:
    """
    Simulates the physical propagation of crowds through connected zones.
    Operates on a cloned VenueGraph to predict future states in discrete time steps.
    """

    def forecast_network_risk(
        self,
        graph: VenueGraph,
        current_state: Dict[str, RiskAssessment],
        horizon_minutes: int,
    ) -> Tuple[Dict[str, RiskAssessment], List[PropagationResult]]:
        """
        Predict future risk state of the entire network by simulating propagation.
        
        Args:
            graph: The current physical topology and state of the venue.
            current_state: The current RiskAssessment for each zone_id.
            horizon_minutes: Number of 1-minute simulation ticks to run.
            
        Returns:
            A tuple containing:
            1. The forecasted RiskAssessment for each zone at the end of the horizon.
            2. A log of PropagationResults explaining the flow transfers.
        """
        # Do not mutate the authoritative graph or current states
        sim_state = {zone_id: self._clone_assessment(ra) for zone_id, ra in current_state.items()}
        propagation_trace: List[PropagationResult] = []

        # Run discrete time-step simulation (1 tick = 1 minute)
        for tick in range(1, horizon_minutes + 1):
            tick_results, next_state = self._simulate_tick(graph, sim_state, tick)
            propagation_trace.extend(tick_results)
            sim_state = next_state

        return sim_state, propagation_trace

    def _simulate_tick(
        self,
        graph: VenueGraph,
        state: Dict[str, RiskAssessment],
        tick: int,
    ) -> Tuple[List[PropagationResult], Dict[str, RiskAssessment]]:
        """
        Execute one minute of crowd propagation.
        """
        results: List[PropagationResult] = []
        next_state = {zone_id: self._clone_assessment(ra) for zone_id, ra in state.items()}

        # 1. Calculate Outward Pressure for all zones
        pressures: Dict[str, float] = {}
        for node_id, node in graph.nodes.items():
            if node_id not in state:
                continue
            
            ra = state[node_id]
            pressures[node_id] = self._calculate_outward_pressure(node.current_crowd, ra)

        # 2. Distribute flow
        for source_id, pressure in pressures.items():
            if pressure <= 0:
                continue
                
            outgoing_edges = [e for e in graph.get_edges_from(source_id) if e.available and e.effective_capacity > 0]
            if not outgoing_edges:
                continue

            # Calculate total effective outgoing capacity
            total_out_cap = sum(e.effective_capacity for e in outgoing_edges)
            
            # Bound transferable flow by edge capacity and actual crowd
            source_crowd = graph.nodes[source_id].current_crowd
            transferable_flow = min(pressure, total_out_cap, source_crowd)
            
            if transferable_flow <= 0:
                continue

            # Calculate distribution weights
            edge_weights: List[float] = []
            valid_edges = []
            
            for edge in outgoing_edges:
                dest_id = edge.dest_id
                dest_node = graph.nodes.get(dest_id)
                if not dest_node or not dest_node.available or dest_node.capacity <= 0:
                    continue
                    
                # Downstream congestion limits flow
                # Re-calculate dest_crowd based on density risk assuming density_risk = (crowd/cap)*100
                dest_crowd_est = (state[dest_id].features.density_risk / 100.0) * dest_node.capacity if dest_id in state else dest_node.current_crowd
                congestion = min(1.0, dest_crowd_est / dest_node.capacity)
                
                # Weight = Edge Capacity * Available Destination Space
                weight = edge.effective_capacity * (1.0 - congestion)
                if weight > 0:
                    edge_weights.append(weight)
                    valid_edges.append(edge)
                    
            total_weight = sum(edge_weights)
            if total_weight <= 0:
                continue
                
            # Distribute flow
            for edge, weight in zip(valid_edges, edge_weights):
                fraction = weight / total_weight
                flow = transferable_flow * fraction
                
                dest_id = edge.dest_id
                dest_node = graph.nodes[dest_id]
                
                # Update downstream state (simulate people arriving)
                if dest_id in next_state:
                    density_increase = (flow / dest_node.capacity) * 100.0
                    next_state[dest_id].features.density_risk = min(100.0, next_state[dest_id].features.density_risk + density_increase)
                    # Roughly increase overall risk score based on density change
                    next_state[dest_id].score = min(100.0, next_state[dest_id].score + (density_increase * 0.5))
                else:
                    density_increase = 0.0
                
                # Update source state (simulate people leaving)
                density_decrease = (flow / graph.nodes[source_id].capacity) * 100.0 if graph.nodes[source_id].capacity > 0 else 0.0
                next_state[source_id].features.density_risk = max(0.0, next_state[source_id].features.density_risk - density_decrease)
                
                results.append(PropagationResult(
                    source_zone_id=source_id,
                    destination_zone_id=dest_id,
                    estimated_flow=round(flow, 2),
                    propagation_time=float(tick),
                    source_pressure=round(pressure, 2),
                    destination_pressure_change=round(density_increase, 2),
                    reason=f"Pressure ({pressure:.0f}) pushed {flow:.0f} people via {edge.effective_capacity} cap edge."
                ))

        return results, next_state

    def _calculate_outward_pressure(self, current_crowd: int, ra: RiskAssessment) -> float:
        """
        Calculate the outward pressure (people/min seeking to leave) for a zone.
        
        Formula:
        Base pressure is proportional to the current risk score and density risk.
        A zone at 0 risk has 0 pressure. A zone at 100 risk has strong outward pressure.
        
        Multipliers:
        - Bottleneck or high speed reduction -> increases desire to leave (x1.25)
        - High growth rate -> arriving people push existing crowd outward (x1.25)
        """
        if current_crowd <= 0:
            return 0.0
            
        # Drive pressure by the worst of density or overall risk
        pressure_factor = max(ra.score, ra.features.density_risk) / 100.0
        
        # Don't generate flow if risk is very low
        if pressure_factor < 0.2:
            return 0.0
            
        raw_pressure = current_crowd * pressure_factor
        
        # Apply situational multipliers
        multiplier = 1.0
        if ra.features.bottleneck_signal or ra.features.speed_reduction_risk > 50.0:
            multiplier += 0.25
            
        if ra.features.growth_risk > 50.0:
            multiplier += 0.25
            
        # Bounded by current crowd (cannot push out more people than exist)
        return min(float(current_crowd), raw_pressure * multiplier)
        
    def _clone_assessment(self, ra: RiskAssessment) -> RiskAssessment:
        """Helper to deep copy a RiskAssessment for simulation."""
        # Using model_copy(deep=True) for pydantic models
        return ra.model_copy(deep=True)
