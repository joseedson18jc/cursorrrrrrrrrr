"""
Data Export Service
Exports live dashboard data as GeoJSON or CSV.
"""

import csv
import io
import json
import time
from typing import Dict, Any, List


def _entities_to_features(entities: List[Dict], entity_type: str,
                          lat_key: str = "lat", lng_key: str = "lng") -> List[Dict]:
    """Convert a list of entity dicts to GeoJSON Features."""
    features = []
    for e in entities:
        lat = e.get(lat_key)
        lng = e.get(lng_key)
        if lat is None or lng is None:
            continue
        props = {k: v for k, v in e.items() if k not in (lat_key, lng_key, "trail")}
        props["_entity_type"] = entity_type
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": props,
        })
    return features


def export_geojson(data: Dict[str, Any], layers: List[str] | None = None) -> Dict:
    """Export data as a GeoJSON FeatureCollection."""
    all_features = []

    layer_map = {
        "commercial_flights": ("commercial_flights", "lat", "lng"),
        "military_flights": ("military_flights", "lat", "lng"),
        "private_flights": ("private_flights", "lat", "lng"),
        "private_jets": ("private_jets", "lat", "lng"),
        "tracked_flights": ("tracked_flights", "lat", "lng"),
        "ships": ("ships", "lat", "lng"),
        "satellites": ("satellites", "lat", "lng"),
        "earthquakes": ("earthquakes", "lat", "lng"),
        "cctv": ("cctv", "lat", "lon"),
        "gps_jamming": ("gps_jamming", "lat", "lng"),
        "firms_fires": ("firms_fires", "lat", "lng"),
        "internet_outages": ("internet_outages", "lat", "lng"),
        "datacenters": ("datacenters", "lat", "lng"),
        "kiwisdr": ("kiwisdr", "lat", "lon"),
        "military_bases": ("military_bases", "lat", "lng"),
        "power_plants": ("power_plants", "lat", "lng"),
    }

    active_layers = layers or list(layer_map.keys())

    for layer_name in active_layers:
        if layer_name not in layer_map:
            continue
        entity_type, lat_k, lng_k = layer_map[layer_name]
        items = data.get(entity_type, [])
        if items:
            all_features.extend(_entities_to_features(items, entity_type, lat_k, lng_k))

    return {
        "type": "FeatureCollection",
        "metadata": {
            "exported_at": time.time(),
            "feature_count": len(all_features),
            "layers": active_layers,
        },
        "features": all_features,
    }


def export_csv(data: Dict[str, Any], layer: str) -> str:
    """Export a single layer as CSV text."""
    layer_items = data.get(layer, [])
    if not layer_items:
        return ""

    output = io.StringIO()
    # Collect all unique keys across items (excluding complex objects)
    all_keys = []
    seen = set()
    for item in layer_items:
        for k, v in item.items():
            if k not in seen and not isinstance(v, (list, dict)):
                all_keys.append(k)
                seen.add(k)

    writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    for item in layer_items:
        # Filter out complex values
        row = {k: v for k, v in item.items() if not isinstance(v, (list, dict))}
        writer.writerow(row)

    return output.getvalue()
