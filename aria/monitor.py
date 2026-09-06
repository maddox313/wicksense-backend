"""Hook WickSense backend state changes into ARIA proactive events.

Emitter classification:
  hook_backend_notification → USER_SCOPED (requires notification.user_id)
  hook_broker_status        → USER_SCOPED (requires user_id)
  hook_api_failure          → GLOBAL_SAFE (allowlisted api_failure; no private payload)
"""

from __future__ import annotations

import logging
from typing import Any

from aria.events import EventIngestRejected, SCOPE_GLOBAL, SCOPE_USER, ingest_event

log = logging.getLogger("wicksense.aria.monitor")

NOTIFICATION_TYPE_MAP = {
    "live_signal_change": "new_signal",
    "live_top_trade_change": "top_trade_changed",
    "auto_trigger": "new_signal",
    "alert_triggered": "alert_triggered",
}


def hook_backend_notification(notification: dict[str, Any]) -> None:
    """USER_SCOPED — fail closed if notification lacks authenticated user_id."""
    ntype = notification.get("type") or "alert_triggered"
    event_type = NOTIFICATION_TYPE_MAP.get(ntype, "alert_triggered")
    user_id = notification.get("user_id") or notification.get("userId")
    payload = {
        "title": notification.get("title"),
        "market": notification.get("market"),
        "signal": notification.get("signal"),
        "confidence": notification.get("confidence"),
        "setup_type": notification.get("setup_type"),
        "message": notification.get("title") or notification.get("message"),
        "timestamp": notification.get("created_at"),
    }
    try:
        ingest_event(
            event_type,
            payload,
            source="backend",
            user_id=user_id,
            scope=SCOPE_USER,
        )
    except EventIngestRejected as exc:
        log.warning("[aria.monitor] USER_SCOPED notification rejected: %s", exc.reason)


def hook_api_failure(service: str, message: str) -> None:
    """GLOBAL_SAFE — platform service failure without tenant private fields."""
    try:
        ingest_event(
            "api_failure",
            {"service": service, "message": message},
            source="backend",
            scope=SCOPE_GLOBAL,
        )
    except EventIngestRejected as exc:
        log.warning("[aria.monitor] GLOBAL api_failure rejected: %s", exc.reason)


def hook_broker_status(connected: bool, broker: str = "", *, user_id: str | None = None) -> None:
    """USER_SCOPED — broker connectivity is tenant-private; requires user_id."""
    event_type = "broker_connected" if connected else "broker_disconnected"
    try:
        ingest_event(
            event_type,
            {"broker": broker or "unknown"},
            source="backend",
            user_id=user_id,
            scope=SCOPE_USER,
        )
    except EventIngestRejected as exc:
        log.warning("[aria.monitor] USER_SCOPED broker status rejected: %s", exc.reason)
