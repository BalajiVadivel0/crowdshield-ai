"""
Safe Routing / Crowd Redirection Engine package.

Exports:
    SafeRoutingEngine — Dijkstra-based safest-path finder for crowd evacuation.
    VenueGraph        — Directed weighted graph representing the venue layout.
"""

from app.ai.routing.engine import SafeRoutingEngine
from app.ai.routing.graph import VenueGraph

__all__ = ["SafeRoutingEngine", "VenueGraph"]
