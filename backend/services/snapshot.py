"""Shared warm-start snapshots (Supabase). Database setup: backend/supabase/snapshot_store.sql

Why: on serverless/container hosts (Vercel) the backend runs as several
short-lived instances. Each one starts with an empty in-memory store and needs
minutes to rebuild ships (AIS accumulates slowly), satellites and the slow-tier
layers, so visitors see an empty or half-filled map depending on which
instance answers. Instances therefore save a compressed snapshot of the
slow-to-rebuild data to Supabase, and every new instance loads it on boot.

What is stored (three rows):
  flights — the last 150 s of per-region adsb.lol aircraft (11 fields each,
          positions rounded to ~10 m) plus the military list. A new instance
          adopts them as its region cache and publishes immediately, and a
          region that adsb.lol refuses (HTTP 429) can be covered by a sibling's
          copy. Saved only when the three largest regions are present, so a
          partially failed instance can never overwrite a complete snapshot.
  fast  — AIS vessel store (with per-vessel timestamps) and satellites.
          Restored only if <= FAST_MAX_AGE old.
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
FLIGHTS_MAX_AGE = 150         # flight lists older than this are not shared or restored
FLIGHTS_SAVE_INTERVAL = 75
FLIGHTS_WARMUP = 45

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


_last_flights_save = 0.0


def save_flights() -> None:
    """Share this instance's fresh per-region flight lists and the military list.

    Guard: only save a COMPLETE picture (the three largest regions present),
    so an instance that is itself missing a region can never overwrite a good
    shared snapshot with a worse one."""
    global _last_flights_save
    if not enabled() or time.time() - _started < FLIGHTS_WARMUP:
        return
    if time.time() - _last_flights_save < FLIGHTS_SAVE_INTERVAL:
        return
    if not _save_lock.acquire(blocking=False):
        return
    try:
        from services.fetchers.flights import export_regions_for_snapshot, SNAPSHOT_REQUIRED_REGIONS
        regions = export_regions_for_snapshot(max_age=FLIGHTS_MAX_AGE)
        if not all(regions.get(k, {}).get("ac") for k in SNAPSHOT_REQUIRED_REGIONS):
            return
        with _data_lock:
            mil = {"military_flights": list(latest_data.get("military_flights") or []),
                   "uavs": list(latest_data.get("uavs") or [])}
        n = sum(len(v["ac"]) for v in regions.values())
        _save("flights", {"regions": regions, "military": mil, "saved_at": time.time()},
              {"regions": len(regions), "aircraft": n, "military": len(mil["military_flights"])})
        _last_flights_save = time.time()
    except Exception as e:
        logger.warning(f"Snapshot save (flights) failed: {e}")
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


_status: dict = {}


def status() -> dict:
    """Restore outcome for this instance (diagnostics for /api/health/upstreams)."""
    return {"enabled": enabled(), **_status}


def _load_row(kind: str):
    """Download one snapshot row. Returns (kind, row_or_None, seconds, error)."""
    t0 = time.time()
    try:
        rows = _rpc("load_snapshot", {"secret": _SECRET, "snap_id": kind}, timeout=15)
        return kind, (rows[0] if rows else None), time.time() - t0, None
    except Exception as e:
        return kind, None, time.time() - t0, str(e)[:160]


def restore() -> None:
    """Load shared snapshots into this instance. Never overwrites data this
    instance already fetched itself. Safe to call when disabled, and safe to
    run concurrently with the first live fetch (it runs in its own thread).

    The three rows download in parallel; they are then applied in order of
    importance (flights, fast, slow)."""
    import concurrent.futures
    t_start = time.time()
    _status.clear()
    _status["started_at"] = t_start
    if not enabled():
        logger.info("Snapshot store not configured — cold start without warm data")
        return
    kinds = (("flights", FLIGHTS_MAX_AGE), ("fast", FAST_MAX_AGE), ("slow", SLOW_MAX_AGE))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        loaded = {k: v for k, *v in pool.map(_load_row, [k for k, _ in kinds])}
    _status["download_secs"] = round(time.time() - t_start, 2)

    for kind, max_age in kinds:
        row, dl_secs, err = loaded[kind]
        info = {"download_secs": round(dl_secs, 2)}
        _status[kind] = info
        try:
            if err:
                info["outcome"] = "download_failed"; info["error"] = err
                logger.warning(f"Snapshot {kind}: download failed after {dl_secs:.1f}s: {err}")
                continue
            if not row:
                info["outcome"] = "none_stored"
                logger.info(f"Snapshot {kind}: none stored yet")
                continue
            age = _age_seconds(row["updated_at"])
            info["age_s"] = round(age)
            if age > max_age:
                info["outcome"] = "too_old"
                logger.info(f"Snapshot {kind}: {age:.0f}s old (> {max_age}s) — skipped")
                continue
            snap = _decode(row["payload"])
            if kind == "flights":
                from services.fetchers.flights import adopt_snapshot_regions, publish_from_region_cache
                adopted = adopt_snapshot_regions(snap.get("regions") or {}, max_age=FLIGHTS_MAX_AGE)
                published = publish_from_region_cache() if adopted else 0
                mil = snap.get("military") or {}
                with _data_lock:
                    if _is_empty(latest_data.get("military_flights")) and mil.get("military_flights"):
                        latest_data["military_flights"] = mil["military_flights"]
                        latest_data["uavs"] = mil.get("uavs") or []
                info.update(outcome="restored", regions=adopted, published=published,
                            military=len(mil.get("military_flights") or []))
                logger.info(f"Snapshot flights restored ({age:.0f}s old): {adopted} regions, "
                            f"{published} aircraft published, {info['military']} military")
            elif kind == "fast":
                from services.ais_stream import merge_snapshot_vessels
                n = merge_snapshot_vessels(snap.get("vessels") or [])
                with _data_lock:
                    if _is_empty(latest_data.get("satellites")) and snap.get("satellites"):
                        latest_data["satellites"] = snap["satellites"]
                        latest_data["satellite_source"] = snap.get("satellite_source") or "snapshot"
                info.update(outcome="restored", vessels=n, satellites=len(snap.get("satellites") or []))
                logger.info(f"Snapshot fast restored ({age:.0f}s old): {n} vessels, "
                            f"{info['satellites']} satellites")
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
                info.update(outcome="restored", layers=restored)
                logger.info(f"Snapshot slow restored ({age:.0f}s old): {', '.join(restored) or 'nothing new'}")
        except Exception as e:
            info["outcome"] = "apply_failed"; info["error"] = str(e)[:160]
            logger.warning(f"Snapshot restore ({kind}) failed (non-fatal): {e}")
    # Publish restored vessels immediately instead of waiting for the next fast cycle.
    try:
        from services.fetchers.geo import fetch_ships
        fetch_ships()
    except Exception as e:
        logger.debug(f"Post-restore ship publish failed: {e}")
    _status["total_secs"] = round(time.time() - t_start, 2)
