"""Alpaca + Supabase helpers for wicksense-backend /alpaca/* routes."""

import os
import re
import json
import logging
from datetime import datetime, timezone

import requests

from wicksense_backend.alpaca_creds_crypto import (
    AlpacaCredsCryptoError,
    decrypt_credential_envelope,
    encrypt_credential_envelope,
    is_encrypted_credential_row,
    is_legacy_plaintext_credential_row,
)

log = logging.getLogger("wicksense.alpaca")

ALPACA_PAPER_BASE = "https://paper-api.alpaca.markets/v2"
ALPACA_LIVE_BASE = "https://api.alpaca.markets/v2"
ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
BRACKET_MIN_OFFSET = 0.01
CREDENTIAL_SELECT = (
    "id,user_id,mode,updated_at,created_at,"
    "api_key,secret_key,"
    "credential_ciphertext,credential_nonce,enc_version,key_id"
)


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


def _supabase_service_headers():
    """Service-role headers for credential rows (client grants revoked for secrets)."""
    if not SUPABASE_SERVICE_ROLE_KEY:
        return None
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def normalize_alpaca_mode(mode, api_key=None):
    if mode in ("paper", "live"):
        return mode
    prefix = str(api_key or "").strip()[:2].upper()
    if prefix == "AK":
        return "live"
    return "paper"


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


def _fetch_credential_rows(user_id, mode=None):
    headers = _supabase_service_headers()
    if not headers or not SUPABASE_URL:
        log.warning("[alpaca] cannot fetch credentials — service role not configured")
        return None

    params = {
        "user_id": f"eq.{user_id}",
        "select": CREDENTIAL_SELECT,
        "order": "updated_at.desc",
    }
    if mode in ("paper", "live"):
        params["mode"] = f"eq.{mode}"
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params=params,
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as err:
        log.warning("[alpaca] credential fetch failed: %s", err)
        return None
    if res.status_code != 200:
        log.warning(
            "[alpaca] credential fetch HTTP %s: %s",
            res.status_code,
            (res.text or "")[:240],
        )
        return None
    rows = res.json()
    return rows if isinstance(rows, list) else []


def _resolve_credentials_from_row(row, user_id):
    """Decrypt encrypted row or temporarily accept legacy plaintext. Fail closed on crypto errors."""
    if not row:
        return None
    mode = normalize_alpaca_mode(row.get("mode"))
    if is_encrypted_credential_row(row):
        try:
            secrets = decrypt_credential_envelope(row, user_id, mode)
        except AlpacaCredsCryptoError as err:
            log.warning(
                "[alpaca] credential decrypt failed closed user_prefix=%s mode=%s enc_version=%s key_id=%s code=%s",
                str(user_id)[:8],
                mode,
                row.get("enc_version"),
                row.get("key_id"),
                err.code,
            )
            return None
        return {
            "api_key": secrets["api_key"],
            "secret_key": secrets["secret_key"],
            "mode": mode,
            "source": "encrypted",
            "enc_version": row.get("enc_version"),
            "key_id": row.get("key_id"),
        }
    if is_legacy_plaintext_credential_row(row):
        log.info(
            "[alpaca] using temporary legacy plaintext credentials user_prefix=%s mode=%s",
            str(user_id)[:8],
            mode,
        )
        return {
            "api_key": row["api_key"],
            "secret_key": row["secret_key"],
            "mode": mode,
            "source": "legacy_plaintext",
        }
    return None


def get_user_credentials(user_id, auth_header=None, mode=None):
    """
    Load Alpaca credentials for JWT-authoritative user_id.
    auth_header is unused for DB fetch (service-role); retained for call-site compat.
    Decrypts in memory only. Crypto failures fail closed (no plaintext fallback).
    """
    del auth_header  # ownership already established by caller JWT validation
    if not user_id or not SUPABASE_URL:
        return None

    preferred = mode if mode in ("paper", "live") else None
    rows = _fetch_credential_rows(user_id, preferred)
    if rows is None:
        return None
    if not rows and preferred:
        # Fall back to any mode only when caller did not force a mode miss.
        rows = _fetch_credential_rows(user_id, None) or []

    if not rows:
        return None

    row = None
    if preferred:
        row = next((r for r in rows if normalize_alpaca_mode(r.get("mode")) == preferred), None)
    if row is None:
        row = next((r for r in rows if normalize_alpaca_mode(r.get("mode")) != "live"), None) or rows[0]
    return _resolve_credentials_from_row(row, user_id)


