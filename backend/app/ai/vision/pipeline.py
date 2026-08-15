"""
Vision Pipeline orchestrator.

Coordinates detection, tracking, zone assignment, and movement analysis
to produce deterministic CrowdReadingCreate payloads compatible with the
Risk Engine.
"""

from typing import List, Dict, Optional
from datetime import datetime, timezone
import collections
import numpy as np
import cv2

from app.schemas.crowd_reading import CrowdReadingCreate
from app.services.crowd_metrics_service import CrowdMetricsService
from app.ai.vision.detector import PersonDetector
from app.ai.vision.tracker import CentroidTracker
from app.ai.vision.zones import ZoneAssigner, ZoneConfig
from app.ai.vision.movement import MovementAnalyzer, PersonMovement


class VisionPipeline:
    """
    Orchestrates the entire vision-to-metrics pipeline.
    """
    def __init__(
        self,
        event_id: int,
        detector: PersonDetector,
        zones: List[ZoneConfig],
        pixels_per_meter: float = 50.0,
        tracker_max_distance: float = 100.0,
    ):
        self.event_id = event_id
        self.detector = detector
        self.tracker = CentroidTracker(max_distance=tracker_max_distance)
        self.zone_assigner = ZoneAssigner(zones)
        self.movement_analyzer = MovementAnalyzer(pixels_per_meter=pixels_per_meter)
        self.metrics_service = CrowdMetricsService()
        
        # Keep track of previous person counts per zone for growth rate
        self.zones = {z.zone_id: z for z in zones}
        self._previous_counts: Dict[int, int] = {}
        self._previous_times: Dict[int, float] = {}

    def process_frame(self, frame: np.ndarray, timestamp_sec: float) -> List[CrowdReadingCreate]:
        """
        Process a single video frame and return crowd readings for all configured zones.
        """
        # 1. Detect
        detections = self.detector.detect(frame)
        
        # 2. Track
        tracked_people = self.tracker.update(detections)
        
        # 3. Movement
        movements = self.movement_analyzer.analyze(tracked_people, timestamp_sec)
        movement_map = {m.track_id: m for m in movements}
        
        # 4. Zone Assignment
        zone_to_people = collections.defaultdict(list)
        for person in tracked_people:
            assigned_zones = self.zone_assigner.assign(person)
            for z_id in assigned_zones:
                zone_to_people[z_id].append(person)
                
        # 5. Generate Readings
        readings = []
        utc_now = datetime.now(timezone.utc)
        
        for z_id, z_config in self.zones.items():
            people_in_zone = zone_to_people[z_id]
            person_count = len(people_in_zone)
            
            # Density
            density_percent = self.metrics_service.compute_density(person_count, z_config.capacity)
            
            # Speeds and Directions
            speeds = []
            directions = []
            for p in people_in_zone:
                mov = movement_map.get(p.track_id)
                if mov:
                    speeds.append(mov.speed_mps)
                    if mov.direction_string != "UNKNOWN":
                        directions.append(mov.direction_string)
                        
            avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
            avg_speed = self.metrics_service.validate_speed(avg_speed)
            
            # Dominant direction and conflict detection
            dominant_direction = "UNKNOWN"
            if directions:
                # Count directions
                dir_counts = collections.Counter(directions)
                # Find most common
                most_common = dir_counts.most_common()
                
                if len(most_common) > 1:
                    # Check for reverse flow (significant minority going opposite)
                    # For MVP, if the second most common direction is strictly opposite, we call it conflicted.
                    # Or simpler: just let metrics_service check if it's conflicted.
                    # We will emit CONFLICTED if there's a strong secondary flow.
                    primary, p_count = most_common[0]
                    secondary, s_count = most_common[1]
                    
                    # If secondary is at least 30% of primary, call it conflicted
                    if secondary != "STATIONARY" and s_count >= p_count * 0.3:
                        # Need to ensure they are roughly opposite.
                        # Simple hack for MVP: any strong conflicting flow flags it
                        dominant_direction = "CONFLICTED"
                    else:
                        dominant_direction = primary
                else:
                    dominant_direction = most_common[0][0]
            
            # Growth rate
            growth_rate = None
            if z_id in self._previous_counts and z_id in self._previous_times:
                prev_count = self._previous_counts[z_id]
                prev_time = self._previous_times[z_id]
                elapsed_sec = timestamp_sec - prev_time
                if elapsed_sec > 0:
                    growth_rate = self.metrics_service.compute_growth_rate(
                        person_count, prev_count, elapsed_sec
                    )
            
            # Update history
            self._previous_counts[z_id] = person_count
            self._previous_times[z_id] = timestamp_sec
            
            # Congestion
            congestion_score = self.metrics_service.compute_congestion_score(
                density_percent, avg_speed
            )
            
            # All danger indicators
            indicators = self.metrics_service.compute_all_indicators(
                density_percent, avg_speed, dominant_direction, growth_rate
            )
            
            reading = CrowdReadingCreate(
                event_id=self.event_id,
                zone_id=z_id,
                timestamp=utc_now,
                person_count=person_count,
                density_percent=round(density_percent, 2),
                average_speed=round(avg_speed, 2),
                dominant_direction=dominant_direction,
                crowd_growth_rate=round(growth_rate, 2) if growth_rate is not None else None,
                congestion_score=round(congestion_score, 2),
                surge_indicator=indicators["surge_indicator"],
                reverse_flow_indicator=indicators["reverse_flow_indicator"],
                bottleneck_indicator=indicators["bottleneck_indicator"]
            )
            readings.append(reading)
            
        return readings
