"""
Minimal Supabase JWT verification for video-analyzer routes.
Validates Authorization: Bearer <user access_token> via Supabase Auth /user.
"""

import logging
import os

import requests

log = logging.getLogger("wicksense.video-analyzer.auth")


def _env_first(*names):
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


SUPABASE_URL = _env_first("SUPABASE_URL", "VITE_SUPABASE_URL").rstrip("/")
SUPABASE_ANON_KEY = _env_first("SUPABASE_ANON_KEY", "VITE_SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = _env_first(
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_KEY",
)


def _api_key():
    # Prefer anon for Auth /user lookups; service_role also works as apikey.
    return SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY


def auth_configured():
    return bool(SUPABASE_URL and _api_key())


def get_user_id_from_auth_header(auth_header):
    """
    Returns (user_id, error_reason).
    error_reason is None on success.
    """
    if not auth_header or not str(auth_header).startswith("Bearer "):
        return None, "missing_bearer_token"

    if not auth_configured():
        log.error(
            "[auth] Supabase auth not configured — set SUPABASE_URL and "
            "SUPABASE_ANON_KEY (or SUPABASE_SERVICE_ROLE_KEY) on Render"
        )
        return None, "supabase_auth_not_configured"

    try:
        res = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": auth_header,
                "apikey": _api_key(),
            },
            timeout=15,
        )
        if res.status_code != 200:
            return None, "invalid_or_expired_token"
        user_id = (res.json() or {}).get("id")
        if not user_id:
            return None, "invalid_or_expired_token"
        return user_id, None
    except requests.RequestException as err:
        log.warning("[auth] auth user lookup failed: %s", err)
        return None, "auth_lookup_failed"
