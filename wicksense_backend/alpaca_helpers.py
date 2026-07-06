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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def to_uuid_or_null(value):
    if not isinstance(value, str) or not value:
        return None
    return value if UUID_RE.match(value) else None


def get_user_id_from_request(auth_header):
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        log.warning("SUPABASE_URL or SUPABASE_ANON_KEY not configured")
        return None
    try:
        res = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": auth_header,
                "apikey": SUPABASE_ANON_KEY,
            },
            timeout=15,
        )
        if res.status_code != 200:
            return None
        return res.json().get("id")
    except requests.RequestException as err:
        log.warning("auth user lookup failed: %s", err)
        return None


def get_user_credentials(user_id):
    if not user_id or not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"user_id": f"eq.{user_id}", "select": "api_key,secret_key,mode"},
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            },
            timeout=15,
        )
        if res.status_code != 200:
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
        log.warning("credential fetch failed: %s", err)
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


def log_alpaca_order(user_id, row):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not user_id:
        return
    try:
        payload = {**row, "user_id": user_id}
        requests.post(
            f"{SUPABASE_URL}/rest/v1/alpaca_orders",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException as err:
        log.warning("alpaca_orders insert failed: %s", err)


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
