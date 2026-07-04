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
    return ActionResult(result=json_result(ctx.state.get("openTrades") or []))


def _closed_trades(ctx: ActionContext) -> ActionResult:
    limit = int(ctx.arguments.get("limit") or 10)
    trades = (ctx.state.get("closedTrades") or [])[:limit]
    return ActionResult(result=json_result(trades))


def _balance(ctx: ActionContext) -> ActionResult:
    state = ctx.state
    return ActionResult(result=json_result({
        "balance": state.get("accountBalance") or state.get("buyingPower"),
        "buyingPower": state.get("buyingPower"),
        "currency": state.get("accountCurrency") or "USD",
    }))


def _unrealized(ctx: ActionContext) -> ActionResult:
    open_trades = ctx.state.get("openTrades") or []
    pnl = ctx.state.get("unrealizedPnl")
    if pnl is None:
        pnl = compute_unrealized_pnl(open_trades)
    return ActionResult(result=json_result({"unrealizedPnl": pnl, "openPositions": len(open_trades)}))


def _realized(ctx: ActionContext) -> ActionResult:
    closed = ctx.state.get("closedTrades") or []
    pnl = ctx.state.get("realizedPnl")
    if pnl is None:
        pnl = compute_realized_pnl(closed)
    return ActionResult(result=json_result({"realizedPnl": pnl, "closedTrades": len(closed)}))


def _broker(ctx: ActionContext) -> ActionResult:
    state = ctx.state
    return ActionResult(result=json_result({
        "brokerStatus": state.get("brokerStatus") or "Not connected",
        "brokerName": state.get("brokerName"),
        "accountId": state.get("accountId"),
        "connected": state.get("brokerConnected"),
        "positions": state.get("brokerPositions") or [],
        "buyingPower": state.get("buyingPower"),
    }))


def _strategies(ctx: ActionContext) -> ActionResult:
    strategies = ctx.state.get("activeStrategies") or list((ctx.state.get("strategyStats") or {}).keys())
    return ActionResult(result=json_result(strategies))


def _markets(ctx: ActionContext) -> ActionResult:
    markets = ctx.state.get("enabledMarkets") or ([ctx.state.get("activeMarket")] if ctx.state.get("activeMarket") else [])
    return ActionResult(result=json_result(markets))


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
