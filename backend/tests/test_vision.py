"""
Unit and integration tests for the Vision pipeline.

Ensures that detection, tracking, movement analysis, and zone assignment
correctly produce CrowdReadingCreate objects identical in structure to the
Simulation engine, and that these readings can pass through Risk and Prediction.
"""

from datetime import datetime, timezone
import pytest
import numpy as np

from app.schemas.crowd_reading import CrowdReadingCreate
from app.ai.vision.detector import PersonDetection, MockPersonDetector
from app.ai.vision.tracker import CentroidTracker
from app.ai.vision.zones import ZoneAssigner, ZoneConfig
from app.ai.vision.movement import MovementAnalyzer
from app.ai.vision.pipeline import VisionPipeline

from app.ai.risk_engine.engine import RiskEngine
from app.ai.prediction_engine.engine import PredictionEngine

# ---------------------------------------------------------------------------
# Unit tests for Tracker
# ---------------------------------------------------------------------------

def test_tracker_id_stability():
    tracker = CentroidTracker(max_distance=50.0)
    # Frame 1: One person
    d1 = [PersonDetection(0, 0, 10, 10, 0.9)]
    tracked = tracker.update(d1)
    assert len(tracked) == 1
    tid = tracked[0].track_id

    # Frame 2: Same person moved slightly
    d2 = [PersonDetection(2, 2, 12, 12, 0.9)]
    tracked = tracker.update(d2)
    assert len(tracked) == 1
    assert tracked[0].track_id == tid

def test_tracker_new_person():
    tracker = CentroidTracker(max_distance=20.0)
    # Frame 1: One person
    d1 = [PersonDetection(0, 0, 10, 10, 0.9)]
    tracked = tracker.update(d1)
    assert len(tracked) == 1

    # Frame 2: Person moved out of distance bounds (too far) -> treated as new person
    # OR a completely new person appears far away
    d2 = [PersonDetection(100, 100, 110, 110, 0.9)]
    tracked = tracker.update(d1 + d2)
    assert len(tracked) == 2
    # One should have ID 1, one should have ID 2
    ids = {t.track_id for t in tracked}
    assert 1 in ids
    assert 2 in ids

# ---------------------------------------------------------------------------
# Unit tests for MovementAnalyzer
# ---------------------------------------------------------------------------

def test_movement_direction():
    tracker = CentroidTracker(max_distance=100.0)
    analyzer = MovementAnalyzer(pixels_per_meter=10.0, stationary_threshold_mps=0.1)

    # Frame 1
    d1 = [PersonDetection(0, 0, 10, 10, 0.9)]
    t1 = tracker.update(d1)
    mov1 = analyzer.analyze(t1, 0.0)
    assert mov1[0].direction_string == "UNKNOWN" # only 1 point

    # Frame 2: Move right (EAST) +x
    d2 = [PersonDetection(20, 0, 30, 10, 0.9)]
    t2 = tracker.update(d2)
    mov2 = analyzer.analyze(t2, 1.0)
    assert mov2[0].direction_string == "EAST"
    
    # speed: moved 20 pixels in 1 second. pixels_per_meter=10 -> 2 m/s
    assert mov2[0].speed_mps == 2.0

def test_stationary_movement():
    tracker = CentroidTracker(max_distance=100.0)
    analyzer = MovementAnalyzer(pixels_per_meter=10.0, stationary_threshold_mps=0.5)

    d1 = [PersonDetection(0, 0, 10, 10, 0.9)]
    t1 = tracker.update(d1)
    analyzer.analyze(t1, 0.0)

    # Move very slightly
    d2 = [PersonDetection(1, 1, 11, 11, 0.9)]
    t2 = tracker.update(d2)
    mov2 = analyzer.analyze(t2, 1.0)
    
    # Speed is 1.414 pixels / 10 = 0.14 m/s. Threshold is 0.5
    assert mov2[0].direction_string == "STATIONARY"

# ---------------------------------------------------------------------------
# Unit tests for ZoneAssigner
# ---------------------------------------------------------------------------

def test_zone_assignment():
    # Simple rectangle 0,0 to 100,100
    z1 = ZoneConfig(zone_id=1, polygon=[(0,0), (100,0), (100,100), (0,100)], capacity=10)
    assigner = ZoneAssigner([z1])

    tracker = CentroidTracker()
    # Person inside
    p_in = tracker.update([PersonDetection(10, 10, 20, 20, 0.9)])[0]
    # Person outside
    p_out = tracker.update([PersonDetection(200, 200, 210, 210, 0.9)])[0]

    assert 1 in assigner.assign(p_in)
    assert 1 not in assigner.assign(p_out)

