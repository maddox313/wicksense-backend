"""Universal Action Dispatcher — single entry point for all ARIA tool execution."""

from __future__ import annotations

from typing import Any

from aria.integrations import execute_integration_stub
from aria.registry import ActionContext, ActionResult, registry


def ensure_actions_loaded() -> None:
    """Import action modules once so they self-register."""
    from aria.actions import load_all_actions  # noqa: WPS433

    load_all_actions()


def dispatch_action(
    action_name: str,
    arguments: dict[str, Any] | None,
    context: dict[str, Any] | None,
    permissions: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Execute a registered action by name.
    Core logic never branches on action names — the registry owns dispatch.
    """
    ensure_actions_loaded()

    definition = registry.get(action_name)
    if not definition:
        return ActionResult(result=f"Unknown action: {action_name}").to_dict()

    if definition.permission:
        key = definition.permission
        if not (permissions or {}).get(key):
            labels = {
                "execute_trades": "trade execution",
                "external_actions": "external actions (email, phone, SMS, calendar, Zoom)",
                "send_notifications": "sending notifications on your behalf",
            }
            action = labels.get(key, key)
            return ActionResult(
                result=(
                    f"{action_name} requires explicit user authorization for {action}. "
                    "ARIA can analyze and recommend, but cannot execute without confirmation."
                ),
                requires_authorization=True,
            ).to_dict()

        # Integration stubs after authorization (broker wiring comes later)
        if definition.category == "integration" and action_name != "execute_trade":
            return ActionResult(
                result=execute_integration_stub(action_name, arguments or {}),
            ).to_dict()

        if action_name == "execute_trade":
            args = arguments or {}
            return ActionResult(
                result=(
                    f"Trade execution authorized but broker routing not wired. "
                    f"Requested: {args.get('side')} {args.get('quantity')} {args.get('symbol')}. "
                    "Manual confirmation required."
                ),
            ).to_dict()

    ctx = ActionContext.from_payload(arguments, context, permissions)
    try:
        result = definition.handler(ctx)
        if not isinstance(result, ActionResult):
            result = ActionResult(result=str(result))
        return result.to_dict()
    except Exception as exc:
        return ActionResult(result=f"Action {action_name} failed: {exc}").to_dict()


def list_tools() -> list[dict[str, Any]]:
    ensure_actions_loaded()
    return registry.get_anthropic_tools()


def get_registry_catalog() -> dict[str, Any]:
    ensure_actions_loaded()
    return registry.get_catalog()
