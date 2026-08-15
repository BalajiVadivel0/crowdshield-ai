"""
Zone assignment module.

Maps tracked people in pixel space to configured logical zones.
"""

from typing import List, Tuple
from dataclasses import dataclass
import cv2
import numpy as np

from app.ai.vision.tracker import TrackedPerson


@dataclass
class ZoneConfig:
    """Configuration for a monitored zone."""
    zone_id: int
    # List of (x, y) pixel coordinates defining a polygon
    polygon: List[Tuple[float, float]]
    capacity: int


class ZoneAssigner:
    """
    Assigns tracked persons to configured zones.
    """
    def __init__(self, zones: List[ZoneConfig]):
        self.zones = zones
        # Precompute contours for fast OpenCV pointPolygonTest
        self._contours = {}
        for z in zones:
            pts = np.array(z.polygon, np.int32).reshape((-1, 1, 2))
            self._contours[z.zone_id] = pts

    def assign(self, person: TrackedPerson) -> List[int]:
        """
        Return a list of zone_ids the person currently occupies.
        Uses the person's center point.
        """
        assigned = []
        cx, cy = person.center
        pt = (float(cx), float(cy))
        
        for z in self.zones:
            contour = self._contours[z.zone_id]
            # Returns +1 if inside, 0 if on edge, -1 if outside
            dist = cv2.pointPolygonTest(contour, pt, measureDist=False)
            if dist >= 0:
                assigned.append(z.zone_id)
                
        return assigned
