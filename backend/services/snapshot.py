"""Shared warm-start snapshots (Supabase). Database setup: backend/supabase/snapshot_store.sql

Why: on serverless/container hosts (Vercel) the backend runs as several
short-lived instances. Each one starts with an empty in-memory store and needs
minutes to rebuild ships (AIS accumulates slowly), satellites and the slow-tier
layers, so visitors see an empty or half-filled map depending on which
instance answers. Instances therefore save a compressed snapshot of the
slow-to-rebuild data to Supabase, and every new instance loads it on boot.

What is stored (two rows):
  fast  — AIS vessel store (with per-vessel timestamps) and satellites.
          Restored only if <= FAST_MAX_AGE old; flights are NOT stored because
          they refill from adsb.lol within seconds and stale positions mislead.
  slow  — news, quakes, fires, GDELT, frontlines, outages, KiwiSDR, CCTV,
          markets, weather. Restored if <= SLOW_MAX_AGE old.
Bundled static datasets (power plants, data centers, bases) load from disk
instantly and are not stored.

Storage: Supabase project with a private table reachable only through two
SECURITY DEFINER RPCs (save_snapshot / load_snapshot) that verify
SNAPSHOT_SECRET. Disabled unless all three env vars below are set, so local
and Docker installs behave exactly as before.

  SNAPSHOT_SUPABASE_URL  e.g. https://<ref>.supabase.co
  SNAPSHOT_SUPABASE_KEY  the project's anon / publishable key
  SNAPSHOT_SECRET        shared secret checked inside the RPCs
"""
import base64
import gzip
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

from services.fetchers._store import latest_data, source_timestamps, _data_lock

logger = logging.getLogger(__name__)

_URL = os.environ.get("SNAPSHOT_SUPABASE_URL", "").rstrip("/")
_KEY = os.environ.get("SNAPSHOT_SUPABASE_KEY", "")
_SECRET = os.environ.get("SNAPSHOT_SECRET", "")

FAST_MAX_AGE = 10 * 60        # moving objects: older positions are misleading
SLOW_MAX_AGE = 6 * 3600       # news/quakes/fires stay useful for hours
FAST_SAVE_INTERVAL = 120      # seconds between fast saves per instance
WARMUP_SECONDS = 90           # never save before this instance has fetched itself

SLOW_KEYS = [
    "news", "stocks", "oil", "weather", "earthquakes", "frontlines", "gdelt",
    "kiwisdr", "space_weather", "internet_outages", "firms_fires", "cctv",
]

_started = time.time()
_last_hash: dict[str, str] = {}
_last_fast_save = 0.0
_save_lock = threading.Lock()


def enabled() -> bool:
    return bool(_URL and _KEY and _SECRET)


