"""WickSense strategy knowledge base for ARIA explain/validate tools."""

from __future__ import annotations

import json
from typing import Any

STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "strategy_001": {
        "id": "strategy_001",
        "name": "Bearish Wick Rejection Sniper",
        "code": "S001",
        "direction": "bearish",
        "description": "Identifies bearish wick rejections at key levels with sniper-style precision entries.",
        "parameters": {"min_wick_ratio": 0.6, "confirmation_required": True},
    },
    "strategy_001_bullish": {
        "id": "strategy_001_bullish",
        "name": "Bullish Wick Rejection Sniper",
        "code": "S001 Bullish",
        "direction": "bullish",
        "description": "Bullish counterpart to S001 — wick rejection long entries.",
        "parameters": {"min_wick_ratio": 0.6, "confirmation_required": True},
    },
    "strategy_002": {
        "id": "strategy_002",
        "name": "Bullish Wick Rejection Sniper V3",
        "code": "S002",
        "direction": "bullish",
        "description": "V3 bullish wick rejection with enhanced confirmation filters.",
        "parameters": {"min_wick_ratio": 0.65, "v3_enforcement": True},
    },
    "strategy_003": {
        "id": "strategy_003",
        "name": "Trend Pullback Wick Confirmation",
        "code": "S003",
        "direction": "both",
        "description": "Pullback entries in established trends confirmed by wick structure.",
        "parameters": {"trend_lookback": 20, "pullback_depth_atr": 1.5},
    },
    "s108": {
        "id": "s108",
        "name": "S108 Hammer",
        "code": "S108",
        "direction": "bullish",
        "description": "Hammer reversal pattern — V2 enforcement active, BUY-only. Requires confirmation above hammer high.",
        "parameters": {"buy_only": True, "v2_enforcement": True, "confirmation_above_high": True},
        "validation_note": "V2 enforcement active — blocked without confirmation candle.",
    },
    "bearish_confluence_setup": {
        "id": "bearish_confluence_setup",
        "name": "Bearish Confluence Setup",
        "code": "S103",
        "direction": "bearish",
        "description": "Multi-factor bearish confluence with V2 enforcement.",
        "parameters": {"v2_enforcement": True, "min_confluence_score": 3},
    },
    "s111_v2": {
        "id": "s111_v2",
        "name": "Support/Resistance Rejection V2",
        "code": "S111",
        "direction": "both",
        "description": "S/R rejection with V2 validation rules.",
        "parameters": {"v2_enforcement": True},
    },
    "wicksense_t1": {
        "id": "wicksense_t1",
        "name": "WickSense T1 — Liquidity Sweep",
        "code": "T1",
        "direction": "both",
        "description": "Liquidity sweep detection and reversal entry system.",
        "parameters": {"sweep_lookback": 15},
    },
}


def _normalize_key(name: str) -> str:
    return (name or "").lower().strip().replace(" ", "_").replace("-", "_")


def find_strategy(query: str) -> dict[str, Any] | None:
    q = _normalize_key(query)
    if not q:
        return None
    if q in STRATEGY_CATALOG:
        return STRATEGY_CATALOG[q]
    for key, strat in STRATEGY_CATALOG.items():
        if q in key or q in _normalize_key(strat.get("name", "")):
            return strat
        if q in (strat.get("code") or "").lower().replace(" ", ""):
            return strat
    return None


def explain_strategy(query: str) -> str:
    strat = find_strategy(query)
    if not strat:
        return f"No strategy catalog entry found for '{query}'. Try an ID like S108, strategy_003, or a strategy name."
    lines = [
        f"{strat['name']} ({strat.get('code', strat['id'])})",
        f"Direction: {strat.get('direction', 'unknown')}",
        f"Description: {strat.get('description', 'N/A')}",
    ]
    if strat.get("validation_note"):
        lines.append(f"Validation: {strat['validation_note']}")
    return "\n".join(lines)


def get_strategy_parameters(query: str, state: dict[str, Any]) -> str:
    strat = find_strategy(query)
    meta = (state.get("strategyMeta") or {}).get(strat["id"] if strat else query, {})
    params = {**(strat.get("parameters") if strat else {}), **meta.get("parameters", {})}
    if not params:
        return f"No parameters available for '{query}'."
    return json.dumps(params, indent=2)


def get_strategy_recent_performance(query: str, state: dict[str, Any]) -> str:
    stats = state.get("strategyStats") or {}
    q = (query or "").lower()
    matched = {k: v for k, v in stats.items() if q in k.lower()} if q else stats
    if not matched:
        return f"No recent performance data for '{query}' in current session."
    return json.dumps(matched, indent=2, default=str)


def get_strategy_validation_status(query: str, state: dict[str, Any]) -> str:
    strat = find_strategy(query)
    meta = (state.get("strategyMeta") or {})
    key = strat["id"] if strat else _normalize_key(query)
    info = meta.get(key) or {}
    validation = info.get("validation") or info.get("validation_status")
    if validation:
        return json.dumps(validation, indent=2, default=str)
    if strat and strat.get("validation_note"):
        return strat["validation_note"]
    blocked = state.get("blockedStrategies") or []
    if key in blocked or (strat and strat.get("name") in blocked):
        return "Strategy is currently blocked/disabled in WickSense."
    return f"Validation status for '{query}' not in live context. Check Strategy Command Center for lifecycle state."


def get_strategy_incubation_status(query: str, state: dict[str, Any]) -> str:
    meta = (state.get("strategyMeta") or {})
    strat = find_strategy(query)
    key = strat["id"] if strat else _normalize_key(query)
    incubation = meta.get(key, {}).get("incubation") or meta.get(key, {}).get("incubation_status")
    if incubation:
        return json.dumps(incubation, indent=2, default=str)
    return f"Incubation status for '{query}' not in live context. Strategies in TESTING phase need closed-trade validation thresholds."


def get_strategy_failure_analysis(query: str, state: dict[str, Any]) -> str:
    reasons = state.get("failureReasons") or []
    analysis = state.get("postStopAnalysis")
    strat = find_strategy(query)
    q = (strat.get("name") if strat else query or "").lower()
    filtered = [r for r in reasons if q in str(r).lower()] if q else reasons
    result = {"failure_reasons": filtered, "post_stop_analysis": analysis}
    if not filtered and not analysis:
        return f"No failure analysis available for '{query}' in current context."
    return json.dumps(result, indent=2, default=str)
