"""Hook WickSense backend state changes into ARIA proactive events."""

from __future__ import annotations

from typing import Any

from aria.events import ingest_event

NOTIFICATION_TYPE_MAP = {
    "live_signal_change": "new_signal",
    "live_top_trade_change": "top_trade_changed",
    "auto_trigger": "new_signal",
    "alert_triggered": "alert_triggered",
}


def hook_backend_notification(notification: dict[str, Any]) -> None:
    """Called when backend create_notification fires."""
    ntype = notification.get("type") or "alert_triggered"
    event_type = NOTIFICATION_TYPE_MAP.get(ntype, "alert_triggered")
    payload = {
        "title": notification.get("title"),
        "market": notification.get("market"),
        "signal": notification.get("signal"),
        "confidence": notification.get("confidence"),
        "setup_type": notification.get("setup_type"),
        "message": notification.get("title") or notification.get("message"),
        "timestamp": notification.get("created_at"),
    }
    ingest_event(event_type, payload, source="backend")


def hook_api_failure(service: str, message: str) -> None:
    ingest_event("api_failure", {"service": service, "message": message}, source="backend")


def hook_broker_status(connected: bool, broker: str = "") -> None:
    event_type = "broker_connected" if connected else "broker_disconnected"
    ingest_event(event_type, {"broker": broker or "unknown"}, source="backend")
