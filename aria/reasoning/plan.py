"""PLAN — decide approach and suggested tool sequence."""

from __future__ import annotations

from aria.reasoning.models import MemoryRecall, Observation, ReasoningPlan

INTENT_TO_ACTIONS: dict[str, list[str]] = {
    "navigation": ["list_routes", "navigate_to_page", "open_modal"],
    "trading": ["get_open_trades", "get_closed_trades", "get_unrealized_pnl", "get_realized_pnl", "get_broker_status"],
    "strategy": ["explain_strategy", "get_strategy_performance", "get_strategy_recent_performance"],
    "news": ["get_market_news", "refresh_market_news"],
    "market": ["get_wicksense_snapshot", "get_top_trade", "get_market_conditions"],
    "risk": ["get_wicksense_snapshot", "get_alerts"],
    "settings": ["open_settings", "get_dashboard_state"],
}


def build_plan(observation: Observation, recall: MemoryRecall) -> ReasoningPlan:
    hints = observation.intent_hints or ["general"]
    primary = hints[0]

    goal_map = {
        "navigation": "Help the user reach the right WickSense page or panel efficiently.",
        "trading": "Answer with accurate live trade and P&L data from WickSense context.",
        "strategy": "Explain strategy behavior and performance using catalog + live stats.",
        "news": "Summarize relevant market news from cached brief or refresh if needed.",
        "market": "Analyze current market conditions, Top Trade, and signal quality.",
        "risk": "Surface active risk warnings and recommend cautious next steps.",
        "settings": "Guide the user to account/settings or relevant configuration.",
        "general": "Understand intent, use tools as needed, respond as an executive trading assistant.",
    }

    suggested: list[str] = []
    for hint in hints:
        for action in INTENT_TO_ACTIONS.get(hint, []):
            if action not in suggested:
                suggested.append(action)

    if not suggested:
        suggested = ["get_wicksense_snapshot"]

    personalization_parts: list[str] = []
    for item in recall.items[:3]:
        if item.kind in ("preference", "strategy", "routine"):
            personalization_parts.append(item.content)

    notes = []
    if observation.risk_warning_count > 0:
        notes.append(f"{observation.risk_warning_count} active risk warning(s) — mention if relevant.")
    if observation.open_trades_count > 0:
        notes.append(f"User has {observation.open_trades_count} open trade(s).")
    if observation.active_market:
        notes.append(f"Chart market: {observation.active_market}.")

    return ReasoningPlan(
        goal=goal_map.get(primary, goal_map["general"]),
        suggested_actions=suggested[:5],
        reasoning_notes=" ".join(notes),
        personalization="; ".join(personalization_parts) if personalization_parts else "",
    )
