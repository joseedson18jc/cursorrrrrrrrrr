"""Startup environment validation — called once in the FastAPI lifespan hook.

Ensures required env vars are present before the scheduler starts.
Logs warnings for optional keys that degrade functionality when missing.
"""
import os
import sys
import logging

logger = logging.getLogger(__name__)

# Keys grouped by criticality
_REQUIRED = {
    # Empty for now — add keys here only if the app literally cannot function without them
}

_CRITICAL_WARN = {
    "ADMIN_KEY": "Authentication for /api/settings and /api/system/update — endpoints are UNPROTECTED without it!",
}

_OPTIONAL = {
    "AIS_API_KEY": "aisstream.io global vessel stream (without it, ships come only from the keyless Digitraffic Baltic feed)",
    "OPENSKY_CLIENT_ID": "OpenSky OAuth2 — gap-fill flights in Africa/Asia/LatAm",
    "OPENSKY_CLIENT_SECRET": "OpenSky OAuth2 — gap-fill flights in Africa/Asia/LatAm",
    # LTA_ACCOUNT_KEY intentionally not listed: the Singapore camera ingestor
    # uses the keyless data.gov.sg traffic-images endpoint.
}


def validate_env(*, strict: bool = True) -> bool:
    """Validate environment variables at startup.

    Args:
        strict: If True, exit the process on missing required keys.
                If False, only log errors (useful for tests).

    Returns:
        True if all required keys are present, False otherwise.
    """
    all_ok = True

    # Required keys — must be set
    for key, desc in _REQUIRED.items():
        value = os.environ.get(key, "").strip()
        if not value:
            logger.error(
                "❌ REQUIRED env var %s is not set. %s\n"
                "   Set it in .env or via Docker secrets (%s_FILE).",
                key, desc, key,
            )
            all_ok = False

    if not all_ok and strict:
        logger.critical("Startup aborted — required environment variables are missing.")
        sys.exit(1)

    # Critical-warn keys — app works but security/functionality is degraded
    for key, desc in _CRITICAL_WARN.items():
        value = os.environ.get(key, "").strip()
        if not value:
            logger.critical(
                "🔓 CRITICAL: env var %s is not set — %s\n"
                "   This is safe for local dev but MUST be set in production.",
                key, desc,
            )

    # Optional keys — warn if missing
    for key, desc in _OPTIONAL.items():
        value = os.environ.get(key, "").strip()
        if not value:
            logger.warning(
                "⚠️  Optional env var %s is not set — %s", key, desc
            )

    if all_ok:
        logger.info("✅ Environment validation passed.")

    return all_ok
