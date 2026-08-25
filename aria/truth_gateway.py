"""ARIA Truth Gateway — authenticated, JWT-bound read tools."""

from __future__ import annotations

from typing import Any

from aria.actions._helpers import json_result
from aria.registry import ActionContext, ActionResult, registry
from aria import supabase_user as sb


# Static producer mount knowledge (mirrors frontend PRODUCER_MOUNT_CATALOG — informational only).
PRODUCER_OPERATIONAL: dict[str, dict[str, Any]] = {
    "s111_v2": {"poller": "useStrategy111Poller", "timeframe": "15m", "mount": "PaperTradesContext"},
    "s113": {"poller": "useStrategy113Poller", "timeframe": "15m", "mount": "PaperTradesContext"},
    "s114": {"poller": "useStrategy114Poller", "timeframe": "5m", "mount": "PaperTradesContext"},
    "s002ngm": {"poller": "useReferenceStrategiesPoller", "timeframe": "5m", "mount": "PaperTradesContext"},
    "strategy_005_ema_pullback": {"poller": "useStrategy005Poller", "timeframe": "1h", "mount": "PaperTradesContext"},
    "pin_bar": {"poller": "useStrategyPinBarPoller", "timeframe": "15m", "mount": "PaperTradesContext"},
}


def _auth(ctx: ActionContext) -> tuple[str | None, str | None]:
    return ctx.user_id, ctx.auth_header


def _unavailable(reason: str) -> ActionResult:
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": reason,
            "message": "ARIA cannot verify this from authenticated server data.",
        })
    )


def get_account_summary(ctx: ActionContext) -> ActionResult:
    user_id, auth = _auth(ctx)
    if not user_id or not auth:
        return _unavailable("missing_authenticated_user")
    risk = sb.fetch_risk_account_settings(auth, user_id)
    open_trades = sb.fetch_open_trades(auth, user_id, limit=100)
    closed = sb.fetch_closed_trades(auth, user_id, limit=50)
    realized = 0.0
    for t in closed:
        try:
            realized += float(t.get("pnl") or t.get("pnl_pts") or 0)
        except (TypeError, ValueError):
            pass
    return ActionResult(result=json_result({
        "verified": True,
        "user_id": user_id,
        "account_balance": (risk or {}).get("account_balance") or (risk or {}).get("account_size"),
        "risk_percent": (risk or {}).get("risk_percent"),
        "open_trade_count": len(open_trades),
        "closed_trade_sample_count": len(closed),
        "realized_pnl_sample": realized,
        "source": "supabase_jwt_scoped",
        "note": "Balance/risk from risk_account_settings; P&L sample from recent closed trades only.",
    }))


def get_open_trades_truth(ctx: ActionContext) -> ActionResult:
    user_id, auth = _auth(ctx)
    if not user_id or not auth:
        return _unavailable("missing_authenticated_user")
    trades = sb.fetch_open_trades(auth, user_id, limit=int(ctx.arguments.get("limit") or 50))
    return ActionResult(result=json_result({
        "verified": True,
        "user_id": user_id,
        "count": len(trades),
        "trades": trades,
        "source": "paper_trades_jwt_scoped",
    }))


def get_closed_trades_truth(ctx: ActionContext) -> ActionResult:
    user_id, auth = _auth(ctx)
    if not user_id or not auth:
        return _unavailable("missing_authenticated_user")
    trades = sb.fetch_closed_trades(auth, user_id, limit=int(ctx.arguments.get("limit") or 25))
    return ActionResult(result=json_result({
        "verified": True,
        "user_id": user_id,
        "count": len(trades),
        "trades": trades,
        "source": "closed_or_paper_trades_jwt_scoped",
    }))


def get_performance_truth(ctx: ActionContext) -> ActionResult:
    user_id, auth = _auth(ctx)
    if not user_id or not auth:
        return _unavailable("missing_authenticated_user")
    closed = sb.fetch_closed_trades(auth, user_id, limit=100)
    wins = losses = 0
    pnl_sum = 0.0
    for t in closed:
        try:
            p = float(t.get("pnl") or t.get("pnl_pts") or 0)
        except (TypeError, ValueError):
            p = 0.0
        pnl_sum += p
        if p > 0:
            wins += 1
        elif p < 0:
            losses += 1
    return ActionResult(result=json_result({
        "verified": True,
        "user_id": user_id,
        "sample_size": len(closed),
        "wins": wins,
        "losses": losses,
        "realized_pnl_sample": pnl_sum,
        "source": "recent_closed_trades_jwt_scoped",
        "note": "Sample-based; not a full-history statement if older rows are truncated.",
    }))


def get_market_status_truth(ctx: ActionContext) -> ActionResult:
    user_id, auth = _auth(ctx)
    if not user_id or not auth:
        return _unavailable("missing_authenticated_user")
    matrix = sb.fetch_strategy_market_matrix(auth, user_id)
    enabled = sorted({
        str(r.get("market_key") or r.get("market") or "").upper()
        for r in matrix
        if r.get("enabled") is True or r.get("enabled") == "true"
    } - {""})
    return ActionResult(result=json_result({
        "verified": True,
        "user_id": user_id,
        "enabled_markets": enabled,
        "matrix_rows": len(matrix),
        "source": "strategy_market_matrix_jwt_scoped",
    }))


