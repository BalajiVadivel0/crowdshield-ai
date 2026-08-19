import pytest
from app.ai.routing.graph import VenueGraph
from app.ai.routing.models import VenueNode, VenueEdge, NodeType
from app.ai.simulation.mutations import MutationBuilder, GraphMutation, apply_mutations
from app.ai.simulation.ranker import SimulationRanker
from app.ai.recommendation_engine.models import ActionType
from app.ai.prediction_engine.models import PropagationResult


def create_mock_graph():
    graph = VenueGraph()
    graph.add_node(VenueNode(node_id="zone_1", name="Zone 1", node_type=NodeType.ZONE, capacity=100))
    graph.add_node(VenueNode(node_id="zone_2", name="Zone 2", node_type=NodeType.ZONE, capacity=100))
    graph.add_node(VenueNode(node_id="gate_1", name="Gate 1", node_type=NodeType.GATE, capacity=50))
    graph.add_node(VenueNode(node_id="exit_1", name="Exit 1", node_type=NodeType.EXIT, capacity=100))
    
    # Entrance to Zone 1
    graph.add_edge(VenueEdge(source_id="gate_1", dest_id="zone_1", distance=10.0, capacity=20, status="OPEN", bidirectional=False))
    # Zone 1 to Zone 2
    graph.add_edge(VenueEdge(source_id="zone_1", dest_id="zone_2", distance=10.0, capacity=20, status="OPEN", bidirectional=True))
    # Zone 2 to Exit (currently closed/restricted to simulate alternate exit)
    graph.add_edge(VenueEdge(source_id="zone_2", dest_id="exit_1", distance=10.0, capacity=20, status="CLOSED", available=False, bidirectional=False))
    
    return graph


def test_clone_isolation():
    graph = create_mock_graph()
    clone = graph.clone()
    
    assert clone.node_count() == graph.node_count()
    assert clone.edge_count() == graph.edge_count()
    
    # Mutate clone
    clone.update_node("zone_1", capacity=999)
    clone.set_edge_available("zone_1", "zone_2", False)
    
    # Assert original unchanged
    assert graph.nodes["zone_1"].capacity == 100
    assert graph.get_edges_from("zone_1")[0].available is True


def test_open_alternate_exit():
    graph = create_mock_graph()
    # Action
    mutations = MutationBuilder.build_mutations(ActionType.OPEN_ALTERNATE_EXIT, "zone_2", graph)
    assert len(mutations) == 1
    
    # Apply
    apply_mutations(graph, mutations)
    
    # Verify
    edges = graph.get_edges_from("zone_2")
    edge = next(e for e in edges if e.dest_id == "exit_1")
    assert edge.status == "OPEN"
    assert edge.available is True
    assert edge.available is True


def test_close_entry_gate():
    graph = create_mock_graph()
    mutations = MutationBuilder.build_mutations(ActionType.CLOSE_ENTRY_GATE, "zone_1", graph)
    
    apply_mutations(graph, mutations)
    
    edge = graph.get_edges_from("gate_1")[0]
    assert edge.status == "CLOSED"
    assert edge.available is False


def test_restrict_entry():
    graph = create_mock_graph()
    mutations = MutationBuilder.build_mutations(ActionType.RESTRICT_ENTRY, "zone_1", graph)
    
    apply_mutations(graph, mutations)
    
    edge = graph.get_edges_from("gate_1")[0]
    assert edge.status == "RESTRICTED"


def test_one_way_flow():
    graph = create_mock_graph()
    mutations = MutationBuilder.build_mutations(ActionType.ONE_WAY_FLOW, "zone_2", graph)
    
    apply_mutations(graph, mutations)
    
    # Incoming to zone 2 from zone 1 should be closed
    edges_from_1 = graph.get_edges_from("zone_1")
    edge_to_2 = next(e for e in edges_from_1 if e.dest_id == "zone_2")
    assert edge_to_2.status == "CLOSED"
    assert edge_to_2.available is False
    
    # Outgoing from zone 2 to zone 1 should remain open
    edges_from_2 = graph.get_edges_from("zone_2")
    edge_to_1 = next(e for e in edges_from_2 if e.dest_id == "zone_1")
    assert edge_to_1.status == "OPEN"


def test_ranking_determinism():
    # Scenario A: peak 90, 2 critical, 1 high
    # Score = 90 + 2*25 + 1*8 = 90 + 50 + 8 = 148
    score_a = SimulationRanker.calculate_score(90.0, 2, 1)
    assert score_a == 148.0
    
    # Scenario B: peak 85, 1 critical, 3 high
    # Score = 85 + 25 + 24 = 134
    score_b = SimulationRanker.calculate_score(85.0, 1, 3)
    assert score_b == 134.0
    
    # Lower is better, B wins
    assert score_b < score_a


def test_unsupported_action():
    graph = create_mock_graph()
    with pytest.raises(ValueError, match="Simulation not supported"):
        MutationBuilder.build_mutations(ActionType.DEPLOY_SECURITY, "zone_1", graph)


def test_invalid_target():
    graph = create_mock_graph()
    with pytest.raises(ValueError, match="Target node 'invalid_zone' not found"):
        MutationBuilder.build_mutations(ActionType.CLOSE_ENTRY_GATE, "invalid_zone", graph)


def test_calculate_metrics():
    baseline_risk = 90.0
    
    # Mocking the final scenario state as Dict[str, dict]
    scenario_state = {
        "zone_1": {"score": 60.0},
        "zone_2": {"score": 85.0}  # 1 critical
    }
    
    metrics = SimulationRanker.calculate_metrics(
        baseline_risk=baseline_risk,
        scenario_state=scenario_state,
        horizon_minutes=15,
        affected_zones=[101]
    )
    
    assert metrics.scenario_peak_network_risk == 85.0
    assert metrics.risk_reduction_delta == 5.0
    assert metrics.critical_zone_count == 1
    assert metrics.high_risk_zone_count == 0
    assert metrics.scenario_score == 85.0 + 25.0 + 0.0 # 110.0
