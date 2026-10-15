import logging
import json
import os
import subprocess
import shutil
import time
import threading
import uuid
import requests
from pathlib import Path
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Reusable session with connection pooling and retry logic.
# Only retry once (total=1) to fail fast — the curl fallback is the real safety net.
_session = requests.Session()
_retry = Retry(total=1, backoff_factor=0.3, status_forcelist=[502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry, pool_maxsize=20))
_session.mount("http://", HTTPAdapter(max_retries=_retry, pool_maxsize=10))

# Find bash for curl fallback — Git bash's curl has the TLS features
# needed to pass CDN fingerprint checks (brotli, zstd, libpsl)
_BASH_PATH = shutil.which("bash") or "bash"

# Cache domains where requests fails — skip straight to curl for 5 minutes
_domain_fail_cache: dict[str, float] = {}
_DOMAIN_FAIL_TTL = 300  # 5 minutes

# Circuit breaker: track domains where BOTH requests AND curl fail
# If a domain failed completely within the last 2 minutes, skip it entirely
_circuit_breaker: dict[str, float] = {}
_CIRCUIT_BREAKER_TTL = 120  # 2 minutes

# Lock protecting _domain_fail_cache and _circuit_breaker mutations
_cb_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Per-operator outbound identification
# ---------------------------------------------------------------------------
#
# Ported from upstream ShadowBroker (issues #289 / #290 / #291). Every
# third-party API this backend calls used to identify itself with one shared
# "ShadowBroker-OSINT" User-Agent, so from an upstream's perspective every
# install in the world looked like a single entity. adsb.lol now answers
# HTTP 403 to any User-Agent containing "shadowbroker", which silently empties
# the flights layer on every install.
#
# Fix: each install identifies with its own stable pseudonymous handle as the
# entire User-Agent product token. Upstreams see "operator-7f3a92" (or the
# configured OPERATOR_HANDLE), so a misbehaving operator can be rate-limited
# or blocked individually without taking down everyone else.
#
# - Auto-generated on first use when OPERATOR_HANDLE is unset.
# - Persisted to backend/data/operator_handle.json across restarts (ephemeral
#   hosts simply regenerate one per instance).
# - Override with OPERATOR_HANDLE (e.g. your GitHub handle) for traceability,
#   or SHADOWBROKER_USER_AGENT to replace the whole string.

_OPERATOR_HANDLE_FILE = Path(__file__).parent.parent / "data" / "operator_handle.json"
_OPERATOR_HANDLE_CACHE: str = ""
_OPERATOR_HANDLE_LOCK = threading.Lock()


