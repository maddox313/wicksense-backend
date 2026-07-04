"""ARIA proactive intelligence event system."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any

# Event types ARIA monitors
EVENT_TYPES = {
    "new_signal",
    "trade_opened",
    "trade_closed",
    "large_profit",
    "large_loss",
    "broker_disconnected",
    "broker_connected",
    "strategy_disabled",
    "strategy_promoted",
    "strategy_incubation_completed",
    "market_news_updated",
    "high_impact_event",
    "risk_warning",
    "api_failure",
    "top_trade_changed",
    "alert_triggered",
}

# Natural-language templates for proactive notifications
EVENT_TEMPLATES: dict[str, str] = {
    "new_signal": "Based on WickSense data — new {signal} signal on {market} ({confidence}% confidence).",
    "trade_opened": "A trade was opened: {side} {symbol} via {strategy}.",
    "trade_closed": "Trade closed on {symbol}: {pnl} P&L.",
    "large_profit": "Large profit alert: +{pnl} on {symbol}. Nice work — review what worked.",
    "large_loss": "Large loss alert: {pnl} on {symbol}. I recommend reviewing the setup and risk rules.",
    "broker_disconnected": "Broker connection lost ({broker}). Reconnect to resume live execution monitoring.",
    "broker_connected": "Broker connected: {broker}. Account monitoring is active.",
    "strategy_disabled": "Strategy {strategy} was disabled.",
    "strategy_promoted": "Strategy {strategy} was promoted to {stage}.",
    "strategy_incubation_completed": "Strategy {strategy} completed incubation — validation threshold reached.",
    "market_news_updated": "Market news updated for {market}: {headline}",
    "high_impact_event": "High-impact event: {headline} — may affect {market}.",
    "risk_warning": "Risk warning: {message}",
    "api_failure": "API issue detected: {service} — {message}",
    "top_trade_changed": "Top Trade rotated to {market}: {signal} ({confidence}% confidence).",
    "alert_triggered": "Alert triggered: {title}",
}

_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=500)
_seen_signatures: dict[str, float] = {}
_DEDUP_TTL = 120  # seconds


def _signature(event_type: str, payload: dict[str, Any]) -> str:
    key_fields = payload.get("market") or payload.get("symbol") or payload.get("strategy") or payload.get("headline") or ""
    return f"{event_type}:{key_fields}:{payload.get('timestamp', '')}"


def ingest_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    source: str = "frontend",
    user_id: str | None = None,
) -> dict[str, Any] | None:
    """Ingest an event. Returns the event record or None if deduplicated."""
    if event_type not in EVENT_TYPES:
        event_type = "risk_warning" if "warning" in event_type else event_type

    payload = dict(payload or {})
    sig = _signature(event_type, payload)
    now = time.time()

    with _lock:
        last = _seen_signatures.get(sig)
        if last and (now - last) < _DEDUP_TTL:
            return None
        _seen_signatures[sig] = now

        event = {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "payload": payload,
            "source": source,
            "user_id": user_id,
            "timestamp": payload.get("timestamp") or int(now * 1000),
            "created_at": now,
            "message": format_proactive_message(event_type, payload),
        }
        _events.appendleft(event)
        return event


def format_proactive_message(event_type: str, payload: dict[str, Any]) -> str:
    template = EVENT_TEMPLATES.get(event_type, "WickSense update: {message}")
    try:
        safe = {k: (v if v is not None else "") for k, v in payload.items()}
        safe.setdefault("message", payload.get("title") or payload.get("reason") or event_type)
        return template.format(**safe)
    except (KeyError, ValueError):
        return f"WickSense event ({event_type}): {payload}"


def get_recent_events(
    since: float | None = None,
    limit: int = 20,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    with _lock:
        items = list(_events)

    if since:
        items = [e for e in items if e.get("created_at", 0) > since]
    if user_id:
        items = [e for e in items if not e.get("user_id") or e.get("user_id") == user_id]

    return items[:limit]


def clear_events_older_than(max_age_seconds: float = 86400) -> int:
    cutoff = time.time() - max_age_seconds
    removed = 0
    with _lock:
        while _events and _events[-1].get("created_at", 0) < cutoff:
            _events.pop()
            removed += 1
    return removed
