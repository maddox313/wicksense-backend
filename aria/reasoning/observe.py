"""OBSERVE — build situational awareness from message + WickSense state."""

from __future__ import annotations

import re
from typing import Any

from aria.reasoning.models import Observation

INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("navigation", ["open", "go to", "navigate", "show me", "take me"]),
    ("trading", ["trade", "position", "pnl", "p&l", "open trades", "closed trades", "balance"]),
    ("strategy", ["strategy", "s108", "s001", "hammer", "performance", "validation", "incubation"]),
    ("news", ["news", "headline", "briefing", "why is", "moving"]),
    ("market", ["market", "signal", "readiness", "regime", "conditions", "top trade"]),
    ("risk", ["risk", "warning", "blocked", "discipline"]),
    ("settings", ["settings", "account", "preferences"]),
]


def observe(
    message: str,
    context: dict[str, Any] | None,
    history: list[dict[str, str]] | None,
) -> Observation:
    ctx = context or {}
    state = ctx.get("state") or {}
    text = (message or "").lower()

    hints: list[str] = []
    for intent, patterns in INTENT_PATTERNS:
        if any(p in text for p in patterns):
            hints.append(intent)

    tail = []
    for item in (history or [])[-4:]:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and content:
            tail.append({"role": role, "content": content[:200]})

    warnings = state.get("blockedStrategies") or []
    from aria.prompt import detect_risk_warnings

    risk_count = len(detect_risk_warnings(state))

    return Observation(
        user_message=message,
        active_market=state.get("activeMarket"),
        active_signal=state.get("currentSignal"),
        open_trades_count=len(state.get("openTrades") or []),
        risk_warning_count=risk_count,
        history_tail=tail,
        intent_hints=hints,
        raw_context_summary={
            "timeframe": state.get("activeTimeframe"),
            "readiness": state.get("tradeReadiness"),
            "pnl": state.get("pnl"),
            "blockedStrategies": warnings,
        },
    )
