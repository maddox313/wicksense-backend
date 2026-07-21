"""
Alpaca proxy blueprint — mirrors supabase/functions/alpaca-paper-proxy actions.

Routes:
  POST /alpaca/<action>   — snake_case or kebab-case action name
  OPTIONS /alpaca/<action> — CORS preflight (204)
"""

import json
import logging

from flask import Blueprint, jsonify, request, g

from wicksense_backend.alpaca_helpers import (
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    REAL_LIVE_ORDER_SUBMISSION_ENABLED,
    alpaca_fetch,
    build_credential_status,
    build_mock_live_order,
    delete_user_credentials,
    fetch_latest_trade_price,
    get_user_credentials,
    get_user_id_from_request,
    log_alpaca_order,
    now_iso,
    repair_bracket_prices,
    save_user_credentials,
    to_uuid_or_null,
)

log = logging.getLogger("wicksense.alpaca")

alpaca_bp = Blueprint("alpaca", __name__, url_prefix="/alpaca")

KNOWN_ACTIONS = {
    "test_connection",
    "send_test_order",
    "submit_entry_order",
    "check_asset",
    "get_order_status",
    "get_positions",
    "get_live_orders",
    "get_account_activity",
    "close_position",
    "emergency_kill_switch",
    "get_alpaca_orders",
    "reset_paper_account",
    "save_credentials",
    "load_credentials",
    "delete_credentials",
    "get_account",
    "cancel_order",
    "reconcile_fills",
}


def _normalize_action(raw):
    if not raw:
        return ""
    return raw.strip().lower().replace("-", "_")


def _require_auth():
    auth = request.headers.get("Authorization", "")
    user_id, reason = get_user_id_from_request(auth)
    if not user_id:
        return None, (jsonify({"error": "Unauthorized", "reason": reason or "unauthorized"}), 401)
    g.alpaca_auth_header = auth
    return user_id, None


def _require_creds(user_id, forced_mode=None):
    auth = getattr(g, "alpaca_auth_header", None)
    body = request.get_json(silent=True) or {}
    mode = forced_mode or body.get("credential_mode")
    if mode not in ("paper", "live"):
        mode = None
    creds = get_user_credentials(user_id, auth, forced_mode=mode)
    if not creds:
        slot = mode or "active"
        return None, (
            jsonify({
                "error": f"No Alpaca {slot} credentials found. Save and test that credential pair first.",
            }),
            400,
        )
    return creds, None


def _record_connection_result(user_id, mode, account):
    """Persist connection metadata via service_role (no secrets; account ids/numbers masked)."""
    import requests
    from wicksense_backend.alpaca_crypto import mask_account_id, mask_account_number

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return
    is_live = mode == "live"
    ok = bool(account and account.get("id"))
    now = now_iso()
    patch = {"updated_at": now}
    masked_id = mask_account_id((account or {}).get("id"))
    masked_num = mask_account_number((account or {}).get("account_number"))
    if is_live:
        patch.update({
            "live_connection_ok": ok,
            "live_last_tested_at": now,
            "live_account_id": masked_id,
            "live_account_number": masked_num,
            "live_account_status": (account or {}).get("status"),
        })
    else:
        patch.update({
            "paper_connection_ok": ok,
            "paper_last_tested_at": now,
            "paper_account_id": masked_id,
            "paper_account_number": masked_num,
            "paper_account_status": (account or {}).get("status"),
        })
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/alpaca_credentials",
            params={"user_id": f"eq.{user_id}"},
            headers=headers,
            json=patch,
            timeout=15,
        )
    except Exception as err:
        log.warning("record connection result failed: %s", err)