def get_strategy_status_truth(ctx: ActionContext) -> ActionResult:
    """
    Multi-field strategy status — never collapsed to a single ACTIVE/GO.
    """
    user_id, auth = _auth(ctx)
    if not user_id or not auth:
        return _unavailable("missing_authenticated_user")

    strategy_id = (
        ctx.arguments.get("strategy_id")
        or ctx.arguments.get("strategyId")
        or ctx.arguments.get("canonical_strategy_id")
    )
    if not strategy_id:
        return _unavailable("strategy_id_required")

    sid = str(strategy_id)
    lifecycle_rows = sb.fetch_strategy_lifecycle(auth)
    life = next((r for r in lifecycle_rows if str(r.get("strategy_id")) == sid), None)

    risk = sb.fetch_risk_account_settings(auth, user_id) or {}
    toggles = risk.get("strategy_toggles") or {}
    if isinstance(toggles, str):
        toggles = {}
    user_enabled = toggles.get(sid)
    if user_enabled is None:
        # Missing toggle is NOT "disabled" for hasGlobalToggle:false strategies —
        # report as unknown rather than inventing false.
        user_enabled_status = "unknown_or_not_required"
    else:
        user_enabled_status = bool(user_enabled)

    matrix = sb.fetch_strategy_market_matrix(auth, user_id)
    markets_for = [r for r in matrix if str(r.get("strategy_id")) == sid]
    enabled_markets = [
        str(r.get("market_key") or "").upper()
        for r in markets_for
        if r.get("enabled") is True
    ]

    open_trades = sb.fetch_open_trades(auth, user_id, limit=100)
    strategy_opens = [t for t in open_trades if str(t.get("strategy_id")) == sid]

    producer = PRODUCER_OPERATIONAL.get(sid)
    auto_mode = None
    # Auto Mode is browser-session truth — cannot verify server-side in Phase 2A
    auto_mode_status = "cannot_verify_server_side"
    auto_mode_note = (
        "Auto Trading is browser-session dependent in Phase 2A; "
        "server cannot confirm whether the user's WickSense tab is open."
    )

    lifecycle_enabled = None
    if life is not None:
        lifecycle_enabled = bool(life.get("auto_trading_enabled")) and str(
            life.get("current_stage") or ""
        ).lower() not in ("paused", "retired", "archived")

    return ActionResult(result=json_result({
        "verified": True,
        "user_id": user_id,
        "strategy_id": sid,
        "producer_operational": bool(producer),
        "producer_detail": producer,
        "lifecycle_enabled": lifecycle_enabled,
        "lifecycle_stage": (life or {}).get("current_stage"),
        "lifecycle_auto_trading_enabled": (life or {}).get("auto_trading_enabled"),
        "user_strategy_enabled": user_enabled_status,
        "market_enabled": enabled_markets,
        "market_enabled_any": len(enabled_markets) > 0,
        "auto_mode": auto_mode,
        "auto_mode_status": auto_mode_status,
        "auto_mode_note": auto_mode_note,
        "candle_data_freshness": "cannot_verify",
        "engine_evaluation_status": "cannot_verify",
        "current_signal": "cannot_verify",
        "latest_rejection": "cannot_verify",
        "trade_attempted": "cannot_verify",
        "insert_result": "cannot_verify",
        "open_trades_for_strategy": len(strategy_opens),
        "open_trade_ids": [t.get("id") for t in strategy_opens[:20]],
        "source": "jwt_scoped_truth_gateway",
        "language_note": (
            "Do not say GO or ACTIVE merely because a toggle or lifecycle flag is on. "
            "Reserve trade language for an actual executable signal (not verified here)."
        ),
    }))


def _register_truth_gateway() -> None:
    r = registry
    r.register_action(
        "getAccountSummary",
        "Authenticated account summary (balance/risk/open counts) for the JWT user only.",
        get_account_summary,
        category="truth_gateway",
        tags=["truth", "account"],
    )
    r.register_action(
        "getStrategyStatus",
        "Multi-field strategy status for the JWT user. Never collapses to a single ACTIVE/GO.",
        get_strategy_status_truth,
        category="truth_gateway",
        properties={"strategy_id": {"type": "string", "description": "Canonical strategy id"}},
        required=["strategy_id"],
        tags=["truth", "strategy"],
    )
    r.register_action(
        "getOpenTrades",
        "Open/WAIT/ACTIVE paper trades for the authenticated user only.",
        get_open_trades_truth,
        category="truth_gateway",
        properties={"limit": {"type": "integer"}},
        tags=["truth", "trades"],
    )
    r.register_action(
        "getClosedTrades",
        "Recent closed trades for the authenticated user only.",
        get_closed_trades_truth,
        category="truth_gateway",
        properties={"limit": {"type": "integer"}},
        tags=["truth", "trades"],
    )
    r.register_action(
        "getPerformance",
        "Sample performance from recent closed trades for the authenticated user.",
        get_performance_truth,
        category="truth_gateway",
        tags=["truth", "performance"],
    )
    r.register_action(
        "getMarketStatus",
        "Enabled markets from the authenticated user's Command Center matrix.",
        get_market_status_truth,
        category="truth_gateway",
        tags=["truth", "markets"],
    )


_register_truth_gateway()
