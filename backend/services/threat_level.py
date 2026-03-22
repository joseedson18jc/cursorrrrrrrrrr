"""
Threat Level Classification System
Computes a global threat level (1-5) from active data sources.

Levels:
  1 - NOMINAL    (green)  — Normal global activity
  2 - GUARDED    (blue)   — Slightly elevated activity
  3 - ELEVATED   (yellow) — Notable increase in one or more domains
  4 - HIGH       (orange) — Significant activity across domains
  5 - CRITICAL   (red)    — Extreme activity levels
"""

import time
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Thresholds for each signal (tuned to typical global baselines)
_THRESHOLDS = {
    "military_flights": [20, 40, 80, 120],      # count breakpoints
    "earthquakes_m5plus": [0, 1, 3, 5],          # M5+ quakes in 24h
    "gps_jamming_zones": [2, 5, 10, 20],         # active jamming zones
    "conflict_events": [50, 150, 400, 800],      # GDELT event count
    "fire_hotspots": [500, 2000, 5000, 10000],   # FIRMS fire count
    "internet_outages": [1, 3, 6, 10],           # IODA outage regions
}

LEVEL_NAMES = {
    1: "NOMINAL",
    2: "GUARDED",
    3: "ELEVATED",
    4: "HIGH",
    5: "CRITICAL",
}

LEVEL_COLORS = {
    1: "#22c55e",  # green
    2: "#3b82f6",  # blue
    3: "#eab308",  # yellow
    4: "#f97316",  # orange
    5: "#ef4444",  # red
}


def _score_signal(value: float, thresholds: list) -> int:
    """Return 0-4 score based on which threshold bracket the value falls in."""
    for i, t in enumerate(thresholds):
        if value <= t:
            return i
    return 4


def compute_threat_level(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze all live data and return a threat assessment."""
    scores = {}

    # Military flight count
    mil_count = len(data.get("military_flights", []))
    scores["military_flights"] = _score_signal(mil_count, _THRESHOLDS["military_flights"])

    # Strong earthquakes (M5+)
    quakes = data.get("earthquakes", [])
    m5_count = sum(1 for q in quakes if (q.get("mag") or 0) >= 5.0)
    scores["earthquakes_m5plus"] = _score_signal(m5_count, _THRESHOLDS["earthquakes_m5plus"])

    # GPS jamming zones
    jam_count = len(data.get("gps_jamming", []))
    scores["gps_jamming_zones"] = _score_signal(jam_count, _THRESHOLDS["gps_jamming_zones"])

    # Conflict events (GDELT)
    gdelt_count = len(data.get("gdelt", []))
    scores["conflict_events"] = _score_signal(gdelt_count, _THRESHOLDS["conflict_events"])

    # Fire hotspots
    fire_count = len(data.get("firms_fires", []))
    scores["fire_hotspots"] = _score_signal(fire_count, _THRESHOLDS["fire_hotspots"])

    # Internet outages
    outage_count = len(data.get("internet_outages", []))
    scores["internet_outages"] = _score_signal(outage_count, _THRESHOLDS["internet_outages"])

    # Weighted average → final level (1-5)
    if scores:
        avg_score = sum(scores.values()) / len(scores)
        level = max(1, min(5, int(avg_score) + 1))
    else:
        level = 1

    return {
        "level": level,
        "name": LEVEL_NAMES[level],
        "color": LEVEL_COLORS[level],
        "signals": {
            "military_flights": mil_count,
            "earthquakes_m5plus": m5_count,
            "gps_jamming_zones": jam_count,
            "conflict_events": gdelt_count,
            "fire_hotspots": fire_count,
            "internet_outages": outage_count,
        },
        "signal_scores": scores,
        "computed_at": time.time(),
    }
