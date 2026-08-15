"""
Crowd simulation package.

Public API:
    CrowdSimulationService  — use this from external modules
    CrowdSimulator          — internal engine (use via service)
    ScenarioType            — enum of available scenarios
"""

from app.ai.simulation.scenarios import ScenarioType
from app.ai.simulation.crowd_simulator import CrowdSimulator
from app.ai.simulation.service import CrowdSimulationService

__all__ = [
    "ScenarioType",
    "CrowdSimulator",
    "CrowdSimulationService",
]
