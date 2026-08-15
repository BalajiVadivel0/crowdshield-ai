"""
Tracker module for maintaining person identities across frames.

Implements a lightweight centroid-based tracker for MVP purposes.
Does not depend on heavy MOT frameworks, but can be easily swapped out.
"""

from typing import List, Dict, Tuple
from dataclasses import dataclass
import numpy as np

from app.ai.vision.detector import PersonDetection


@dataclass
class TrackedPerson:
    """A person tracked with a stable ID across frames."""
    track_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    
    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


class CentroidTracker:
    """
    A simple deterministic centroid distance-based tracker.
    
    Assigns IDs to bounding boxes based on the Euclidean distance
    between their centroids in consecutive frames.
    """
    def __init__(self, max_distance: float = 100.0, max_disappeared: int = 5):
        self.next_id = 1
        self.objects: Dict[int, TrackedPerson] = {}
        self.disappeared: Dict[int, int] = {}
        self.max_distance = max_distance
        self.max_disappeared = max_disappeared

    def update(self, detections: List[PersonDetection]) -> List[TrackedPerson]:
        """
        Update the tracker with new detections and return tracked objects.
        """
        if len(detections) == 0:
            for track_id in list(self.disappeared.keys()):
                self.disappeared[track_id] += 1
                if self.disappeared[track_id] > self.max_disappeared:
                    self._deregister(track_id)
            return list(self.objects.values())

        input_centroids = np.zeros((len(detections), 2), dtype="float")
        for i, d in enumerate(detections):
            input_centroids[i] = d.center

        if len(self.objects) == 0:
            for i, d in enumerate(detections):
                self._register(d)
        else:
            object_ids = list(self.objects.keys())
            object_centroids = np.array([obj.center for obj in self.objects.values()])

            # Compute distance matrix between existing objects and input centroids
            # D[i, j] is distance between object i and input j
            D = np.linalg.norm(object_centroids[:, np.newaxis] - input_centroids, axis=2)

            # Find smallest distances
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for row, col in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue

                if D[row, col] > self.max_distance:
                    continue

                object_id = object_ids[row]
                d = detections[col]
                self.objects[object_id] = TrackedPerson(
                    track_id=object_id,
                    x1=d.x1, y1=d.y1, x2=d.x2, y2=d.y2,
                    confidence=d.confidence
                )
                self.disappeared[object_id] = 0

                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(0, D.shape[0])).difference(used_rows)
            unused_cols = set(range(0, D.shape[1])).difference(used_cols)

            for row in unused_rows:
                object_id = object_ids[row]
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self._deregister(object_id)

            for col in unused_cols:
                self._register(detections[col])

        return list(self.objects.values())

    def _register(self, detection: PersonDetection):
        self.objects[self.next_id] = TrackedPerson(
            track_id=self.next_id,
            x1=detection.x1,
            y1=detection.y1,
            x2=detection.x2,
            y2=detection.y2,
            confidence=detection.confidence
        )
        self.disappeared[self.next_id] = 0
        self.next_id += 1

    def _deregister(self, track_id: int):
        del self.objects[track_id]
        del self.disappeared[track_id]