def save_user_credentials(user_id, api_key, secret_key, mode=None):
    """Encrypt server-side and upsert; plaintext columns NULL. Returns safe metadata."""
    headers = _supabase_service_headers()
    if not headers or not SUPABASE_URL:
        return None, "service_role_not_configured"
    if not user_id:
        return None, "unauthorized"
    api_key = str(api_key or "").strip()
    secret_key = str(secret_key or "").strip()
    if not api_key or not secret_key:
        return None, "api_key_and_secret_key_required"
    resolved_mode = normalize_alpaca_mode(mode, api_key)
    try:
        enc = encrypt_credential_envelope(api_key, secret_key, user_id, resolved_mode)
    except AlpacaCredsCryptoError as err:
        log.warning(
            "[alpaca] credential encrypt failed user_prefix=%s mode=%s code=%s",
            str(user_id)[:8],
            resolved_mode,
            err.code,
        )
        return None, "encryption_failed"

    now = now_iso()
    payload = {
        "user_id": user_id,
        "mode": resolved_mode,
        "api_key": None,
        "secret_key": None,
        "credential_ciphertext": enc["credential_ciphertext"],
        "credential_nonce": enc["credential_nonce"],
        "enc_version": enc["enc_version"],
        "key_id": enc["key_id"],
        "updated_at": now,
    }
    headers = {**headers, "Prefer": "resolution=merge-duplicates,return=representation"}
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"on_conflict": "user_id,mode"},
            headers=headers,
            json=payload,
            timeout=15,
        )
    except requests.RequestException as err:
        log.warning("[alpaca] credential upsert failed: %s", err)
        return None, "upsert_failed"
    if res.status_code not in (200, 201):
        log.warning(
            "[alpaca] credential upsert HTTP %s: %s",
            res.status_code,
            (res.text or "")[:240],
        )
        return None, "upsert_failed"
    rows = res.json() if res.content else []
    row = rows[0] if isinstance(rows, list) and rows else {}
    return {
        "success": True,
        "configured": True,
        "mode": resolved_mode,
        "updated_at": row.get("updated_at") or now,
        "id": row.get("id"),
    }, None


def load_user_credentials_metadata(user_id):
    """Safe metadata only — never returns secrets, ciphertext, nonce, or key_id."""
    rows = _fetch_credential_rows(user_id, None)
    if rows is None:
        return None, "fetch_failed"

    def meta_for(mode):
        row = next((r for r in rows if normalize_alpaca_mode(r.get("mode")) == mode), None)
        configured = False
        if row:
            configured = is_encrypted_credential_row(row) or is_legacy_plaintext_credential_row(row)
        return {
            "configured": configured,
            "has_credentials": configured,
            "mode": mode,
            "updated_at": (row or {}).get("updated_at"),
            "api_key_preview": None,
        }

    paper = meta_for("paper")
    live = meta_for("live")
    preferred = paper if paper["configured"] else live
    return {
        "credentials": {
            "configured": paper["configured"] or live["configured"],
            "has_credentials": paper["configured"] or live["configured"],
            "mode": preferred["mode"] if preferred["configured"] else "paper",
            "updated_at": preferred["updated_at"] if preferred["configured"] else None,
            "api_key_preview": None,
            "paper": paper,
            "live": live,
        }
    }, None


def delete_user_credentials(user_id, mode=None):
    headers = _supabase_service_headers()
    if not headers or not SUPABASE_URL:
        return None, "service_role_not_configured"
    if not user_id:
        return None, "unauthorized"
    params = {"user_id": f"eq.{user_id}"}
    if mode in ("paper", "live"):
        params["mode"] = f"eq.{mode}"
    try:
        res = requests.delete(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params=params,
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as err:
        log.warning("[alpaca] credential delete failed: %s", err)
        return None, "delete_failed"
    if res.status_code not in (200, 204):
        log.warning(
            "[alpaca] credential delete HTTP %s: %s",
            res.status_code,
            (res.text or "")[:240],
        )
        return None, "delete_failed"
    return {"success": True, "message": "Credentials removed successfully"}, None


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
