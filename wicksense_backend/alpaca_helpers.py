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


def _service_role_headers():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _fetch_credential_row_service(user_id):
    """Load full credential row via service_role (secrets never sent to browser)."""
    headers = _service_role_headers()
    if not headers or not user_id:
        return None, "service_role_not_configured"

    # Prefer dual columns; fall back if migration not applied
    select_dual = (
        "id,user_id,mode,updated_at,created_at,"
        "api_key,secret_key,api_key_last4,credentials_encrypted,"
        "paper_api_key,paper_secret_key,live_api_key,live_secret_key,"
        "paper_api_key_last4,live_api_key_last4,"
        "paper_account_id,live_account_id,paper_account_number,live_account_number,"
        "paper_account_status,live_account_status,"
        "paper_connection_ok,live_connection_ok,"
        "paper_last_tested_at,live_last_tested_at,live_confirmed_at"
    )
    select_legacy = (
        "id,user_id,mode,updated_at,created_at,"
        "api_key,secret_key,api_key_last4,credentials_encrypted"
    )

    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"user_id": f"eq.{user_id}", "select": select_dual},
            headers=headers,
            timeout=15,
        )
        if res.status_code == 400 and "paper_api_key" in (res.text or ""):
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
                params={"user_id": f"eq.{user_id}", "select": select_legacy},
                headers=headers,
                timeout=15,
            )
        if res.status_code != 200:
            log.warning("[alpaca] credential row fetch HTTP %s", res.status_code)
            return None, "credential_fetch_failed"
        rows = res.json()
        if not rows:
            return None, None
        return rows[0], None
    except requests.RequestException as err:
        log.warning("[alpaca] credential row fetch failed: %s", err)
        return None, "credential_fetch_failed"


def _maybe_reencrypt_and_persist(user_id, row, plain_key, plain_secret, storage_key_field, storage_secret_field):
    """If plaintext was loaded and encryption is configured, rewrite as enc:v1:."""
    from wicksense_backend.alpaca_crypto import (
        encryption_configured,
        ensure_encrypted_pair,
        is_encrypted,
        last4,
    )

    if not encryption_configured():
        return
    if is_encrypted(row.get(storage_key_field)) and is_encrypted(row.get(storage_secret_field)):
        return
    try:
        enc_key, enc_secret, changed = ensure_encrypted_pair(plain_key, plain_secret)
    except Exception as err:
        log.warning("[alpaca] re-encrypt skipped: %s", err)
        return
    if not changed:
        return

    headers = _service_role_headers()
    if not headers:
        return
    headers["Prefer"] = "return=minimal"
    patch = {
        storage_key_field: enc_key,
        storage_secret_field: enc_secret,
        "credentials_encrypted": True,
        "updated_at": now_iso(),
        "api_key_last4": last4(plain_key) if storage_key_field in ("api_key", "paper_api_key") else row.get("api_key_last4"),
    }
    if storage_key_field == "paper_api_key":
        patch["paper_api_key_last4"] = last4(plain_key)
        # keep legacy mirror encrypted too when dual schema
        patch["api_key"] = enc_key
        patch["secret_key"] = enc_secret
    if storage_key_field == "api_key":
        patch["api_key_last4"] = last4(plain_key)

    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"user_id": f"eq.{user_id}"},
            headers=headers,
            json=patch,
            timeout=15,
        )
        log.info("[alpaca] legacy plaintext credentials re-encrypted for user_id=%s…", str(user_id)[:8])
    except requests.RequestException as err:
        log.warning("[alpaca] re-encrypt persist failed: %s", err)


