"""Executive assistant / integration actions — permission-gated stubs."""

from __future__ import annotations

from aria.registry import ActionResult, registry


def _register_integration_actions() -> None:
    r = registry

    r.register_action(
        "execute_trade", "Execute trade via broker (requires execute_trades authorization).",
        _noop_gated, category="integration", permission="execute_trades",
        properties={
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": {"type": "number"},
            "order_type": {"type": "string", "enum": ["market", "limit"]},
        },
        required=["symbol", "side", "quantity"],
        expose_to_voice=False,
    )

    external = [
        ("send_email", "Send email (requires authorization).", {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, ["to", "subject", "body"], "external_actions"),
        ("create_calendar_event", "Create calendar event (requires authorization).", {"title": {"type": "string"}, "start_time": {"type": "string"}, "end_time": {"type": "string"}}, ["title", "start_time"], "external_actions"),
        ("create_task", "Create task (requires authorization).", {"title": {"type": "string"}, "due_date": {"type": "string"}, "notes": {"type": "string"}}, ["title"], "external_actions"),
        ("lookup_contact", "Look up contact (requires authorization).", {"name": {"type": "string"}}, ["name"], "external_actions"),
        ("initiate_phone_call", "Initiate phone call (requires authorization).", {"contact_name": {"type": "string"}, "phone_number": {"type": "string"}}, [], "external_actions"),
        ("send_sms", "Send SMS (requires authorization).", {"to": {"type": "string"}, "message": {"type": "string"}}, ["to", "message"], "external_actions"),
        ("create_zoom_meeting", "Create Zoom meeting (requires authorization).", {"topic": {"type": "string"}, "start_time": {"type": "string"}}, ["topic"], "external_actions"),
        ("send_notification", "Send push/in-app notification (requires authorization).", {"title": {"type": "string"}, "message": {"type": "string"}}, ["title", "message"], "send_notifications"),
    ]

    for name, desc, props, required, perm in external:
        r.register_action(
            name, desc, _noop_gated,
            category="integration",
            permission=perm,
            properties=props,
            required=required,
            expose_to_voice=False,
        )


def _noop_gated(_ctx) -> ActionResult:
    """Handler body runs only after dispatcher authorization gate."""
    return ActionResult(result="Handled by dispatcher authorization layer.")


_register_integration_actions()
