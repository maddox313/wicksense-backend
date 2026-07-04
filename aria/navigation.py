"""WickSense navigation and modal routing for ARIA tools."""

from __future__ import annotations

from typing import Any

# All protected React routes (Routes.jsx)
ROUTE_CATALOG: list[dict[str, Any]] = [
    {"route": "/dashboard", "label": "Dashboard", "patterns": ["dashboard", "home", "main"]},
    {"route": "/paper-trading-dashboard", "label": "Paper Trading Dashboard", "patterns": ["paper trading", "paper trade", "paper"]},
    {"route": "/signal-analytics", "label": "Signal Analytics", "patterns": ["signal analytics", "signal analysis", "analytics"]},
    {"route": "/strategy-command-center", "label": "Strategy Command Center", "patterns": ["strategy command", "strategy center", "all strategies"]},
    {"route": "/strategy-monitor", "label": "Strategy Monitor", "patterns": ["strategy monitor", "monitor strategies"]},
    {"route": "/strategy-promotion", "label": "Strategy Promotion", "patterns": ["strategy promotion", "promote strategy"]},
    {"route": "/strategy-reference-library", "label": "Strategy Reference Library", "patterns": ["strategy library", "reference library"]},
    {"route": "/profit-dashboard", "label": "Profit Dashboard", "patterns": ["profit dashboard", "profit", "pnl dashboard"]},
    {"route": "/trade-plan-page", "label": "Trade Plan", "patterns": ["trade plan", "trade planning"]},
    {"route": "/backtest-results", "label": "Backtest Results", "patterns": ["backtest", "back test"]},
    {"route": "/market-scanner", "label": "Market Scanner", "patterns": ["scanner", "market scanner", "scan"]},
    {"route": "/history", "label": "Trade History", "patterns": ["history", "trade history"]},
    {"route": "/trade-journal", "label": "Trade Journal", "patterns": ["journal", "trade journal"]},
    {"route": "/alerts", "label": "Alerts", "patterns": ["alerts", "alert rules"]},
    {"route": "/notification-settings", "label": "Notification Settings", "patterns": ["notification settings", "notifications settings"]},
    {"route": "/presets-management", "label": "Presets Management", "patterns": ["presets", "preset management"]},
    {"route": "/tutorial-page", "label": "Tutorial", "patterns": ["tutorial", "learn", "guide"]},
    {"route": "/trainers", "label": "Trainers", "patterns": ["trainers", "trainer", "coaching"]},
    {"route": "/account-management", "label": "Account Management", "patterns": ["account", "profile"]},
    {"route": "/losing-trade-report", "label": "Losing Trade Report", "patterns": ["losing trade", "failure report", "loss report"]},
    {"route": "/trading-knowledge-analyzer", "label": "Knowledge Analyzer", "patterns": ["knowledge analyzer", "knowledge"]},
    {"route": "/signal-replay", "label": "Signal Replay", "patterns": ["signal replay", "replay"]},
    {"route": "/trade-rankings", "label": "Trade Rankings", "patterns": ["trade rankings", "rankings", "top trade rankings"]},
    {"route": "/risk-account", "label": "Risk Account", "patterns": ["risk account", "risk settings"]},
    {"route": "/market-matrix", "label": "Market Matrix", "patterns": ["market matrix", "matrix"]},
    {"route": "/trade-queue-control", "label": "Trade Queue Control", "patterns": ["trade queue", "queue control"]},
    {"route": "/systems-center", "label": "Systems Center", "patterns": ["systems center", "systems"]},
    {"route": "/dev-tools", "label": "Dev Tools / Diagnostics", "patterns": ["dev tools", "diagnostics", "debug tools"]},
    {"route": "/metrics-reconciliation", "label": "Metrics Reconciliation", "patterns": ["metrics reconciliation", "metrics debug"]},
    {"route": "/content-scripts", "label": "Content Scripts", "patterns": ["content scripts"]},
    {"route": "/training-sessions", "label": "Training Sessions", "patterns": ["training sessions", "training"]},
    {"route": "/session-booking", "label": "Session Booking", "patterns": ["session booking", "book session"]},
]

# Dashboard draggable modals (PANEL_CONFIG ids)
MODAL_CATALOG: list[dict[str, Any]] = [
    {"modal_id": "performance", "label": "Performance Panel", "patterns": ["performance", "performance panel"]},
    {"modal_id": "strategy", "label": "Strategy & Scanner Panel", "patterns": ["strategy panel", "strategy modal", "strategy and scanner"]},
    {"modal_id": "replay", "label": "Signal Replay Panel", "patterns": ["replay panel", "replay modal"]},
    {"modal_id": "paper_trades", "label": "Paper Trades Panel", "patterns": ["paper trades panel", "paper trades modal"]},
    {"modal_id": "top_trade", "label": "Top Trade Focus", "patterns": ["top trade", "best trade", "current trade setup"]},
    {"modal_id": "market_news", "label": "Market News Brief", "patterns": ["market news modal", "news brief", "daily news"]},
    {"modal_id": "snapshot", "label": "Snapshot Analysis", "patterns": ["snapshot", "chart snapshot", "snapshot analysis"]},
    {"modal_id": "wicksense_engine", "label": "WickSense Engine", "patterns": ["wicksense engine", "engine modal"]},
]

# Shortcut aliases → route or modal action
SHORTCUT_ACTIONS: dict[str, dict[str, str]] = {
    "open_scanner": {"type": "navigate", "route": "/market-scanner", "label": "Market Scanner"},
    "open_journal": {"type": "navigate", "route": "/trade-journal", "label": "Trade Journal"},
    "open_diagnostics": {"type": "navigate", "route": "/dev-tools", "label": "Dev Tools / Diagnostics"},
    "open_settings": {"type": "navigate", "route": "/account-management", "label": "Account Management"},
    "open_strategy_performance": {"type": "open_modal", "modal_id": "strategy", "label": "Strategy & Scanner"},
    "open_top_trade": {"type": "focus_top_trade", "route": "/dashboard", "label": "Top Trade"},
}


def resolve_route(destination: str) -> dict[str, str] | None:
    text = (destination or "").lower().strip()
    if text.startswith("/"):
        for entry in ROUTE_CATALOG:
            if entry["route"].lower() == text.lower():
                return {"route": entry["route"], "label": entry["label"]}
        return {"route": text, "label": text.strip("/").replace("-", " ").title()}

    for entry in ROUTE_CATALOG:
        if any(p in text for p in entry["patterns"]):
            return {"route": entry["route"], "label": entry["label"]}
        if entry["label"].lower() in text:
            return {"route": entry["route"], "label": entry["label"]}
    return None


def resolve_modal(name: str) -> dict[str, str] | None:
    text = (name or "").lower().strip()
    for entry in MODAL_CATALOG:
        if entry["modal_id"] == text:
            return {"modal_id": entry["modal_id"], "label": entry["label"]}
        if any(p in text for p in entry["patterns"]):
            return {"modal_id": entry["modal_id"], "label": entry["label"]}
        if entry["label"].lower() in text:
            return {"modal_id": entry["modal_id"], "label": entry["label"]}
    return None


def list_routes() -> list[dict[str, str]]:
    return [{"route": r["route"], "label": r["label"]} for r in ROUTE_CATALOG]


def list_modals() -> list[dict[str, str]]:
    return [{"modal_id": m["modal_id"], "label": m["label"]} for m in MODAL_CATALOG]


def build_client_action(action_type: str, **kwargs) -> dict[str, Any]:
    return {"type": action_type, **kwargs}
