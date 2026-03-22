"""
Geofence Alert Zones
Allows defining circular geofence zones and checking which entities
(flights, ships, etc.) are inside them.
"""

import json
import math
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_GEOFENCE_FILE = _DATA_DIR / "geofences.json"

# In-memory geofence store
_geofences: List[Dict[str, Any]] = []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _load_geofences():
    """Load geofences from disk."""
    global _geofences
    if _GEOFENCE_FILE.exists():
        try:
            with open(_GEOFENCE_FILE, "r") as f:
                _geofences = json.load(f)
            logger.info(f"Loaded {len(_geofences)} geofences from disk")
        except Exception as e:
            logger.error(f"Failed to load geofences: {e}")
            _geofences = []
    else:
        # Create default geofences for interesting areas
        _geofences = [
            {
                "id": "strait-of-hormuz",
                "name": "Strait of Hormuz",
                "lat": 26.5,
                "lng": 56.25,
                "radius_km": 100,
                "category": "chokepoint",
                "color": "#ef4444",
            },
            {
                "id": "taiwan-strait",
                "name": "Taiwan Strait",
                "lat": 24.0,
                "lng": 119.5,
                "radius_km": 150,
                "category": "flashpoint",
                "color": "#f97316",
            },
            {
                "id": "suez-canal",
                "name": "Suez Canal",
                "lat": 30.5,
                "lng": 32.3,
                "radius_km": 50,
                "category": "chokepoint",
                "color": "#eab308",
            },
            {
                "id": "black-sea",
                "name": "Black Sea Zone",
                "lat": 43.5,
                "lng": 34.0,
                "radius_km": 300,
                "category": "conflict",
                "color": "#ef4444",
            },
            {
                "id": "south-china-sea",
                "name": "South China Sea",
                "lat": 15.0,
                "lng": 115.0,
                "radius_km": 500,
                "category": "flashpoint",
                "color": "#f97316",
            },
        ]
        _save_geofences()


def _save_geofences():
    """Persist geofences to disk."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_GEOFENCE_FILE, "w") as f:
            json.dump(_geofences, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save geofences: {e}")


def get_geofences() -> List[Dict[str, Any]]:
    """Return all defined geofences."""
    if not _geofences:
        _load_geofences()
    return _geofences


def add_geofence(fence: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new geofence zone."""
    if not _geofences:
        _load_geofences()

    required = {"id", "name", "lat", "lng", "radius_km"}
    if not required.issubset(fence.keys()):
        return {"error": f"Missing required fields: {required - fence.keys()}"}

    # Prevent duplicates
    _geofences[:] = [g for g in _geofences if g["id"] != fence["id"]]
    fence.setdefault("category", "custom")
    fence.setdefault("color", "#3b82f6")
    _geofences.append(fence)
    _save_geofences()
    return {"status": "added", "geofence": fence}


def remove_geofence(fence_id: str) -> Dict[str, Any]:
    """Remove a geofence by ID."""
    if not _geofences:
        _load_geofences()
    before = len(_geofences)
    _geofences[:] = [g for g in _geofences if g["id"] != fence_id]
    _save_geofences()
    if len(_geofences) < before:
        return {"status": "removed", "id": fence_id}
    return {"status": "not_found", "id": fence_id}


def check_geofence_alerts(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check which entities are inside geofence zones. Returns alerts."""
    if not _geofences:
        _load_geofences()

    alerts = []

    for fence in _geofences:
        f_lat, f_lng, f_radius = fence["lat"], fence["lng"], fence["radius_km"]
        fence_alerts = {
            "geofence_id": fence["id"],
            "geofence_name": fence["name"],
            "category": fence.get("category", "custom"),
            "entities": [],
        }

        # Check military flights
        for flight in data.get("military_flights", []):
            lat, lng = flight.get("lat"), flight.get("lng")
            if lat is not None and lng is not None:
                dist = _haversine_km(f_lat, f_lng, lat, lng)
                if dist <= f_radius:
                    fence_alerts["entities"].append({
                        "type": "military_flight",
                        "id": flight.get("icao24", ""),
                        "callsign": flight.get("callsign", ""),
                        "country": flight.get("country", ""),
                        "distance_km": round(dist, 1),
                    })

        # Check ships
        for ship in data.get("ships", []):
            lat, lng = ship.get("lat"), ship.get("lng")
            if lat is not None and lng is not None:
                dist = _haversine_km(f_lat, f_lng, lat, lng)
                if dist <= f_radius:
                    ship_type = ship.get("type", "unknown")
                    if ship_type in ("carrier", "military_vessel"):
                        fence_alerts["entities"].append({
                            "type": "military_vessel",
                            "id": str(ship.get("mmsi", "")),
                            "name": ship.get("name", ""),
                            "ship_type": ship_type,
                            "country": ship.get("country", ""),
                            "distance_km": round(dist, 1),
                        })

        if fence_alerts["entities"]:
            fence_alerts["entity_count"] = len(fence_alerts["entities"])
            alerts.append(fence_alerts)

    return alerts
