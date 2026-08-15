"""
Movement analysis module.

Computes speed, movement vectors, and dominant directions for tracked people.
"""

from typing import List, Dict, Tuple
from dataclasses import dataclass
import math

from app.ai.vision.tracker import TrackedPerson


@dataclass
class PersonMovement:
    track_id: int
    speed_mps: float
    direction_string: str  # e.g., 'NORTH', 'STATIONARY'
    vector: Tuple[float, float]  # (dx, dy) in pixels


class MovementAnalyzer:
    """
    Analyzes historical positions of tracked persons to determine movement metrics.
    """
    def __init__(self, pixels_per_meter: float = 50.0, stationary_threshold_mps: float = 0.1):
        self.pixels_per_meter = pixels_per_meter
        self.stationary_threshold = stationary_threshold_mps
        
        # History mapping track_id -> List of (timestamp_seconds, (cx, cy))
        self._history: Dict[int, List[Tuple[float, Tuple[float, float]]]] = {}
        
        # Maximum history to keep per person (e.g., 2 seconds worth at 10 fps)
        self.max_history_len = 20

    def analyze(self, tracked_people: List[TrackedPerson], current_time_sec: float) -> List[PersonMovement]:
        """
        Analyze current tracks against their history.
        """
        current_ids = {p.track_id for p in tracked_people}
        
        # Cleanup lost tracks
        lost = set(self._history.keys()) - current_ids
        for tid in lost:
            del self._history[tid]
            
        movements = []
        
        for person in tracked_people:
            tid = person.track_id
            center = person.center
            
            if tid not in self._history:
                self._history[tid] = []
            
            history = self._history[tid]
            history.append((current_time_sec, center))
            
            if len(history) > self.max_history_len:
                history.pop(0)
                
            # Need at least 2 points to compute movement
            if len(history) < 2:
                movements.append(PersonMovement(
                    track_id=tid, speed_mps=0.0, direction_string="UNKNOWN", vector=(0.0, 0.0)
                ))
                continue
                
            # Use oldest and newest point in the short history window to compute average velocity
            t0, (x0, y0) = history[0]
            t1, (x1, y1) = history[-1]
            
            dt = t1 - t0
            if dt <= 0:
                movements.append(PersonMovement(
                    track_id=tid, speed_mps=0.0, direction_string="UNKNOWN", vector=(0.0, 0.0)
                ))
                continue
                
            dx = x1 - x0
            dy = y1 - y0
            
            dist_pixels = math.hypot(dx, dy)
            dist_meters = dist_pixels / self.pixels_per_meter
            speed_mps = dist_meters / dt
            
            if speed_mps <= self.stationary_threshold:
                direction = "STATIONARY"
            else:
                direction = self._vector_to_direction(dx, dy)
                
            movements.append(PersonMovement(
                track_id=tid,
                speed_mps=speed_mps,
                direction_string=direction,
                vector=(dx, dy)
            ))
            
        return movements

    def _vector_to_direction(self, dx: float, dy: float) -> str:
        """
        Map a movement vector to a cardinal/ordinal direction string.
        Note: Image coordinates usually have +y going DOWN. 
        So dy > 0 is SOUTH.
        dx > 0 is EAST.
        """
        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 360.0
            
        # 0 -> E, 90 -> S, 180 -> W, 270 -> N (assuming +y is down)
        
        if 22.5 <= angle < 67.5:
            return "SOUTHEAST"
        elif 67.5 <= angle < 112.5:
            return "SOUTH"
        elif 112.5 <= angle < 157.5:
            return "SOUTHWEST"
        elif 157.5 <= angle < 202.5:
            return "WEST"
        elif 202.5 <= angle < 247.5:
            return "NORTHWEST"
        elif 247.5 <= angle < 292.5:
            return "NORTH"
        elif 292.5 <= angle < 337.5:
            return "NORTHEAST"
        else:
            return "EAST"