def get_user_credentials(user_id, auth_header=None, forced_mode=None):
    """
    Load + decrypt Paper OR Live keys (server-side only).
    Never returns paper keys when mode is live (and vice versa).
    """
    from wicksense_backend.alpaca_crypto import (
        decrypt_field,
        is_placeholder,
        encryption_configured,
    )

    row, err = _fetch_credential_row_service(user_id)
    if err == "service_role_not_configured":
        log.error("[alpaca] SUPABASE_SERVICE_ROLE_KEY required for credential access")
        return None
    if err or not row:
        return None

    mode = (forced_mode or row.get("mode") or "paper").lower()
    if mode not in ("paper", "live"):
        mode = "paper"

    if mode == "live":
        enc_key = row.get("live_api_key")
        enc_secret = row.get("live_secret_key")
        storage_key, storage_secret = "live_api_key", "live_secret_key"
        if is_placeholder(enc_key) or is_placeholder(enc_secret):
            log.warning("[alpaca] live mode requested but live credentials missing")
            return None
    else:
        enc_key = row.get("paper_api_key") or row.get("api_key")
        enc_secret = row.get("paper_secret_key") or row.get("secret_key")
        storage_key = "paper_api_key" if row.get("paper_api_key") else "api_key"
        storage_secret = "paper_secret_key" if row.get("paper_secret_key") else "secret_key"
        if is_placeholder(enc_key) or is_placeholder(enc_secret):
            return None

    try:
        plain_key = decrypt_field(enc_key)
        plain_secret = decrypt_field(enc_secret)
    except Exception as exc:
        log.warning("[alpaca] credential decrypt failed: %s", exc)
        return None

    if not plain_key or not plain_secret:
        return None

    if encryption_configured():
        _maybe_reencrypt_and_persist(
            user_id, row, plain_key, plain_secret, storage_key, storage_secret
        )

    return {
        "api_key": plain_key,
        "secret_key": plain_secret,
        "mode": mode,
        "connection_ok": bool(
            row.get("live_connection_ok") if mode == "live" else row.get("paper_connection_ok")
        ),
    }


def build_credential_status(user_id):
    """Masked status payload safe for the browser — never includes secrets."""
    from wicksense_backend.alpaca_crypto import (
        decrypt_field,
        is_placeholder,
        is_encrypted,
        mask_key_preview,
        encryption_configured,
    )

    row, err = _fetch_credential_row_service(user_id)
    if err == "service_role_not_configured":
        return {"error": "service_role_not_configured", "has_paper": False, "has_live": False}
    if not row:
        return {
            "has_credentials": False,
            "has_paper": False,
            "has_live": False,
            "mode": "paper",
            "paper": None,
            "live": None,
            "encryption_configured": encryption_configured(),
            "credentials_encrypted": False,
        }

    def _slot(preview_last4, connection_ok, account_id, account_number, account_status, last_tested, confirmed=None):
        from wicksense_backend.alpaca_crypto import mask_account_id, mask_account_number

        return {
            "api_key_preview": f"••••{preview_last4}" if preview_last4 else None,
            "account_id": mask_account_id(account_id),
            "account_number": mask_account_number(account_number),
            "account_status": account_status,
            "connection_ok": bool(connection_ok),
            "last_tested_at": last_tested,
            **({"confirmed_at": confirmed} if confirmed is not None else {}),
        }

    # Detect paper presence without exposing secrets: encrypted blob or last4 or decryptable
    paper_enc = row.get("paper_api_key") or row.get("api_key")
    paper_sec = row.get("paper_secret_key") or row.get("secret_key")
    has_paper = not is_placeholder(paper_enc) and not is_placeholder(paper_sec)
    live_enc = row.get("live_api_key")
    live_sec = row.get("live_secret_key")
    has_live = not is_placeholder(live_enc) and not is_placeholder(live_sec)

    paper_last4 = row.get("paper_api_key_last4") or row.get("api_key_last4")
    live_last4 = row.get("live_api_key_last4")

    # If last4 missing but we can decrypt server-side, derive preview without returning secret
    if has_paper and not paper_last4:
        try:
            pk = decrypt_field(paper_enc)
            paper_last4 = (pk[-4:] if pk and len(pk) >= 4 else None)
        except Exception:
            paper_last4 = None
    if has_live and not live_last4:
        try:
            lk = decrypt_field(live_enc)
            live_last4 = (lk[-4:] if lk and len(lk) >= 4 else None)
        except Exception:
            live_last4 = None

    paper = None
    if has_paper:
        paper = _slot(
            paper_last4,
            row.get("paper_connection_ok"),
            row.get("paper_account_id"),
            row.get("paper_account_number"),
            row.get("paper_account_status"),
            row.get("paper_last_tested_at"),
        )
        if not paper.get("api_key_preview") and paper_last4:
            paper["api_key_preview"] = f"••••{paper_last4}"
        elif not paper.get("api_key_preview"):
            paper["api_key_preview"] = "••••••••"

    live = None
    if has_live:
        live = _slot(
            live_last4,
            row.get("live_connection_ok"),
            row.get("live_account_id"),
            row.get("live_account_number"),
            row.get("live_account_status"),
            row.get("live_last_tested_at"),
            confirmed=row.get("live_confirmed_at"),
        )
        if not live.get("api_key_preview"):
            live["api_key_preview"] = f"••••{live_last4}" if live_last4 else "••••••••"

    active = row.get("mode") if row.get("mode") in ("paper", "live") else "paper"
    active_slot = live if active == "live" else paper

    return {
        "has_credentials": has_paper or has_live,
        "has_paper": has_paper,
        "has_live": has_live,
        "mode": active,
        "updated_at": row.get("updated_at"),
        "api_key_preview": (active_slot or {}).get("api_key_preview"),
        "paper": paper,
        "live": live,
        "encryption_configured": encryption_configured(),
        "credentials_encrypted": bool(row.get("credentials_encrypted"))
        or is_encrypted(paper_enc or "")
        or is_encrypted(live_enc or ""),
        "schema": "dual" if "paper_api_key" in row else "legacy",
    }