# ---------------------------------------------------------------------------
# VisionPipeline Output
# ---------------------------------------------------------------------------

def test_pipeline_output_structure():
    z1 = ZoneConfig(zone_id=1, polygon=[(0,0), (100,0), (100,100), (0,100)], capacity=10)
    mock_detector = MockPersonDetector([
        [PersonDetection(10, 10, 20, 20, 0.9), PersonDetection(30, 30, 40, 40, 0.9)],
        [PersonDetection(15, 10, 25, 20, 0.9), PersonDetection(35, 30, 45, 40, 0.9)] # Move East
    ])
    
    pipeline = VisionPipeline(event_id=42, detector=mock_detector, zones=[z1], pixels_per_meter=10.0)
    
    # Empty frame (just a dummy np.array)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    
    readings_f1 = pipeline.process_frame(frame, 0.0)
    assert len(readings_f1) == 1
    r1 = readings_f1[0]
    assert isinstance(r1, CrowdReadingCreate)
    assert r1.person_count == 2
    assert r1.density_percent == 20.0 # 2/10 * 100
    assert r1.event_id == 42
    assert r1.zone_id == 1
    assert r1.crowd_growth_rate is None # no history
    
    readings_f2 = pipeline.process_frame(frame, 1.0)
    r2 = readings_f2[0]
    assert r2.person_count == 2
    assert r2.dominant_direction == "EAST"
    assert r2.crowd_growth_rate == 0.0 # 2 to 2 in 1 second
    
# ---------------------------------------------------------------------------
# End-to-End Integration (Vision -> Risk -> Prediction)
# ---------------------------------------------------------------------------

def test_full_vision_to_prediction_pipeline():
    """
    Simulates a sequence of frames showing a rapidly growing, conflicting crowd.
    Passes the output to RiskEngine, then PredictionEngine.
    """
    z1 = ZoneConfig(zone_id=1, polygon=[(0,0), (1000,0), (1000,1000), (0,1000)], capacity=5)
    
    # We will provide 5 frames, spaced 60 seconds apart, with rapidly increasing crowd size.
    # We'll make them move opposite ways to trigger CONFLICTED and reverse flow.
    detections_sequence = []
    
    count = 1
    for step in range(5):
        dets = []
        for i in range(count):
            # Half go East, half go West
            if i % 2 == 0:
                # Eastward
                x = 10 + step*10
                dets.append(PersonDetection(x, 50, x+10, 60, 0.9))
            else:
                # Westward
                x = 500 - step*10
                dets.append(PersonDetection(x, 50, x+10, 60, 0.9))
        
        detections_sequence.append(dets)
        count += 2 # Crowd growing rapidly
        
    mock_detector = MockPersonDetector(detections_sequence)
    pipeline = VisionPipeline(event_id=1, detector=mock_detector, zones=[z1], pixels_per_meter=10.0)
    
    risk_engine = RiskEngine()
    prediction_engine = PredictionEngine(min_observations=3)
    
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    
    risk_history = []
    
    for step in range(5):
        # 60 second intervals
        readings = pipeline.process_frame(frame, float(step * 60))
        assert len(readings) == 1
        r = readings[0]
        
        ass = risk_engine.evaluate(r)
        risk_history.append(ass)
        
    # The crowd grew from 1 to 9 over 5 frames (capacity 5). Density hit > 100%.
    # Opposing flows should trigger REVERSE_FLOW or CONFLICTED.
    # Risk should be rapidly increasing.
    
    # Let's verify the risk engine detected things properly from vision data
    last_ass = risk_history[-1]
    assert last_ass.features.reverse_flow_signal is True
    assert last_ass.features.density_risk > 80.0
    
    # Now run prediction
    pred = prediction_engine.predict(risk_history)
    assert pred.confidence > 0.0
    assert pred.trend_direction.value == "WORSENING"
    
    # The future risk type should be critical given high density and conflict
    assert pred.forecasts[-1].predicted_risk_type in ("REVERSE_FLOW", "CROWD_CRUSH", "HIGH_DENSITY")
