"""
Scenario metrics and deterministic ranking logic.
"""

from typing import List, Optional
from pydantic import BaseModel


class SimulationMetrics(BaseModel):
    """
    Metrics resulting from a simulation of an intervention scenario.
    """
    baseline_peak_network_risk: float
    scenario_peak_network_risk: Optional[float]
    risk_reduction_delta: Optional[float]
    risk_reduction_percentage: Optional[float]
    critical_zone_count: Optional[int]
    high_risk_zone_count: Optional[int]
    affected_zone_ids: Optional[List[int]]
    simulation_horizon_minutes: int
    scenario_score: Optional[float]
    simulated: bool
    explanation: str


class SimulationRanker:
    """
    Deterministically ranks intervention simulations based on predicted network outcomes.
    """

    @staticmethod
    def calculate_score(peak_risk: float, critical_count: int, high_risk_count: int) -> float:
        """
        Calculate deterministic safety heuristic score. Lower is better.
        """
        return peak_risk + (critical_count * 25.0) + (high_risk_count * 8.0)

    @staticmethod
    def calculate_metrics(
        baseline_risk: float,
        scenario_state: dict,
        horizon_minutes: int,
        affected_zones: List[int]
    ) -> SimulationMetrics:
        """
        Calculate and construct the scenario metrics.
        
        scenario_state should be the final output state of NetworkPropagationEngine.forecast_network_risk().
        It is a Dict[str, RiskAssessment]
        """
        # Find peak risk for each zone at the end of the horizon
        peak_zone_risks = {}
        for zone_id, zone_data in scenario_state.items():
            current_risk = zone_data.get("score", 0.0) if isinstance(zone_data, dict) else zone_data.score
            peak_zone_risks[zone_id] = current_risk
                    
        # Calculate scenario_risk as the max of all peak_zone_risks
        scenario_risk = max(peak_zone_risks.values()) if peak_zone_risks else 0.0
        
        # Count critical and high risk zones
        critical_count = 0
        high_risk_count = 0
        for risk in peak_zone_risks.values():
            if risk >= 80.0:
                critical_count += 1
            elif risk >= 65.0:
                high_risk_count += 1
                
        delta = baseline_risk - scenario_risk
        if baseline_risk > 0:
            pct = (delta / baseline_risk) * 100.0
        else:
            pct = 0.0
            
        score = SimulationRanker.calculate_score(scenario_risk, critical_count, high_risk_count)
        
        # Build explanation
        if delta > 5.0:
            explanation = "This intervention significantly reduces predicted peak network risk."
        elif delta > 0.0:
            explanation = "This intervention provides a minor reduction in predicted peak network risk."
        else:
            explanation = "This intervention does not reduce predicted network risk."
            
        return SimulationMetrics(
            baseline_peak_network_risk=baseline_risk,
            scenario_peak_network_risk=scenario_risk,
            risk_reduction_delta=delta,
            risk_reduction_percentage=pct,
            critical_zone_count=critical_count,
            high_risk_zone_count=high_risk_count,
            affected_zone_ids=affected_zones,
            simulation_horizon_minutes=horizon_minutes,
            scenario_score=score,
            simulated=True,
            explanation=explanation
        )

    @staticmethod
    def build_unsupported_metrics(baseline_risk: float, horizon_minutes: int) -> SimulationMetrics:
        """
        Build metrics for an action that cannot be simulated.
        """
        return SimulationMetrics(
            baseline_peak_network_risk=baseline_risk,
            scenario_peak_network_risk=None,
            risk_reduction_delta=None,
            risk_reduction_percentage=None,
            critical_zone_count=None,
            high_risk_zone_count=None,
            affected_zone_ids=None,
            simulation_horizon_minutes=horizon_minutes,
            scenario_score=None,
            simulated=False,
            explanation="This intervention cannot currently be simulated by the topology model."
        )
