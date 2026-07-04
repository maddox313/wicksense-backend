"""Platform snapshot actions."""

from __future__ import annotations

from aria.actions._helpers import json_result
from aria.registry import ActionContext, ActionResult, registry


def _register_platform_actions() -> None:
    r = registry
    r.register_action("get_wicksense_snapshot", "Full WickSense app state snapshot.", _snapshot, category="platform")
    r.register_action("get_dashboard_state", "Dashboard UI state: open modals, selected market/timeframe.", _dashboard, category="platform")
    r.register_action("get_alerts", "Active alerts and notifications from context.", _alerts, category="platform")
    r.register_action(
        "get_market_news", "Cached daily market news.", _market_news,
        category="platform", properties={"market": {"type": "string"}},
    )
    r.register_action(
        "refresh_market_news", "Fetch fresh news via Perplexity.", _refresh_news,
        category="platform", properties={"query": {"type": "string"}}, required=["query"],
    )


def _snapshot(ctx: ActionContext) -> ActionResult:
    from aria.prompt import detect_risk_warnings
    state = ctx.state
    data = {
        "activeMarket": state.get("activeMarket"),
        "activeTimeframe": state.get("activeTimeframe"),
        "currentSignal": state.get("currentSignal"),
        "confidence": state.get("confidence"),
        "tradeReadiness": state.get("tradeReadiness"),
        "marketRegime": state.get("marketRegime"),
        "pnl": state.get("pnl"),
        "winRate": state.get("winRate"),
        "openTradesCount": len(state.get("openTrades") or []),
        "closedTradesCount": len(state.get("closedTrades") or []),
        "topTrade": state.get("topTrade") or state.get("lastSignalData"),
        "riskWarnings": detect_risk_warnings(state),
    }
    return ActionResult(result=json_result(data))


def _dashboard(ctx: ActionContext) -> ActionResult:
    state = ctx.state
    return ActionResult(result=json_result({
        "activeMarket": state.get("activeMarket"),
        "activeTimeframe": state.get("activeTimeframe"),
        "openModals": state.get("openModals") or [],
        "alertsCount": len(state.get("alerts") or []),
    }))


def _alerts(ctx: ActionContext) -> ActionResult:
    alerts = ctx.state.get("alerts") or []
    return ActionResult(result=json_result(alerts) if alerts else "No active alerts.")


def _market_news(ctx: ActionContext) -> ActionResult:
    from aria.actions._helpers import format_news_items
    return ActionResult(result=format_news_items(ctx.news, ctx.arguments.get("market")))


def _refresh_news(ctx: ActionContext) -> ActionResult:
    from aria.actions._helpers import fetch_perplexity_news
    query = ctx.arguments.get("query") or "Latest market news for day traders"
    return ActionResult(result=fetch_perplexity_news(query))


_register_platform_actions()
