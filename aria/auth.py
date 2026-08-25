"""Supabase JWT tenant auth for ARIA and other private Flask routes."""

from __future__ import annotations

import logging
from typing import Any

from flask import jsonify, request

from wicksense_backend.alpaca_helpers import (
    get_user_id_from_request,
    supabase_auth_configured,
)

log = logging.getLogger("wicksense.tenant_auth")

# Safe defaults — never trust client-claimed execute_trades.
DEFAULT_ARIA_PERMISSIONS: dict[str, bool] = {
    "execute_trades": False,
    "auto_save_strategy_parameters": False,
    "save_strategy_parameters": False,
    "propose_strategy_parameters": True,
    "read_strategy_parameters": True,
    "apply_strategy_parameters_after_confirmation": True,
    "external_actions": False,
    "send_notifications": False,
}


def require_authenticated_user():
    """
    Validate Authorization: Bearer <supabase_access_token>.
    Returns (user_id, auth_header) or (None, (response, status)).
    """
    auth_header = request.headers.get("Authorization", "") or ""
    if not supabase_auth_configured():
        return None, (
            jsonify({
                "error": "Unauthorized",
                "reason": "supabase_auth_not_configured",
            }),
            503,
        )
    user_id, reason = get_user_id_from_request(auth_header)
    if not user_id:
        return None, (
            jsonify({
                "error": "Unauthorized",
                "reason": reason or "unauthorized",
            }),
            401,
        )
    return user_id, auth_header


def reject_identity_spoof(authenticated_user_id: str, payload: dict[str, Any] | None) -> tuple | None:
    """
    If the client sends user_id / account_id / studentId / trainerId that
    disagrees with the JWT subject, reject with 403.
    Returns (response, status) or None if OK.
    """
    if not payload:
        return None
    spoof_keys = (
        "user_id",
        "userId",
        "account_id",
        "accountId",
        "studentId",
        "student_id",
        "trainerId",
        "trainer_id",
    )
    for key in spoof_keys:
        claimed = payload.get(key)
        if claimed is None or claimed == "":
            continue
        if str(claimed) != str(authenticated_user_id):
            log.warning(
                "[tenant_auth] identity spoof rejected key=%s claimed=%s auth=%s",
                key,
                claimed,
                authenticated_user_id,
            )
            return (
                jsonify({
                    "error": "Forbidden",
                    "reason": "identity_mismatch",
                    "detail": f"{key} does not match authenticated user",
                }),
                403,
            )
    return None


def resolve_aria_permissions(auth_header: str, user_id: str, client_hints: dict | None = None) -> dict[str, bool]:
    """
    Server-derived ARIA permissions. Client claims are ignored for high-impact flags.
    Soft prefs (alerts) may be read from trusted Supabase user_preferences via JWT.
    """
    perms = dict(DEFAULT_ARIA_PERMISSIONS)
    # Never honor client execute_trades / external override for execution.
    try:
        from aria.supabase_user import fetch_user_preferences

        prefs = fetch_user_preferences(auth_header, user_id) or {}
        allow_alerts = prefs.get("allow_aria_alerts")
        if allow_alerts is None and isinstance(prefs.get("extra"), dict):
            allow_alerts = prefs["extra"].get("allow_aria_alerts")
        if allow_alerts is None:
            allow_alerts = True
        allow_alerts = bool(allow_alerts)
        perms["external_actions"] = allow_alerts
        perms["send_notifications"] = allow_alerts
    except Exception as exc:
        log.warning("[tenant_auth] preference lookup failed for %s: %s", user_id, exc)
        # Fail closed on external/notify if prefs unavailable
        perms["external_actions"] = False
        perms["send_notifications"] = False

    # Explicitly ignore any client permission hints for execute_trades
    _ = client_hints
    perms["execute_trades"] = False
    return perms


def sanitize_aria_context(context: dict | None, user_id: str) -> dict:
    """
    Strip credential-like keys and force authenticated identity into context.
    Never pass alpaca secrets / API keys into the model context.
    """
    ctx = dict(context or {})
    ctx["authenticated_user_id"] = user_id
    # Remove any client attempt to set another identity
    for key in ("user_id", "userId", "account_id", "accountId"):
        if key in ctx and str(ctx.get(key)) != str(user_id):
            ctx.pop(key, None)
    ctx["user_id"] = user_id

    def _scrub(obj, depth=0):
        if depth > 8 or obj is None:
            return obj
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if any(
                    s in lk
                    for s in (
                        "api_key",
                        "apikey",
                        "secret_key",
                        "secretkey",
                        "password",
                        "private_key",
                        "access_token",
                        "refresh_token",
                        "authorization",
                    )
                ):
                    continue
                out[k] = _scrub(v, depth + 1)
            return out
        if isinstance(obj, list):
            return [_scrub(x, depth + 1) for x in obj[:200]]
        return obj

    return _scrub(ctx)