def save_user_credentials(user_id, credential_mode, api_key, secret_key):
    """Encrypt and upsert credentials via service_role. Never echoes secrets back."""
    from wicksense_backend.alpaca_crypto import (
        encryption_configured,
        encrypt_field,
        last4,
        is_placeholder,
    )

    if not encryption_configured():
        return {"success": False, "error": "encryption_not_configured"}
    if is_placeholder(api_key) or is_placeholder(secret_key):
        return {"success": False, "error": "api_key and secret_key are required"}

    headers = _service_role_headers()
    if not headers:
        return {"success": False, "error": "service_role_not_configured"}

    slot = "live" if credential_mode == "live" else "paper"
    try:
        enc_key = encrypt_field(api_key.strip())
        enc_secret = encrypt_field(secret_key.strip())
    except Exception as exc:
        log.warning("[alpaca] encrypt failed: %s", exc)
        return {"success": False, "error": "encryption_failed"}

    key_last4 = last4(api_key.strip())
    now = now_iso()

    existing, _ = _fetch_credential_row_service(user_id)
    dual = bool(existing and ("paper_api_key" in existing or existing.get("paper_api_key") is not None))
    # Detect dual schema via a probe when no row yet
    if existing is None:
        probe = requests.get(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"select": "paper_api_key", "limit": "1"},
            headers=headers,
            timeout=15,
        )
        dual = probe.status_code == 200

    row = {
        "user_id": user_id,
        "updated_at": now,
        "credentials_encrypted": True,
        "mode": (existing or {}).get("mode") if (existing or {}).get("mode") in ("paper", "live") else "paper",
    }

    if slot == "live":
        if not dual:
            return {
                "success": False,
                "error": "live_schema_migration_required",
                "message": "Live credentials require the Paper/Live column migration (on hold until security gate passes).",
            }
        row["live_api_key"] = enc_key
        row["live_secret_key"] = enc_secret
        row["live_api_key_last4"] = key_last4
        row["live_connection_ok"] = False
        row["live_last_tested_at"] = None
        row["live_account_id"] = None
        row["live_account_number"] = None
        row["live_account_status"] = None
        row["live_confirmed_at"] = None
        # Preserve paper
        if existing:
            row["paper_api_key"] = existing.get("paper_api_key") or existing.get("api_key")
            row["paper_secret_key"] = existing.get("paper_secret_key") or existing.get("secret_key")
            row["api_key"] = row["paper_api_key"] or "paper_not_configured"
            row["secret_key"] = row["paper_secret_key"] or "paper_not_configured"
            row["api_key_last4"] = existing.get("api_key_last4") or existing.get("paper_api_key_last4")
            row["paper_api_key_last4"] = existing.get("paper_api_key_last4") or existing.get("api_key_last4")
        else:
            row["api_key"] = "paper_not_configured"
            row["secret_key"] = "paper_not_configured"
    else:
        if dual:
            row["paper_api_key"] = enc_key
            row["paper_secret_key"] = enc_secret
            row["paper_api_key_last4"] = key_last4
            row["paper_connection_ok"] = False
            row["paper_last_tested_at"] = None
            row["paper_account_id"] = None
            row["paper_account_number"] = None
            row["paper_account_status"] = None
            if existing:
                row["live_api_key"] = existing.get("live_api_key")
                row["live_secret_key"] = existing.get("live_secret_key")
                row["live_api_key_last4"] = existing.get("live_api_key_last4")
        row["api_key"] = enc_key
        row["secret_key"] = enc_secret
        row["api_key_last4"] = key_last4

    headers_upsert = {**headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"on_conflict": "user_id"},
            headers=headers_upsert,
            json=row,
            timeout=15,
        )
        if res.status_code not in (200, 201, 204):
            # fallback upsert via PATCH if row exists
            if existing:
                res = requests.patch(
                    f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
                    params={"user_id": f"eq.{user_id}"},
                    headers={**headers, "Prefer": "return=minimal"},
                    json=row,
                    timeout=15,
                )
            if res.status_code not in (200, 201, 204):
                log.warning("[alpaca] save credentials HTTP %s: %s", res.status_code, (res.text or "")[:200])
                return {"success": False, "error": "save_failed"}
    except requests.RequestException as err:
        log.warning("[alpaca] save credentials failed: %s", err)
        return {"success": False, "error": "save_failed"}

    status = build_credential_status(user_id)
    return {"success": True, "credentialMode": slot, "credentials": status}


