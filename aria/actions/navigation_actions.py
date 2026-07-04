"""Navigation actions — routes, modals, shortcuts."""

from __future__ import annotations

from aria.actions._helpers import json_result
from aria.navigation import (
    SHORTCUT_ACTIONS,
    build_client_action,
    list_modals,
    list_routes,
    resolve_modal,
    resolve_route,
)
from aria.registry import ActionContext, ActionResult, registry


def _register_navigation_actions() -> None:
    r = registry

    r.register_action("list_routes", "List all WickSense pages ARIA can navigate to.", _list_routes, category="navigation", tags=["discovery"])
    r.register_action("list_modals", "List all dashboard modals/panels ARIA can open.", _list_modals, category="navigation", tags=["discovery"])
    r.register_action(
        "navigate_to_page", "Navigate to any WickSense route.", _navigate_to_page,
        category="navigation", properties={"destination": {"type": "string"}}, required=["destination"],
    )
    r.register_action(
        "navigate_to_route", "Navigate directly by route path.", _navigate_to_route,
        category="navigation", properties={"route": {"type": "string"}}, required=["route"],
    )
    r.register_action(
        "open_modal", "Open a dashboard modal/panel.", _open_modal,
        category="navigation", properties={"modal": {"type": "string"}}, required=["modal"],
    )

    for name, desc in (
        ("open_top_trade", "Focus the current Top Trade on the dashboard."),
        ("open_strategy_performance", "Open Strategy Performance / Strategy panel."),
        ("open_scanner", "Open the Market Scanner."),
        ("open_journal", "Open the Trade Journal."),
        ("open_diagnostics", "Open Dev Tools / Diagnostics."),
        ("open_settings", "Open Account Settings."),
    ):
        r.register_action(name, desc, _make_shortcut_handler(name), category="navigation")


def _list_routes(_ctx: ActionContext) -> ActionResult:
    return ActionResult(result=json_result(list_routes()))


def _list_modals(_ctx: ActionContext) -> ActionResult:
    return ActionResult(result=json_result(list_modals()))


def _navigate_to_page(ctx: ActionContext) -> ActionResult:
    nav = resolve_route(ctx.arguments.get("destination") or "")
    if not nav:
        return ActionResult(result=f"Could not resolve '{ctx.arguments.get('destination')}'. Use list_routes.")
    return ActionResult(
        result=f"Navigating to {nav['label']}.",
        client_actions=[build_client_action("navigate", route=nav["route"], label=nav["label"])],
    )


def _navigate_to_route(ctx: ActionContext) -> ActionResult:
    route = ctx.arguments.get("route") or ""
    nav = resolve_route(route)
    label = nav["label"] if nav else route
    return ActionResult(
        result=f"Navigating to {label}.",
        client_actions=[build_client_action("navigate", route=nav["route"] if nav else route, label=label)],
    )


def _open_modal(ctx: ActionContext) -> ActionResult:
    modal = resolve_modal(ctx.arguments.get("modal") or "")
    if not modal:
        return ActionResult(result=f"Unknown modal '{ctx.arguments.get('modal')}'. Use list_modals.")
    return ActionResult(
        result=f"Opening {modal['label']}.",
        client_actions=[build_client_action("open_modal", modal_id=modal["modal_id"], label=modal["label"])],
    )


def _make_shortcut_handler(shortcut_name: str):
    def handler(_ctx: ActionContext) -> ActionResult:
        action = SHORTCUT_ACTIONS.get(shortcut_name)
        if not action:
            return ActionResult(result=f"Unknown shortcut: {shortcut_name}")
        atype = action["type"]
        if atype == "navigate":
            return ActionResult(
                result=f"Navigating to {action['label']}.",
                client_actions=[build_client_action("navigate", route=action["route"], label=action["label"])],
            )
        if atype == "open_modal":
            return ActionResult(
                result=f"Opening {action['label']}.",
                client_actions=[build_client_action("open_modal", modal_id=action["modal_id"], label=action["label"])],
            )
        if atype == "focus_top_trade":
            return ActionResult(
                result="Focusing Top Trade on dashboard.",
                client_actions=[
                    build_client_action("navigate", route=action["route"], label=action["label"]),
                    build_client_action("focus_top_trade"),
                ],
            )
        return ActionResult(result="Action queued.", client_actions=[build_client_action(atype, **{k: v for k, v in action.items() if k != "type"})])
    return handler


_register_navigation_actions()
