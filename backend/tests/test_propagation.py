import pytest
from app.ai.routing.graph import VenueGraph
from app.ai.routing.models import VenueNode, NodeType, VenueEdge
from app.ai.risk_engine.models import RiskAssessment, RiskFeatures, RiskLevel, RiskType
from app.ai.prediction_engine.propagation import NetworkPropagationEngine

@pytest.fixture
def base_graph():
    graph = VenueGraph()
    # Zone A: Source
    graph.add_node(VenueNode(node_id="A", name="Zone A", node_type=NodeType.ZONE, capacity=1000, current_crowd=800, risk_score=80.0))
    # Zone B: Downstream
    graph.add_node(VenueNode(node_id="B", name="Zone B", node_type=NodeType.ZONE, capacity=1000, current_crowd=200, risk_score=10.0))
    # Zone C: Isolated
    graph.add_node(VenueNode(node_id="C", name="Zone C", node_type=NodeType.ZONE, capacity=1000, current_crowd=100, risk_score=10.0))
    
    # A -> B connection (Capacity 500)
    graph.add_edge(VenueEdge(source_id="A", dest_id="B", distance=10.0, capacity=500, bidirectional=False, status="OPEN", available=True))
    return graph

@pytest.fixture
def base_state():
    return {
        "A": RiskAssessment(
            event_id=1, zone_id=1, score=80.0, level=RiskLevel.HIGH, risk_type=RiskType.HIGH_DENSITY,
            explanation="Mock explanation A",
            features=RiskFeatures(
                density_risk=80.0, growth_risk=60.0, movement_conflict_risk=0.0, 
                speed_reduction_risk=60.0, surge_signal=False, reverse_flow_signal=False, 
                bottleneck_signal=True, congestion_signal=True
            )
        ),
        "B": RiskAssessment(
            event_id=1, zone_id=2, score=10.0, level=RiskLevel.LOW, risk_type=RiskType.STABLE,
            explanation="Mock explanation B",
            features=RiskFeatures(
                density_risk=20.0, growth_risk=0.0, movement_conflict_risk=0.0, 
                speed_reduction_risk=0.0, surge_signal=False, reverse_flow_signal=False, 
                bottleneck_signal=False, congestion_signal=False
            )
        ),
        "C": RiskAssessment(
            event_id=1, zone_id=3, score=10.0, level=RiskLevel.LOW, risk_type=RiskType.STABLE,
            explanation="Mock explanation C",
            features=RiskFeatures(
                density_risk=10.0, growth_risk=0.0, movement_conflict_risk=0.0, 
                speed_reduction_risk=0.0, surge_signal=False, reverse_flow_signal=False, 
                bottleneck_signal=False, congestion_signal=False
            )
        ),
    }

def test_connectivity_and_directionality(base_graph, base_state):
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=1)
    
    # A -> B produces propagation
    assert len(trace) == 1
    assert trace[0].source_zone_id == "A"
    assert trace[0].destination_zone_id == "B"
    assert trace[0].estimated_flow > 0
    
    # Check that A decreased and B increased
    assert next_state["B"].features.density_risk > base_state["B"].features.density_risk
    assert next_state["A"].features.density_risk < base_state["A"].features.density_risk

def test_closed_edge(base_graph, base_state):
    # Close the edge
    base_graph.set_edge_available("A", "B", available=False)
    # Also update status to CLOSED just in case
    for e in base_graph.get_edges_from("A"):
        e.status = "CLOSED"
        
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=1)
    
    assert len(trace) == 0
    assert next_state["B"].features.density_risk == base_state["B"].features.density_risk

def test_restricted_edge(base_graph, base_state):
    # Set to restricted
    edges = base_graph.get_edges_from("A")
    edges[0].status = "RESTRICTED"
    
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=1)
    
    assert len(trace) == 1
    # Effective capacity should be 250 (500 * 0.5)
    assert trace[0].estimated_flow <= 250

def test_capacity_cap(base_graph, base_state):
    # Very small capacity edge
    edges = base_graph.get_edges_from("A")
    edges[0].capacity = 10
    
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=1)
    
    assert len(trace) == 1
    assert trace[0].estimated_flow <= 10

def test_downstream_pressure_increases_risk(base_graph, base_state):
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=1)
    
    assert next_state["B"].score > base_state["B"].score
    
def test_saturated_destination(base_graph, base_state):
    # Make B saturated
    base_graph.nodes["B"].current_crowd = 1000
    base_state["B"].features.density_risk = 100.0
    
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=1)
    
    # B is full (congestion = 1.0), so weight is 0. No flow should occur
    assert len(trace) == 0

def test_isolation(base_graph, base_state):
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=1)
    
    # C should remain completely unaffected
    assert next_state["C"].score == base_state["C"].score
    assert next_state["C"].features.density_risk == base_state["C"].features.density_risk

def test_cyclic_graph(base_graph, base_state):
    # Add B -> A connection to create cycle
    base_graph.add_edge(VenueEdge(source_id="B", dest_id="A", distance=10.0, capacity=500, bidirectional=False, status="OPEN", available=True))
    
    # Make B also dangerous
    base_state["B"].score = 80.0
    base_state["B"].features.density_risk = 80.0
    base_graph.nodes["B"].current_crowd = 800
    
    engine = NetworkPropagationEngine()
    next_state, trace = engine.forecast_network_risk(base_graph, base_state, horizon_minutes=3)
    
    # With a 3 minute horizon, they will exchange flow, but it should not crash or runaway to infinity
    assert next_state["A"].features.density_risk <= 100.0
    assert next_state["B"].features.density_risk <= 100.0
    assert len(trace) > 0
