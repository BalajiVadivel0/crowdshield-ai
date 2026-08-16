import math
from typing import Optional


# Mock representations of zone locations.
# In a full system, this would come from Venue.location_details
MOCK_ZONES = {
    10: {"lat": 40.7128, "lon": -74.0060, "radius_m": 50},   # Zone A
    11: {"lat": 40.7130, "lon": -74.0065, "radius_m": 100},  # Zone B
    12: {"lat": 40.7135, "lon": -74.0050, "radius_m": 200},  # Zone C
}

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance in meters between two points."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class LocationService:
    """
    Evaluates user location relative to zones.
    """

    @staticmethod
    def resolve_zone(latitude: float, longitude: float) -> Optional[int]:
        """
        Finds which zone a given coordinate is strictly inside.
        Returns the zone_id or None if outside all zones.
        """
        for zone_id, data in MOCK_ZONES.items():
            dist = haversine_distance(latitude, longitude, data["lat"], data["lon"])
            if dist <= data["radius_m"]:
                return zone_id
        return None

    @staticmethod
    def is_approaching_zone(latitude: float, longitude: float, zone_id: int) -> bool:
        """
        Determines if a user is approaching a zone.
        Defined as being outside the zone strictly, but within a 200m warning buffer of its edge.
        """
        if zone_id not in MOCK_ZONES:
            return False
        
        data = MOCK_ZONES[zone_id]
        dist = haversine_distance(latitude, longitude, data["lat"], data["lon"])
        
        # Must be outside the zone itself
        if dist <= data["radius_m"]:
            return False
            
        # But within an approaching threshold
        approaching_threshold = data["radius_m"] + 200
        return dist <= approaching_threshold