def delete_user_credentials(user_id, credential_mode="paper"):
    """
    Remove encrypted secrets for a mode via service_role.
    No in-process Alpaca client cache is retained across requests; each broker call
    decrypts from DB. Deletion nulls ciphertext so subsequent decrypts fail closed.
    """
    headers = _service_role_headers()
    if not headers:
        return {"success": False, "error": "service_role_not_configured"}

    existing, _ = _fetch_credential_row_service(user_id)
    if not existing:
        return {"success": True, "cache_cleared": True}

    slot = "live" if credential_mode == "live" else "paper"
    dual = "paper_api_key" in existing or existing.get("live_api_key") is not None

    from wicksense_backend.alpaca_crypto import is_placeholder

    has_paper = not is_placeholder(existing.get("paper_api_key") or existing.get("api_key"))
    has_live = not is_placeholder(existing.get("live_api_key"))

    headers_mut = {**headers, "Prefer": "return=minimal"}

    if not dual or (slot == "paper" and not has_live) or (slot == "live" and not has_paper):
        res = requests.delete(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"user_id": f"eq.{user_id}"},
            headers=headers_mut,
            timeout=15,
        )
        if res.status_code not in (200, 204):
            return {"success": False, "error": "delete_failed"}
        return {"success": True, "deletedRow": True, "cache_cleared": True}

    patch = {"updated_at": now_iso()}
    if slot == "live":
        patch.update({
            "live_api_key": None,
            "live_secret_key": None,
            "live_api_key_last4": None,
            "live_connection_ok": False,
            "live_confirmed_at": None,
            "live_account_id": None,
            "live_account_number": None,
            "live_account_status": None,
            "live_last_tested_at": None,
            "mode": "paper",
        })
    else:
        patch.update({
            "paper_api_key": None,
            "paper_secret_key": None,
            "paper_api_key_last4": None,
            "api_key": "paper_not_configured",
            "secret_key": "paper_not_configured",
            "api_key_last4": None,
            "credentials_encrypted": bool(existing.get("live_api_key")),
            "paper_connection_ok": False,
            "paper_account_id": None,
            "paper_account_number": None,
            "paper_account_status": None,
            "paper_last_tested_at": None,
        })

    res = requests.patch(
        f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
        params={"user_id": f"eq.{user_id}"},
        headers=headers_mut,
        json=patch,
        timeout=15,
    )
    if res.status_code not in (200, 204):
        return {"success": False, "error": "delete_failed"}
    return {"success": True, "cache_cleared": True}


# Real live entry-order submission stays off until separately approved.
REAL_LIVE_ORDER_SUBMISSION_ENABLED = False


def alpaca_base(creds):
    return ALPACA_LIVE_BASE if creds.get("mode") == "live" else ALPACA_PAPER_BASE


def build_mock_live_order(body=None):
    body = body or {}
    oid = f"MOCK-LIVE-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    return {
        "success": True,
        "mocked": True,
        "real_live_submission_blocked": True,
        "message": (
            "Live order submission is disabled until separately approved. "
            "Returning mocked response only."
        ),
        "order": {
            "id": oid,
            "alpaca_order_id": oid,
            "client_order_id": body.get("client_order_id") or oid,
            "symbol": body.get("symbol") or "SPY",
            "qty": str(body.get("qty") or "1"),
            "side": body.get("side") or "buy",
            "type": body.get("type") or "market",
            "status": "accepted",
            "created_at": now_iso(),
            "mocked": True,
        },
    }


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
