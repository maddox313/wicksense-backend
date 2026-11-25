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


ELIGIBLE_PLANS = frozenset({"elite", "trial_elite"})
ELIGIBLE_STATUSES = frozenset({"active", "trialing"})
IDENTITY_FIELDS = (
    "user_id",
    "userId",
    "owner_id",
    "ownerId",
    "account_id",
    "accountId",
)


def subscription_allows_analyzer(row):
    """Eligible plans are elite and trial_elite while status is active or trialing."""
    plan = str((row or {}).get("plan") or "").strip().lower()
    status = str((row or {}).get("status") or "").strip().lower()
    if plan in ELIGIBLE_PLANS and status in ELIGIBLE_STATUSES:
        return True, None
    return False, "plan_ineligible"


def lookup_subscription_http(auth_header, user_id):
    """
    Read plan and status for the JWT user through the anon key.
    RLS allows that user to select only their own row. The service-role
    key is never sent. Body fields are never the lookup key.
    """
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None, "supabase_auth_not_configured"
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_subscriptions",
            params={"id": "eq.%s" % user_id, "select": "plan,status"},
            headers={
                "Authorization": auth_header,
                "apikey": SUPABASE_ANON_KEY,
                "Accept": "application/json",
            },
            timeout=15,
        )
    except requests.RequestException as err:
        log.warning("[auth] subscription lookup failed: %s", err)
        return None, "subscription_lookup_failed"
    if res.status_code != 200:
        log.warning("[auth] subscription lookup HTTP %s", res.status_code)
        return None, "subscription_lookup_failed"
    rows = res.json() or []
    if not rows:
        return {"plan": None, "status": None}, None
    row = rows[0] or {}
    return {"plan": row.get("plan"), "status": row.get("status")}, None


def guard_analyzer_request(auth_header, body=None, lookup_user=None, lookup_subscription=None):
    """
    Returns (user_id, None) or (None, (payload, status)).
    401 missing or invalid token. 403 ineligible plan or identity mismatch.
    A failed subscription read returns 503 and must not continue to Claude.
    """
    body = body or {}
    lookup_user = lookup_user or get_user_id_from_auth_header
    lookup_subscription = lookup_subscription or lookup_subscription_http

    user_id, auth_reason = lookup_user(auth_header)
    if not user_id:
        return None, (
            {"error": "Unauthorized", "reason": auth_reason or "missing_bearer_token"},
            401,
        )

    for field in IDENTITY_FIELDS:
        claimed = body.get(field)
        if claimed is not None and str(claimed).strip() and str(claimed) != str(user_id):
            return None, (
                {
                    "error": "Forbidden",
                    "reason": "identity_mismatch",
                    "detail": "%s does not match authenticated user" % field,
                },
                403,
            )

    subscription, sub_reason = lookup_subscription(auth_header, user_id)
    if sub_reason:
        status = 503 if sub_reason == "subscription_lookup_failed" else 401
        error = "Subscription lookup failed" if status == 503 else "Unauthorized"
        return None, ({"error": error, "reason": sub_reason}, status)

    allowed, reason = subscription_allows_analyzer(subscription or {})
    if not allowed:
        return None, ({"error": "Forbidden", "reason": reason or "plan_ineligible"}, 403)

    return user_id, None


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
