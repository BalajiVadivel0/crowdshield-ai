"""
Detector module for person detection in the vision pipeline.

Abstracts the underlying object detection model (e.g. YOLO) to ensure
the rest of the system does not depend on a specific ML framework.
"""

from typing import List, Protocol
from dataclasses import dataclass
import numpy as np

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


@dataclass
class PersonDetection:
    """A detected person in a single frame."""
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


class PersonDetector(Protocol):
    """Protocol for person detection models."""
    def detect(self, frame: np.ndarray) -> List[PersonDetection]:
        """Detect persons in a numpy image array (BGR)."""
        ...


class YOLOPersonDetector:
    """
    YOLO-based person detector.
    
    Only filters class 0 (person).
    """
    def __init__(self, model_path: str = "yolov8n.pt", conf_threshold: float = 0.3):
        if not YOLO_AVAILABLE:
            raise ImportError("ultralytics is not installed. Cannot use YOLOPersonDetector.")
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold

    def detect(self, frame: np.ndarray) -> List[PersonDetection]:
        # run inference on frame
        results = self.model(frame, classes=[0], verbose=False)
        
        detections = []
        if not results:
            return detections
            
        result = results[0]
        boxes = result.boxes
        
        if boxes is None:
            return detections
            
        for box in boxes:
            conf = float(box.conf[0])
            if conf < self.conf_threshold:
                continue
                
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(PersonDetection(
                x1=float(x1),
                y1=float(y1),
                x2=float(x2),
                y2=float(y2),
                confidence=conf
            ))
            
        return detections


class MockPersonDetector:
    """
    A deterministic mock detector for unit tests.
    Does not require real weights or inference.
    """
    def __init__(self, predefined_detections: List[List[PersonDetection]] = None):
        """
        Args:
            predefined_detections: A list of detection lists, one for each frame.
        """
        self.predefined_detections = predefined_detections or []
        self.frame_index = 0

    def detect(self, frame: np.ndarray) -> List[PersonDetection]:
        if self.frame_index < len(self.predefined_detections):
            dets = self.predefined_detections[self.frame_index]
        else:
            dets = []
        self.frame_index += 1
        return dets
