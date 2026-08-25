"""Trading and broker read-only actions."""

from __future__ import annotations

from aria.actions._helpers import compute_realized_pnl, compute_unrealized_pnl, json_result
from aria.registry import ActionContext, ActionResult, registry


def _register_trading_actions() -> None:
    r = registry
    actions = [
        ("get_open_trades", "All currently open trades.", _open_trades),
        ("get_closed_trades", "Recently closed trades.", _closed_trades, {"limit": {"type": "integer"}}),
        ("get_account_balance", "Account balance from broker context.", _balance),
        ("get_unrealized_pnl", "Unrealized P&L from open positions.", _unrealized),
        ("get_realized_pnl", "Realized P&L from closed trades.", _realized),
        ("get_broker_status", "Broker connection and account status.", _broker),
        ("get_active_strategies", "Strategies currently active/enabled.", _strategies),
        ("get_enabled_markets", "Markets currently enabled for scanning/trading.", _markets),
        ("get_top_trade", "Current Top Trade setup with full signal data.", _top_trade),
        ("get_market_conditions", "Current market conditions for active market.", _conditions),
    ]
    for item in actions:
        name, desc, handler = item[0], item[1], item[2]
        props = item[3] if len(item) > 3 else None
        r.register_action(name, desc, handler, category="trading", properties=props or {})


def _open_trades(ctx: ActionContext) -> ActionResult:
    if ctx.user_id and ctx.auth_header:
        from aria.truth_gateway import get_open_trades_truth
        return get_open_trades_truth(ctx)
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": "unauthenticated_context_fallback_disabled",
            "message": "Open trades require authenticated truth-gateway access.",
        })
    )


def _closed_trades(ctx: ActionContext) -> ActionResult:
    if ctx.user_id and ctx.auth_header:
        from aria.truth_gateway import get_closed_trades_truth
        return get_closed_trades_truth(ctx)
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": "unauthenticated_context_fallback_disabled",
            "message": "Closed trades require authenticated truth-gateway access.",
        })
    )


def _balance(ctx: ActionContext) -> ActionResult:
    if ctx.user_id and ctx.auth_header:
        from aria.truth_gateway import get_account_summary
        return get_account_summary(ctx)
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": "unauthenticated_context_fallback_disabled",
        })
    )


def _unrealized(ctx: ActionContext) -> ActionResult:
    if ctx.user_id and ctx.auth_header:
        from aria import supabase_user as sb
        open_trades = sb.fetch_open_trades(ctx.auth_header, ctx.user_id, limit=100)
        pnl = compute_unrealized_pnl(open_trades)
        return ActionResult(result=json_result({
            "verified": True,
            "unrealizedPnl": pnl,
            "openPositions": len(open_trades),
            "source": "jwt_scoped",
        }))
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": "unauthenticated_context_fallback_disabled",
        })
    )


def _realized(ctx: ActionContext) -> ActionResult:
    if ctx.user_id and ctx.auth_header:
        from aria.truth_gateway import get_performance_truth
        return get_performance_truth(ctx)
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": "unauthenticated_context_fallback_disabled",
        })
    )


def _broker(ctx: ActionContext) -> ActionResult:
    # Never surface broker credentials. Status only from scrubbed client state if present.
    state = ctx.state or {}
    return ActionResult(result=json_result({
        "verified": False,
        "brokerStatus": state.get("brokerStatus") or "Not connected",
        "brokerName": state.get("brokerName"),
        "connected": state.get("brokerConnected"),
        "note": "Credential fields are never returned. Live broker multi-user is out of Phase 2A scope.",
        "credentials_included": False,
    }))


def _strategies(ctx: ActionContext) -> ActionResult:
    if ctx.user_id and ctx.auth_header:
        from aria import supabase_user as sb
        risk = sb.fetch_risk_account_settings(ctx.auth_header, ctx.user_id) or {}
        toggles = risk.get("strategy_toggles") or {}
        return ActionResult(result=json_result({
            "verified": True,
            "strategy_toggles": toggles if isinstance(toggles, dict) else {},
            "source": "risk_account_settings_jwt_scoped",
            "note": "Toggle map is per-user; missing keys may mean hasGlobalToggle:false.",
        }))
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": "unauthenticated_context_fallback_disabled",
        })
    )


def _markets(ctx: ActionContext) -> ActionResult:
    if ctx.user_id and ctx.auth_header:
        from aria.truth_gateway import get_market_status_truth
        return get_market_status_truth(ctx)
    return ActionResult(
        result=json_result({
            "verified": False,
            "cannot_verify": True,
            "reason": "unauthenticated_context_fallback_disabled",
        })
    )


def _top_trade(ctx: ActionContext) -> ActionResult:
    top = ctx.state.get("topTrade") or ctx.state.get("lastSignalData")
    return ActionResult(result=json_result(top) if top else "No Top Trade data in current context.")


def _conditions(ctx: ActionContext) -> ActionResult:
    state = ctx.state
    return ActionResult(result=json_result({
        "market": state.get("activeMarket"),
        "timeframe": state.get("activeTimeframe"),
        "signal": state.get("currentSignal"),
        "confidence": state.get("confidence"),
        "tradeReadiness": state.get("tradeReadiness"),
        "marketRegime": state.get("marketRegime"),
        "marketState": state.get("marketState"),
        "dominantBias": state.get("dominantBias"),
        "lineOfLeastResistance": state.get("lineOfLeastResistance"),
        "entryTiming": state.get("entryTiming"),
        "setupGrade": state.get("setupGrade"),
    }))


_register_trading_actions()
