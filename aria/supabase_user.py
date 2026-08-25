"""JWT-scoped Supabase reads for ARIA Truth Gateway (RLS applies via user token)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from wicksense_backend.alpaca_helpers import SUPABASE_URL, supabase_api_key

log = logging.getLogger("wicksense.aria.supabase_user")


def _headers(auth_header: str) -> dict[str, str] | None:
    api_key = supabase_api_key()
    if not SUPABASE_URL or not api_key or not auth_header:
        return None
    return {
        "apikey": api_key,
        "Authorization": auth_header,
        "Content-Type": "application/json",
    }


def _get(path: str, auth_header: str, params: str = "") -> Any:
    headers = _headers(auth_header)
    if not headers:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{path}{params}"
    try:
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code != 200:
            log.warning("[aria.supabase] GET %s -> %s %s", path, res.status_code, res.text[:200])
            return None
        return res.json()
    except requests.RequestException as exc:
        log.warning("[aria.supabase] GET %s failed: %s", path, exc)
        return None


def fetch_user_preferences(auth_header: str, user_id: str) -> dict | None:
    rows = _get(
        "user_preferences",
        auth_header,
        f"?id=eq.{user_id}&select=*&limit=1",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


def fetch_open_trades(auth_header: str, user_id: str, limit: int = 50) -> list:
    rows = _get(
        "paper_trades",
        auth_header,
        f"?user_id=eq.{user_id}&status=in.(WAIT,ACTIVE,OPEN,open,Open)"
        f"&select=id,strategy_id,market,direction,status,entry_price,stop_loss,"
        f"take_profit,opened_at,created_at,signal_id,timeframe,pnl"
        f"&order=created_at.desc&limit={int(limit)}",
    )
    return rows if isinstance(rows, list) else []


def fetch_closed_trades(auth_header: str, user_id: str, limit: int = 25) -> list:
    rows = _get(
        "closed_trades",
        auth_header,
        f"?user_id=eq.{user_id}&select=*&order=closed_at.desc.nullslast&limit={int(limit)}",
    )
    if isinstance(rows, list) and rows:
        return rows
    # Fallback: closed status on paper_trades
    rows = _get(
        "paper_trades",
        auth_header,
        f"?user_id=eq.{user_id}&status=in.(CLOSED,closed,Closed)"
        f"&select=id,strategy_id,market,direction,status,entry_price,exit_price,"
        f"pnl,pnl_pts,closed_at,created_at&order=closed_at.desc.nullslast&limit={int(limit)}",
    )
    return rows if isinstance(rows, list) else []


def fetch_risk_account_settings(auth_header: str, user_id: str) -> dict | None:
    rows = _get(
        "risk_account_settings",
        auth_header,
        f"?user_id=eq.{user_id}&select=*&limit=1",
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


def fetch_strategy_lifecycle(auth_header: str) -> list:
    rows = _get(
        "strategy_lifecycle",
        auth_header,
        "?select=strategy_id,current_stage,auto_trading_enabled,display_name,updated_at",
    )
    return rows if isinstance(rows, list) else []


def fetch_strategy_market_matrix(auth_header: str, user_id: str) -> list:
    rows = _get(
        "strategy_market_matrix",
        auth_header,
        f"?user_id=eq.{user_id}&select=strategy_id,market_key,enabled,updated_at",
    )
    return rows if isinstance(rows, list) else []


def fetch_aria_conversations(auth_header: str, user_id: str, limit: int = 20) -> list:
    rows = _get(
        "aria_conversations",
        auth_header,
        f"?user_id=eq.{user_id}&select=id,session_id,created_at&order=created_at.desc&limit={int(limit)}",
    )
    return rows if isinstance(rows, list) else []


def fetch_aria_memory(auth_header: str, user_id: str, limit: int = 20) -> list:
    rows = _get(
        "aria_memory",
        auth_header,
        f"?user_id=eq.{user_id}&select=id,created_at&order=created_at.desc&limit={int(limit)}",
    )
    return rows if isinstance(rows, list) else []