def _sanitize_public_payload(obj):
    """Defense-in-depth: strip secret keys from any dict returned to the browser."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_sanitize_public_payload(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    kill = {
        "api_key",
        "secret_key",
        "paper_api_key",
        "paper_secret_key",
        "live_api_key",
        "live_secret_key",
        "APCA-API-KEY-ID",
        "APCA-API-SECRET-KEY",
        "_api_key",
        "_secret_key",
    }
    out = {}
    for k, v in obj.items():
        if k in kill or (isinstance(k, str) and (
            k.lower() in ("apikey", "apisecret")
            or k.endswith("_secret_key")
            or (k.endswith("_api_key") and "last4" not in k and "preview" not in k)
        )):
            continue
        out[k] = _sanitize_public_payload(v) if isinstance(v, (dict, list)) else v
    return out


def _public_json(payload, status=200):
    return jsonify(_sanitize_public_payload(payload)), status


def _handle_save_credentials(user_id, body):
    slot = body.get("credentialMode") or body.get("credential_mode") or body.get("mode") or "paper"
    if slot not in ("paper", "live"):
        slot = "paper"
    api_key = body.get("api_key")
    secret_key = body.get("secret_key")
    # Accept secrets only on this write endpoint — never log them
    result = save_user_credentials(user_id, slot, api_key, secret_key)
    status = result.get("success")
    code = 200 if status else 400
    safe = {k: v for k, v in result.items() if k not in ("api_key", "secret_key")}
    return _public_json(safe, code)


def _handle_load_credentials(user_id):
    status = build_credential_status(user_id)
    if status.get("error") == "service_role_not_configured":
        return _public_json({"error": "service_role_not_configured"}, 503)
    return _public_json({"credentials": status, "success": True})


def _handle_delete_credentials(user_id, body):
    slot = body.get("credentialMode") or body.get("credential_mode") or body.get("mode") or "paper"
    result = delete_user_credentials(user_id, slot)
    code = 200 if result.get("success") else 400
    return _public_json(result, code)


def _supabase_patch(table, match_col, match_val, payload, user_id=None):
    from wicksense_backend.alpaca_helpers import _supabase_rest_headers

    headers = _supabase_rest_headers(getattr(g, "alpaca_auth_header", None))
    if not headers or not SUPABASE_URL:
        return
    import requests

    params = {match_col: f"eq.{match_val}"}
    if user_id:
        params["user_id"] = f"eq.{user_id}"
    headers["Prefer"] = "return=minimal"
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/{table}",
            params=params,
            headers=headers,
            json=payload,
            timeout=15,
        )
    except Exception as err:
        log.warning("supabase patch %s failed: %s", table, err)


def _log_order(user_id, row):
    log_alpaca_order(user_id, row, getattr(g, "alpaca_auth_header", None))


def _supabase_get_alpaca_orders(user_id, limit=50):
    from wicksense_backend.alpaca_helpers import _supabase_rest_headers
    import requests

    headers = _supabase_rest_headers(getattr(g, "alpaca_auth_header", None))
    if not headers or not SUPABASE_URL:
        return []

    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/alpaca_orders",
        params={
            "user_id": f"eq.{user_id}",
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        },
        headers=headers,
        timeout=15,
    )
    if res.status_code != 200:
        return []
    return res.json()


def _handle_test_connection(user_id):
    body = request.get_json(silent=True) or {}
    forced = body.get("credential_mode") or body.get("mode")
    if forced not in ("paper", "live"):
        forced = None
    creds, err = _require_creds(user_id, forced_mode=forced)
    if err:
        return err
    res = alpaca_fetch(creds, "/account")
    if not res.ok:
        _record_connection_result(user_id, creds.get("mode"), None)
        return jsonify({
            "success": False,
            "mode": creds.get("mode"),
            "error": "Alpaca API rejected the credentials",
            "detail": res.text,
            "status": res.status_code,
        }), 400
    account = res.json()
    _record_connection_result(user_id, creds.get("mode"), account)
    return jsonify(_masked_account_payload(creds.get("mode"), account, success=True))


def _masked_account_payload(mode, account, success=True):
    """Browser-safe account view — never returns full account id/number."""
    from wicksense_backend.alpaca_crypto import mask_account_id, mask_account_number

    account = account or {}
    return {
        "success": success,
        "mode": mode,
        "endpoint": "live" if mode == "live" else "paper",
        "account": {
            "id": mask_account_id(account.get("id")),
            "account_number": mask_account_number(account.get("account_number")),
            "status": account.get("status"),
            "currency": account.get("currency"),
            "buying_power": account.get("buying_power"),
            "cash": account.get("cash"),
            "portfolio_value": account.get("portfolio_value"),
            "equity": account.get("equity"),
            "last_equity": account.get("last_equity"),
            "trading_blocked": account.get("trading_blocked"),
            "account_blocked": account.get("account_blocked"),
            "shorting_enabled": account.get("shorting_enabled"),
            "pattern_day_trader": account.get("pattern_day_trader"),
            "multiplier": account.get("multiplier"),
            "daytrade_count": account.get("daytrade_count"),
            "long_market_value": account.get("long_market_value"),
            "short_market_value": account.get("short_market_value"),
        },
    }


def _handle_get_account(user_id):
    """Same Alpaca /account fetch as test_connection, without rewriting connection stamps unless forced."""
    body = request.get_json(silent=True) or {}
    forced = body.get("credential_mode") or body.get("mode")
    if forced not in ("paper", "live"):
        forced = None
    creds, err = _require_creds(user_id, forced_mode=forced)
    if err:
        return err
    res = alpaca_fetch(creds, "/account")
    if not res.ok:
        return jsonify({
            "success": False,
            "mode": creds.get("mode"),
            "error": "Alpaca API rejected the credentials",
            "status": res.status_code,
        }), 400
    return jsonify(_masked_account_payload(creds.get("mode"), res.json(), success=True))


def _handle_cancel_order(user_id, body):
    creds, err = _require_creds(user_id)
    if err:
        return err
    alpaca_order_id = body.get("alpaca_order_id") or body.get("order_id")
    if not alpaca_order_id:
        return jsonify({"error": "alpaca_order_id is required"}), 400
    res = alpaca_fetch(creds, f"/orders/{alpaca_order_id}", "DELETE")
    if not res.ok:
        detail = {}
        try:
            detail = res.json()
        except Exception:
            detail = {"raw": (res.text or "")[:200]}
        return jsonify({
            "success": False,
            "error": "Cancel order failed",
            "status": res.status_code,
            "detail": detail,
        }), 400
    data = res.json() if res.content else {"id": alpaca_order_id, "status": "canceled"}
    return jsonify({
        "success": True,
        "mode": creds.get("mode"),
        "order": {
            "alpaca_order_id": data.get("id") or alpaca_order_id,
            "order_status": data.get("status") or "canceled",
            "symbol": data.get("symbol"),
            "side": data.get("side"),
            "qty": data.get("qty"),
        },
    })


def _handle_reconcile_fills(user_id, body):
    """Reconcile fills for one or more Alpaca orders into alpaca_orders / paper_trades."""
    ids = body.get("alpaca_order_ids") or body.get("order_ids") or []
    single = body.get("alpaca_order_id")
    if single:
        ids = list(ids) + [single]
    if not ids:
        return jsonify({"error": "alpaca_order_id or alpaca_order_ids required"}), 400
    results = []
    for oid in ids:
        sub = _handle_get_order_status(user_id, {
            "alpaca_order_id": oid,
            "paper_trade_id": body.get("paper_trade_id"),
        })
        # Flask handlers return (response, status) or Response
        if isinstance(sub, tuple):
            resp, code = sub
            payload = resp.get_json(silent=True) or {}
            results.append({"alpaca_order_id": oid, "ok": code < 400, **payload})
        else:
            payload = sub.get_json(silent=True) or {}
            results.append({"alpaca_order_id": oid, "ok": True, **payload})
    return jsonify({"success": all(r.get("ok") for r in results), "results": results})


def _handle_send_test_order(user_id):
    creds, err = _require_creds(user_id)
    if err:
        return err
    if creds.get("mode") == "live":
        return jsonify({
            "success": False,
            "blocked": True,
            "error": "Test orders are blocked in Live mode. No test-order may submit a live order.",
        }), 400
    payload = {
        "symbol": "SPY",
        "qty": "1",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "client_order_id": f"wicksense_test_{int(__import__('time').time() * 1000)}",
    }
    res = alpaca_fetch(creds, "/orders", "POST", payload)
    data = res.json() if res.content else {}
    if not res.ok:
        return jsonify({"error": "Test order failed", "detail": data, "status": res.status_code}), 400
    return jsonify({"success": True, "mode": "paper", "order": data})


def _handle_submit_entry_order(user_id, body):
    creds, err = _require_creds(user_id)
    if err:
        return err

    if creds.get("mode") == "live" and not REAL_LIVE_ORDER_SUBMISSION_ENABLED:
        return jsonify(build_mock_live_order(body))

    symbol = body.get("symbol")
    side = body.get("side")
    qty = body.get("qty")
    if not symbol or not side or not qty:
        return jsonify({"error": "symbol, side, and qty are required"}), 400

    paper_trade_id = body.get("paper_trade_id")
    external_trade_ref = body.get("external_trade_ref")
    entry_price = body.get("entry_price")
    stop_loss = body.get("stop_loss")
    take_profit = body.get("take_profit")
    market = body.get("market")
    strategy_id = body.get("strategy_id")

    paper_trade_uuid = to_uuid_or_null(paper_trade_id)
    external_ref = external_trade_ref or (paper_trade_id if not paper_trade_uuid and isinstance(paper_trade_id, str) else None)

    latest_price = fetch_latest_trade_price(symbol, creds)
    base_price = latest_price if latest_price is not None else entry_price
    bracket = repair_bracket_prices(side, base_price, stop_loss, take_profit)
    repaired_sl = bracket["stop_loss"]
    repaired_tp = bracket["take_profit"]
    resolved_entry = bracket["entry_price"] or float(entry_price or 0)

    details_extra = {
        "external_trade_ref": external_ref,
        "bracket_base_price": bracket["base_price"],
        "bracket_repairs": bracket["repaired"],
        "latest_trade_price": latest_price,
        "credential_mode": creds.get("mode"),
    }

    if str(side).lower() == "sell":
        asset_res = alpaca_fetch(creds, f"/assets/{symbol.upper()}")
        if asset_res.ok:
            asset = asset_res.json()
            if not (asset.get("shortable") and asset.get("easy_to_borrow")):
                skip_reason = f"Alpaca order skipped: short selling not available for {symbol.upper()}"
                _log_order(user_id, {
                    "paper_trade_id": paper_trade_uuid,
                    "symbol": symbol.upper(),
                    "side": "sell",
                    "qty": float(qty),
                    "order_status": "skipped_short_not_allowed",
                    "error_message": skip_reason,
                    "details": json.dumps(details_extra),
                })
                return jsonify({
                    "skipped": True,
                    "skip_reason": skip_reason,
                    "paper_trade_id": paper_trade_uuid,
                    "external_trade_ref": external_ref,
                })
        else:
            return jsonify({
                "skipped": True,
                "skip_reason": f"Alpaca order skipped: could not verify shortability for {symbol.upper()}",
                "paper_trade_id": paper_trade_uuid,
            })

    client_order_id = f"ws_{paper_trade_uuid or external_ref or 'x'}_{int(__import__('time').time() * 1000)}"[:48]
    order_payload = {
        "symbol": symbol.upper(),
        "qty": str(max(1, round(float(qty)))),
        "side": str(side).lower(),
        "type": "market",
        "time_in_force": "day",
        "client_order_id": client_order_id,
    }
    has_bracket = repaired_sl is not None and repaired_tp is not None
    if has_bracket:
        order_payload["order_class"] = "bracket"
        order_payload["stop_loss"] = {"stop_price": f"{float(repaired_sl):.2f}"}
        order_payload["take_profit"] = {"limit_price": f"{float(repaired_tp):.2f}"}

    order_res = alpaca_fetch(creds, "/orders", "POST", order_payload)
    order_data = order_res.json() if order_res.content else {}

    if not order_res.ok:
        _log_order(user_id, {
            "paper_trade_id": paper_trade_uuid,
            "symbol": symbol.upper(),
            "side": str(side).lower(),
            "qty": float(qty),
            "order_type": "market",
            "order_class": "bracket" if has_bracket else "simple",
            "order_status": "failed",
            "entry_price": resolved_entry or 0,
            "stop_loss_price": repaired_sl,
            "take_profit_price": repaired_tp,
            "market": market,
            "strategy_id": strategy_id,
            "error_message": order_data.get("message") or json.dumps(order_data),
            "details": json.dumps(details_extra),
        })
        return jsonify({
            "success": False,
            "error": "Order submission failed",
            "detail": order_data,
            "alpaca_error_body": order_data,
            "http_status": order_res.status_code,
            "order_payload": order_payload,
            "bracket_repairs": bracket["repaired"],
            "base_price": bracket["base_price"],
        })

    _log_order(user_id, {
        "paper_trade_id": paper_trade_uuid,
        "alpaca_order_id": order_data.get("id"),
        "client_order_id": client_order_id,
        "symbol": symbol.upper(),
        "side": str(side).lower(),
        "qty": float(qty),
        "order_type": "market",
        "order_class": "bracket" if has_bracket else "simple",
        "order_status": order_data.get("status") or "pending_new",
        "entry_price": resolved_entry or 0,
        "stop_loss_price": repaired_sl,
        "take_profit_price": repaired_tp,
        "market": market,
        "strategy_id": strategy_id,
        "alpaca_response": json.dumps(order_data),
        "details": json.dumps(details_extra),
    })

    if paper_trade_uuid:
        exec_mode = "alpaca_live" if creds.get("mode") == "live" else "alpaca_paper"
        _supabase_patch(
            "paper_trades",
            "id",
            paper_trade_uuid,
            {
                "alpaca_order_id": order_data.get("id"),
                "alpaca_order_status": order_data.get("status") or "pending_new",
                "alpaca_submitted_at": now_iso(),
                "stop_loss": repaired_sl,
                "take_profit": repaired_tp,
                "execution_mode": exec_mode,
                "broker_source": "alpaca",
                "alpaca_executed": True,
            },
        )

    return jsonify({
        "success": True,
        "mode": creds.get("mode"),
        "order": {
            "alpaca_order_id": order_data.get("id"),
            "symbol": order_data.get("symbol"),
            "side": order_data.get("side"),
            "qty": order_data.get("qty"),
            "order_status": order_data.get("status"),
        },
        "bracket_repairs": bracket["repaired"],
        "base_price": bracket["base_price"],
        "external_trade_ref": external_ref,
    })


def _handle_get_order_status(user_id, body):
    creds, err = _require_creds(user_id)
    if err:
        return err
    alpaca_order_id = body.get("alpaca_order_id")
    if not alpaca_order_id:
        return jsonify({"error": "alpaca_order_id is required"}), 400
    res = alpaca_fetch(creds, f"/orders/{alpaca_order_id}")
    if not res.ok:
        return jsonify({"error": "Failed to fetch order status"}), 400
    order_data = res.json()
    new_status = order_data.get("status")
    filled_avg = float(order_data["filled_avg_price"]) if order_data.get("filled_avg_price") else None
    filled_qty = float(order_data["filled_qty"]) if order_data.get("filled_qty") else None

    _supabase_patch(
        "alpaca_orders",
        "alpaca_order_id",
        alpaca_order_id,
        {
            "order_status": new_status,
            "filled_avg_price": filled_avg,
            "filled_qty": filled_qty,
            "filled_at": order_data.get("filled_at"),
            "updated_at": now_iso(),
        },
        user_id=user_id,
    )

    paper_trade_uuid = to_uuid_or_null(body.get("paper_trade_id"))
    if paper_trade_uuid:
        patch = {"alpaca_order_status": new_status}
        if filled_avg:
            patch["alpaca_filled_price"] = filled_avg
        if new_status == "filled":
            patch["alpaca_filled_at"] = order_data.get("filled_at") or now_iso()
        _supabase_patch("paper_trades", "id", paper_trade_uuid, patch)

    return jsonify({
        "order": {
            "alpaca_order_id": alpaca_order_id,
            "order_status": new_status,
            "filled_avg_price": filled_avg,
            "filled_qty": filled_qty,
            "filled_at": order_data.get("filled_at"),
            "symbol": order_data.get("symbol"),
            "side": order_data.get("side"),
        },
    })


def _handle_get_positions(user_id):
    creds, err = _require_creds(user_id)
    if err:
        return err
    res = alpaca_fetch(creds, "/positions")
    if not res.ok:
        return jsonify({"error": "Failed to fetch positions"}), 400
    positions = res.json()
    mapped = []
    for p in positions if isinstance(positions, list) else []:
        mapped.append({
            "symbol": p.get("symbol"),
            "qty": float(p.get("qty", 0)),
            "side": p.get("side"),
            "avg_entry_price": float(p.get("avg_entry_price", 0)),
            "current_price": float(p.get("current_price", 0)),
            "unrealized_pl": float(p.get("unrealized_pl", 0)),
            "market_value": float(p.get("market_value", 0)),
        })
    return jsonify({"positions": mapped})


def _handle_get_live_orders(user_id, body):
    creds, err = _require_creds(user_id)
    if err:
        return err
    status = body.get("status", "all")
    limit = body.get("limit", 50)
    after = body.get("after")
    path = f"/orders?status={status}&limit={limit}&direction=desc"
    if after:
        path += f"&after={after}"
    res = alpaca_fetch(creds, path)
    if not res.ok:
        return jsonify({"error": "Failed to fetch live orders", "detail": res.text}), 400
    raw = res.json()
    orders = raw if isinstance(raw, list) else []
    return jsonify({"orders": orders, "fetched_at": now_iso()})


def _handle_get_account_activity(user_id):
    creds, err = _require_creds(user_id)
    if err:
        return err
    res = alpaca_fetch(creds, "/account")
    if not res.ok:
        return jsonify({"error": "Failed to fetch account"}), 400
    account = res.json()
    equity = float(account.get("equity") or 0)
    last_equity = float(account.get("last_equity") or 0)
    return jsonify({
        "daily_pnl": equity - last_equity,
        "equity": equity,
        "last_equity": last_equity,
        "fetched_at": now_iso(),
    })


def _handle_close_position(user_id, body):
    creds, err = _require_creds(user_id)
    if err:
        return err
    symbol = body.get("symbol")
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    res = alpaca_fetch(creds, f"/positions/{symbol.upper()}", "DELETE")
    if not res.ok:
        return jsonify({"error": "Failed to close position", "detail": res.text}), 400
    close_data = res.json() if res.content else {}
    _log_order(user_id, {
        "paper_trade_id": to_uuid_or_null(body.get("paper_trade_id")),
        "alpaca_order_id": close_data.get("id"),
        "symbol": symbol.upper(),
        "side": close_data.get("side") or "sell",
        "order_type": "market",
        "order_class": "simple",
        "order_status": close_data.get("status") or "pending_new",
        "event_type": "POSITION_CLOSE",
        "alpaca_response": json.dumps(close_data),
    })
    return jsonify({"success": True, "order": close_data})


def _handle_emergency_kill_switch(user_id):
    creds, err = _require_creds(user_id)
    if err:
        return err
    cancelled = 0
    closed = 0
    errors = []
    try:
        cancel_res = alpaca_fetch(creds, "/orders", "DELETE")
        if cancel_res.ok:
            data = cancel_res.json()
            cancelled = len(data) if isinstance(data, list) else 0
    except Exception as exc:
        errors.append(f"Cancel orders: {exc}")
    try:
        close_res = alpaca_fetch(creds, "/positions", "DELETE")
        if close_res.ok:
            data = close_res.json()
            closed = len(data) if isinstance(data, list) else 0
    except Exception as exc:
        errors.append(f"Close positions: {exc}")
    _log_order(user_id, {
        "event_type": "EMERGENCY_KILL_SWITCH",
        "order_status": "kill_switch_activated",
        "alpaca_response": json.dumps({"cancelled_orders": cancelled, "closed_positions": closed, "errors": errors}),
    })
    return jsonify({"success": True, "cancelled_orders": cancelled, "closed_positions": closed, "errors": errors})


def _handle_get_alpaca_orders(user_id, body):
    limit = body.get("limit", 50)
    orders = _supabase_get_alpaca_orders(user_id, limit)
    return jsonify({"orders": orders})


def _dispatch_action(action, user_id, body):
    if action == "save_credentials":
        return _handle_save_credentials(user_id, body)
    if action == "load_credentials":
        return _handle_load_credentials(user_id)
    if action == "delete_credentials":
        return _handle_delete_credentials(user_id, body)
    if action == "test_connection":
        return _handle_test_connection(user_id)
    if action == "get_account":
        return _handle_get_account(user_id)
    if action == "send_test_order":
        return _handle_send_test_order(user_id)
    if action == "submit_entry_order":
        return _handle_submit_entry_order(user_id, body)
    if action == "cancel_order":
        return _handle_cancel_order(user_id, body)
    if action == "reconcile_fills":
        return _handle_reconcile_fills(user_id, body)
    if action == "get_order_status":
        return _handle_get_order_status(user_id, body)
    if action == "get_positions":
        return _handle_get_positions(user_id)
    if action == "get_live_orders":
        return _handle_get_live_orders(user_id, body)
    if action == "get_account_activity":
        return _handle_get_account_activity(user_id)
    if action == "close_position":
        return _handle_close_position(user_id, body)
    if action == "emergency_kill_switch":
        return _handle_emergency_kill_switch(user_id)
    if action == "get_alpaca_orders":
        return _handle_get_alpaca_orders(user_id, body)
    if action == "check_asset":
        creds, err = _require_creds(user_id)
        if err:
            return err
        sym = body.get("symbol")
        if not sym:
            return jsonify({"error": "symbol is required"}), 400
        res = alpaca_fetch(creds, f"/assets/{sym.upper()}")
        if not res.ok:
            return jsonify({"error": "Asset lookup failed", "detail": res.text}), 400
        asset = res.json()
        return jsonify({
            "symbol": asset.get("symbol"),
            "shortable": asset.get("shortable") is True,
            "easy_to_borrow": asset.get("easy_to_borrow") is True,
            "tradable": asset.get("tradable"),
            "status": asset.get("status"),
        })
    if action == "reset_paper_account":
        creds, err = _require_creds(user_id)
        if err:
            return err
        alpaca_fetch(creds, "/orders", "DELETE")
        alpaca_fetch(creds, "/positions", "DELETE")
        account_res = alpaca_fetch(creds, "/account")
        account = account_res.json() if account_res.ok else None
        import requests

        if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
            requests.delete(
                f"{SUPABASE_URL}/rest/v1/alpaca_orders",
                params={"user_id": f"eq.{user_id}"},
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                },
                timeout=15,
            )
        return jsonify({
            "success": True,
            "message": "Alpaca paper account reset.",
            "account": _masked_account_payload(
                creds.get("mode"), account, success=True
            ).get("account") if account else None,
        })
    return jsonify({"error": f"Unknown action: {action}"}), 400


@alpaca_bp.route("/<action>", methods=["POST", "OPTIONS"])
def alpaca_action(action):
    if request.method == "OPTIONS":
        return "", 204

    normalized = _normalize_action(action)
    if normalized not in KNOWN_ACTIONS:
        return jsonify({"error": f"Unknown action: {action}"}), 404

    user_id, auth_err = _require_auth()
    if auth_err:
        return auth_err

    body = request.get_json(silent=True) or {}
    result = _dispatch_action(normalized, user_id, body)
    # Sanitize any Response JSON body before it reaches the browser
    if isinstance(result, tuple) and len(result) >= 1:
        resp = result[0]
        code = result[1] if len(result) > 1 else 200
        if hasattr(resp, "get_json"):
            data = resp.get_json(silent=True)
            if isinstance(data, (dict, list)):
                return _public_json(data, code)
        return result
    if hasattr(result, "get_json"):
        data = result.get_json(silent=True)
        if isinstance(data, (dict, list)):
            status = getattr(result, "status_code", 200) or 200
            return _public_json(data, status)
    return result
