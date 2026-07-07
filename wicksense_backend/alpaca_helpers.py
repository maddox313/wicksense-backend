"""Alpaca + Supabase helpers for wicksense-backend /alpaca/* routes."""

import os
import re
import json
import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger("wicksense.alpaca")

ALPACA_PAPER_BASE = "https://paper-api.alpaca.markets/v2"
ALPACA_LIVE_BASE = "https://api.alpaca.markets/v2"
ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
BRACKET_MIN_OFFSET = 0.01


def _env_first(*names):
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


SUPABASE_URL = _env_first("SUPABASE_URL", "VITE_SUPABASE_URL").rstrip("/")
SUPABASE_ANON_KEY = _env_first(
    "SUPABASE_ANON_KEY",
    "VITE_SUPABASE_ANON_KEY",
)
SUPABASE_SERVICE_ROLE_KEY = _env_first(
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_KEY",
)


def supabase_api_key():
    """Project API key for Supabase REST/auth calls (anon preferred)."""
    return SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY


def supabase_auth_configured():
    return bool(SUPABASE_URL and supabase_api_key())


def _supabase_rest_headers(auth_header=None):
    api_key = supabase_api_key()
    if not api_key:
        return None
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    if auth_header and auth_header.startswith("Bearer "):
        headers["Authorization"] = auth_header
    elif SUPABASE_SERVICE_ROLE_KEY:
        headers["Authorization"] = f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
    else:
        return None
    return headers


def to_uuid_or_null(value):
    if not isinstance(value, str) or not value:
        return None
    return value if UUID_RE.match(value) else None


def get_user_id_from_request(auth_header):
    """
    Validate Supabase user JWT from Authorization: Bearer <access_token>.
    Returns (user_id, error_reason).
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, "missing_bearer_token"

    if not supabase_auth_configured():
        log.error(
            "[alpaca] Supabase auth not configured — set SUPABASE_URL and SUPABASE_ANON_KEY on Render"
        )
        return None, "supabase_auth_not_configured"

    try:
        res = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": auth_header,
                "apikey": supabase_api_key(),
            },
            timeout=15,
        )
        if res.status_code != 200:
            log.warning(
                "[alpaca] Supabase rejected JWT: status=%s body=%s",
                res.status_code,
                (res.text or "")[:240],
            )
            return None, "invalid_or_expired_token"
        user_id = res.json().get("id")
        if not user_id:
            return None, "invalid_or_expired_token"
        return user_id, None
    except requests.RequestException as err:
        log.warning("[alpaca] auth user lookup failed: %s", err)
        return None, "auth_lookup_failed"


def get_user_credentials(user_id, auth_header=None):
    if not user_id or not SUPABASE_URL:
        return None

    headers = _supabase_rest_headers(auth_header)
    if not headers:
        log.warning("[alpaca] cannot fetch credentials — no Supabase API key configured")
        return None

    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"user_id": f"eq.{user_id}", "select": "api_key,secret_key,mode"},
            headers=headers,
            timeout=15,
        )
        if res.status_code != 200:
            log.warning(
                "[alpaca] credential fetch HTTP %s: %s",
                res.status_code,
                (res.text or "")[:240],
            )
            return None
        rows = res.json()
        if not rows or not rows[0].get("api_key"):
            return None
        row = rows[0]
        return {
            "api_key": row["api_key"],
            "secret_key": row["secret_key"],
            "mode": row.get("mode") or "paper",
        }
    except requests.RequestException as err:
        log.warning("[alpaca] credential fetch failed: %s", err)
        return None


def alpaca_base(creds):
    return ALPACA_LIVE_BASE if creds.get("mode") == "live" else ALPACA_PAPER_BASE


def alpaca_fetch(creds, path, method="GET", body=None):
    url = f"{alpaca_base(creds)}{path}"
    headers = {
        "APCA-API-KEY-ID": creds["api_key"],
        "APCA-API-SECRET-KEY": creds["secret_key"],
        "Content-Type": "application/json",
    }
    kwargs = {"headers": headers, "timeout": 30}
    if body is not None:
        kwargs["json"] = body
    return requests.request(method, url, **kwargs)


def fetch_latest_trade_price(symbol, creds):
    try:
        res = requests.get(
            f"{ALPACA_DATA_BASE}/stocks/{symbol.upper()}/trades/latest",
            headers={
                "APCA-API-KEY-ID": creds["api_key"],
                "APCA-API-SECRET-KEY": creds["secret_key"],
            },
            timeout=15,
        )
        if not res.ok:
            return None
        price = float(res.json().get("trade", {}).get("p", 0))
        return price if price > 0 else None
    except (requests.RequestException, ValueError, TypeError):
        return None


def repair_bracket_prices(side, entry_price, stop_loss, take_profit):
    try:
        entry = float(entry_price)
    except (TypeError, ValueError):
        entry = 0
    try:
        sl = float(stop_loss)
    except (TypeError, ValueError):
        sl = float("nan")
    try:
        tp = float(take_profit)
    except (TypeError, ValueError):
        tp = float("nan")

    repaired = []
    if not entry or entry <= 0:
        return {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "repaired": repaired,
            "base_price": None,
        }

    is_buy = str(side or "").lower() in ("buy", "long")
    pct_offset = max(BRACKET_MIN_OFFSET, round(entry * 0.01, 2))

    if is_buy:
        min_tp = round(entry + BRACKET_MIN_OFFSET, 2)
        max_sl = round(entry - BRACKET_MIN_OFFSET, 2)
        if tp != tp or tp < min_tp:
            tp = round(entry + pct_offset, 2)
            if tp < min_tp:
                tp = min_tp
            repaired.append(f"take_profit → {tp}")
        if sl != sl or sl > max_sl:
            sl = round(entry - pct_offset, 2)
            if sl > max_sl:
                sl = max_sl
            repaired.append(f"stop_loss → {sl}")
    else:
        max_tp = round(entry - BRACKET_MIN_OFFSET, 2)
        min_sl = round(entry + BRACKET_MIN_OFFSET, 2)
        if tp != tp or tp > max_tp:
            tp = round(entry - pct_offset, 2)
            if tp > max_tp:
                tp = max_tp
            repaired.append(f"take_profit → {tp}")
        if sl != sl or sl < min_sl:
            sl = round(entry + pct_offset, 2)
            if sl < min_sl:
                sl = min_sl
            repaired.append(f"stop_loss → {sl}")

    return {
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "repaired": repaired,
        "base_price": entry,
    }


def log_alpaca_order(user_id, row, auth_header=None):
    if not user_id or not SUPABASE_URL:
        return
    headers = _supabase_rest_headers(auth_header)
    if not headers:
        return
    headers["Prefer"] = "return=minimal"
    try:
        payload = {**row, "user_id": user_id}
        requests.post(
            f"{SUPABASE_URL}/rest/v1/alpaca_orders",
            headers=headers,
            json=payload,
            timeout=15,
        )
    except requests.RequestException as err:
        log.warning("[alpaca] alpaca_orders insert failed: %s", err)


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
