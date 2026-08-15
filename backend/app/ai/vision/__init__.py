"""
Vision Integration Layer.

Converts video frames into CrowdReadingCreate objects.
"""

from app.ai.vision.detector import PersonDetection, PersonDetector, YOLOPersonDetector, MockPersonDetector
from app.ai.vision.tracker import CentroidTracker, TrackedPerson
from app.ai.vision.zones import ZoneAssigner, ZoneConfig
from app.ai.vision.movement import MovementAnalyzer, PersonMovement
from app.ai.vision.pipeline import VisionPipeline

__all__ = [
    "PersonDetection",
    "PersonDetector",
    "YOLOPersonDetector",
    "MockPersonDetector",
    "CentroidTracker",
    "TrackedPerson",
    "ZoneAssigner",
    "ZoneConfig",
    "MovementAnalyzer",
    "PersonMovement",
    "VisionPipeline"
]