def _rpc(name: str, body: dict, timeout: float = 20):
    r = requests.post(
        f"{_URL}/rest/v1/rpc/{name}",
        json=body,
        headers={
            "apikey": _KEY,
            "Authorization": f"Bearer {_KEY}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        },
        timeout=timeout,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"{name} HTTP {r.status_code}: {r.text[:160]}")
    return r.json()


def _encode(obj) -> tuple[str, str]:
    raw = json.dumps(obj, separators=(",", ":"), default=str).encode()
    digest = hashlib.sha1(raw).hexdigest()
    return base64.b64encode(gzip.compress(raw, 9)).decode(), digest


def _decode(payload: str):
    return json.loads(gzip.decompress(base64.b64decode(payload)))


def _is_empty(v) -> bool:
    return v is None or v == [] or v == {}


# --------------------------------------------------------------------------
# Save
# --------------------------------------------------------------------------
def _save(kind: str, data: dict, meta: dict) -> None:
    payload, digest = _encode(data)
    if _last_hash.get(kind) == digest:
        return
    meta = {**meta, "uptime_s": round(time.time() - _started), "bytes_b64": len(payload)}
    _rpc("save_snapshot", {"secret": _SECRET, "snap_id": kind, "payload": payload, "meta": meta})
    _last_hash[kind] = digest
    logger.info(f"Snapshot saved: {kind} ({len(payload) // 1024} KB, {meta})")


def save_fast() -> None:
    """Called after each fast-tier cycle; rate-limited per instance."""
    global _last_fast_save
    if not enabled() or time.time() - _started < WARMUP_SECONDS:
        return
    if time.time() - _last_fast_save < FAST_SAVE_INTERVAL:
        return
    if not _save_lock.acquire(blocking=False):
        return
    try:
        from services.ais_stream import export_vessels_for_snapshot
        vessels = export_vessels_for_snapshot()
        with _data_lock:
            sats = list(latest_data.get("satellites") or [])
            sat_source = latest_data.get("satellite_source")
        if len(vessels) < 50 and not sats:
            return  # nothing worth sharing yet
        _save("fast", {"vessels": vessels, "satellites": sats, "satellite_source": sat_source},
              {"vessels": len(vessels), "satellites": len(sats)})
        _last_fast_save = time.time()
    except Exception as e:
        logger.warning(f"Snapshot save (fast) failed: {e}")
    finally:
        _save_lock.release()


def save_slow() -> None:
    """Called after each slow-tier cycle."""
    if not enabled() or time.time() - _started < WARMUP_SECONDS:
        return
    try:
        with _data_lock:
            data = {k: latest_data.get(k) for k in SLOW_KEYS}
            fresh = {k: source_timestamps[k] for k in SLOW_KEYS if k in source_timestamps}
        if all(_is_empty(v) for v in data.values()):
            return
        counts = {k: len(v) for k, v in data.items() if isinstance(v, (list, dict))}
        _save("slow", {"data": data, "freshness": fresh}, counts)
    except Exception as e:
        logger.warning(f"Snapshot save (slow) failed: {e}")


# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------
def _age_seconds(updated_at: str) -> float:
    ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - ts).total_seconds()


def restore() -> None:
    """Load shared snapshots into this instance. Never overwrites data this
    instance already fetched itself. Safe to call when disabled."""
    if not enabled():
        logger.info("Snapshot store not configured — cold start without warm data")
        return
    for kind, max_age in (("fast", FAST_MAX_AGE), ("slow", SLOW_MAX_AGE)):
        try:
            rows = _rpc("load_snapshot", {"secret": _SECRET, "snap_id": kind}, timeout=30)
            if not rows:
                logger.info(f"Snapshot {kind}: none stored yet")
                continue
            age = _age_seconds(rows[0]["updated_at"])
            if age > max_age:
                logger.info(f"Snapshot {kind}: {age:.0f}s old (> {max_age}s) — skipped")
                continue
            snap = _decode(rows[0]["payload"])
            if kind == "fast":
                from services.ais_stream import merge_snapshot_vessels
                n = merge_snapshot_vessels(snap.get("vessels") or [])
                with _data_lock:
                    if _is_empty(latest_data.get("satellites")) and snap.get("satellites"):
                        latest_data["satellites"] = snap["satellites"]
                        latest_data["satellite_source"] = snap.get("satellite_source") or "snapshot"
                logger.info(f"Snapshot fast restored ({age:.0f}s old): {n} vessels, "
                            f"{len(snap.get('satellites') or [])} satellites")
            else:
                restored = []
                with _data_lock:
                    for k, v in (snap.get("data") or {}).items():
                        if k in SLOW_KEYS and _is_empty(latest_data.get(k)) and not _is_empty(v):
                            latest_data[k] = v
                            restored.append(k)
                    for k, ts in (snap.get("freshness") or {}).items():
                        if k in restored:
                            source_timestamps.setdefault(k, ts)
                logger.info(f"Snapshot slow restored ({age:.0f}s old): {', '.join(restored) or 'nothing new'}")
        except Exception as e:
            logger.warning(f"Snapshot restore ({kind}) failed (non-fatal): {e}")
    # Publish restored vessels immediately instead of waiting for the next fast cycle.
    try:
        from services.fetchers.geo import fetch_ships
        fetch_ships()
    except Exception as e:
        logger.debug(f"Post-restore ship publish failed: {e}")