def _normalize_handle(raw: str) -> str:
    """Strip whitespace, lowercase, replace header-unsafe chars with dashes."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in raw.strip().lower())
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-")
    return safe[:48] if safe else "anonymous"


def _generate_operator_handle() -> str:
    """``operator-7f3a92`` — neutral prefix plus 6 hex chars of a fresh uuid4."""
    return f"operator-{uuid.uuid4().hex[:6]}"


def _load_persisted_operator_handle() -> str:
    try:
        if _OPERATOR_HANDLE_FILE.exists():
            data = json.loads(_OPERATOR_HANDLE_FILE.read_text(encoding="utf-8"))
            return str(data.get("handle", "") or "").strip()
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return ""


def _persist_operator_handle(handle: str) -> None:
    """Atomic save; failure is non-fatal (we just regenerate next restart)."""
    try:
        _OPERATOR_HANDLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OPERATOR_HANDLE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "handle": handle,
            "_meta": {
                "purpose": "Per-install operator handle for outbound third-party API attribution.",
                "see": "backend/services/network_utils.py:outbound_user_agent",
            },
        }, indent=2), encoding="utf-8")
        os.replace(tmp, _OPERATOR_HANDLE_FILE)
    except OSError as exc:
        logger.debug("Could not persist operator_handle (continuing in-memory): %s", exc)


def get_operator_handle() -> str:
    """Resolution order: OPERATOR_HANDLE env → process cache → disk → fresh."""
    global _OPERATOR_HANDLE_CACHE
    with _OPERATOR_HANDLE_LOCK:
        configured = (os.environ.get("OPERATOR_HANDLE") or "").strip()
        if configured:
            return _normalize_handle(configured)
        if _OPERATOR_HANDLE_CACHE:
            return _OPERATOR_HANDLE_CACHE
        persisted = _load_persisted_operator_handle()
        if persisted:
            _OPERATOR_HANDLE_CACHE = _normalize_handle(persisted)
            return _OPERATOR_HANDLE_CACHE
        fresh = _generate_operator_handle()
        logger.warning(
            "OPERATOR_HANDLE is not set; using auto-generated %s. adsb.lol currently "
            "refuses auto-generated handles (HTTP 403), so the flights layer will be "
            "empty. Set OPERATOR_HANDLE to your GitHub handle or organisation name.",
            fresh,
        )
        _persist_operator_handle(fresh)
        _OPERATOR_HANDLE_CACHE = fresh
        return fresh


def outbound_user_agent(purpose: str = "") -> str:
    """User-Agent for an outbound third-party request: the handle only, e.g.
    ``operator-7f3a92`` or ``operator-7f3a92 (purpose: wikipedia)``."""
    handle = get_operator_handle()
    if purpose:
        return f"{handle} (purpose: {_normalize_handle(purpose)})"
    return handle


def default_user_agent() -> str:
    """Default for ``fetch_with_curl``; SHADOWBROKER_USER_AGENT overrides all."""
    custom = (os.environ.get("SHADOWBROKER_USER_AGENT") or "").strip()
    return custom if custom else outbound_user_agent()


class _DummyResponse:
    """Minimal response object matching requests.Response interface."""
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.content = text.encode('utf-8', errors='replace')

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}: {self.text[:100]}")


def fetch_with_curl(url, method="GET", json_data=None, timeout=15, headers=None):
    """Wrapper to bypass aggressive local firewall that blocks Python but permits curl.

    Falls back to running curl through Git bash, which has the TLS features
    (brotli, zstd, libpsl) needed to pass CDN fingerprint checks that block
    both Python requests and the barebones Windows system curl.
    """
    default_headers = {
        "User-Agent": default_user_agent(),
    }
    if headers:
        default_headers.update(headers)

    domain = urlparse(url).netloc

    # Circuit breaker: if domain failed completely <2min ago, fail fast
    with _cb_lock:
        if domain in _circuit_breaker and (time.time() - _circuit_breaker[domain]) < _CIRCUIT_BREAKER_TTL:
            raise Exception(f"Circuit breaker open for {domain} (failed <{_CIRCUIT_BREAKER_TTL}s ago)")

    # Check if this domain recently failed with requests — skip straight to curl
    with _cb_lock:
        _skip_requests = domain in _domain_fail_cache and (time.time() - _domain_fail_cache[domain]) < _DOMAIN_FAIL_TTL
    if not _skip_requests:
        try:
            # Use a short connect timeout (3s) so firewall blocks fail fast,
            # but allow the full timeout for reading the response body.
            req_timeout = (min(3, timeout), timeout)
            if method == "POST":
                res = _session.post(url, json=json_data, timeout=req_timeout, headers=default_headers)
            else:
                res = _session.get(url, timeout=req_timeout, headers=default_headers)
            res.raise_for_status()
            # Clear failure caches on success
            with _cb_lock:
                _domain_fail_cache.pop(domain, None)
                _circuit_breaker.pop(domain, None)
            return res
        except (requests.RequestException, ConnectionError, TimeoutError, OSError) as e:
            logger.warning(f"Python requests failed for {url} ({e}), falling back to bash curl...")
            with _cb_lock:
                _domain_fail_cache[domain] = time.time()

    # Curl fallback — reached from both _skip_requests and requests-exception paths
    _CURL_PATH = shutil.which("curl") or "curl"
    cmd = [_CURL_PATH, "-s", "-w", "\n%{http_code}"]
    for k, v in default_headers.items():
        cmd += ["-H", f"{k}: {v}"]
    if method == "POST" and json_data:
        cmd += ["-X", "POST", "-H", "Content-Type: application/json",
                "--data-binary", "@-"]
    cmd.append(url)

    try:
        stdin_data = json.dumps(json_data) if (method == "POST" and json_data) else None
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5,
            input=stdin_data
        )
        if res.returncode == 0 and res.stdout.strip():
            # Parse HTTP status code from -w output (last line)
            lines = res.stdout.rstrip().rsplit("\n", 1)
            body = lines[0] if len(lines) > 1 else res.stdout
            http_code = int(lines[-1]) if len(lines) > 1 and lines[-1].strip().isdigit() else 200
            if http_code < 400:
                with _cb_lock:
                    _circuit_breaker.pop(domain, None)  # Clear circuit breaker on success
            return _DummyResponse(http_code, body)
        else:
            logger.error(f"bash curl fallback failed: exit={res.returncode} stderr={res.stderr[:200]}")
            with _cb_lock:
                _circuit_breaker[domain] = time.time()
            return _DummyResponse(500, "")
    except (subprocess.SubprocessError, ConnectionError, TimeoutError, OSError) as curl_e:
        logger.error(f"bash curl fallback exception: {curl_e}")
        with _cb_lock:
            _circuit_breaker[domain] = time.time()
        return _DummyResponse(500, "")
