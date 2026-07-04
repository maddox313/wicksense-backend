"""Executive assistant integration stubs — ready for future service connections."""

from __future__ import annotations

from typing import Any

# Tools that modify external systems — always require explicit authorization
EXTERNAL_ACTION_TOOLS = {
    "execute_trade",
    "send_email",
    "create_calendar_event",
    "create_task",
    "lookup_contact",
    "initiate_phone_call",
    "send_sms",
    "create_zoom_meeting",
    "send_push_notification",
    "send_notification",
}

INTEGRATION_STATUS = {
    "send_email": {"provider": "sendgrid", "status": "stub", "requires": "external_actions"},
    "create_calendar_event": {"provider": "google_calendar", "status": "stub", "requires": "external_actions"},
    "create_task": {"provider": "tasks_api", "status": "stub", "requires": "external_actions"},
    "lookup_contact": {"provider": "contacts_api", "status": "stub", "requires": "external_actions"},
    "initiate_phone_call": {"provider": "twilio_voice", "status": "stub", "requires": "external_actions"},
    "send_sms": {"provider": "twilio_sms", "status": "stub", "requires": "external_actions"},
    "create_zoom_meeting": {"provider": "zoom", "status": "stub", "requires": "external_actions"},
    "send_push_notification": {"provider": "wicksense_notifications", "status": "stub", "requires": "send_notifications"},
    "send_notification": {"provider": "wicksense_notifications", "status": "stub", "requires": "send_notifications"},
}


def requires_authorization(tool_name: str) -> str | None:
    """Return permission key required, or None if read-only."""
    if tool_name == "execute_trade":
        return "execute_trades"
    info = INTEGRATION_STATUS.get(tool_name)
    if info:
        return info.get("requires", "external_actions")
    return None


def check_permission(tool_name: str, permissions: dict[str, Any]) -> str | None:
    """Return error message if not authorized, else None."""
    key = requires_authorization(tool_name)
    if not key:
        return None
    if not permissions.get(key):
        labels = {
            "execute_trades": "trade execution",
            "external_actions": "external actions (email, phone, SMS, calendar, Zoom)",
            "send_notifications": "sending notifications on your behalf",
        }
        action = labels.get(key, key)
        return (
            f"{tool_name} requires explicit user authorization for {action}. "
            "ARIA can analyze and recommend, but cannot execute without confirmation."
        )
    return None


def execute_integration_stub(tool_name: str, arguments: dict[str, Any]) -> str:
    info = INTEGRATION_STATUS.get(tool_name, {})
    provider = info.get("provider", "unknown")
    return (
        f"{tool_name} is authorized but not yet connected to {provider}. "
        f"Payload received: {arguments}. "
        "The Executive Assistant framework is ready — connect the provider to enable this action."
    )
