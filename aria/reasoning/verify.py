"""VERIFY — validate action results before ARIA uses them."""

from __future__ import annotations

from typing import Any

from aria.reasoning.models import Verification

FAILURE_MARKERS = (
    "unknown action",
    "failed",
    "error:",
    "not configured",
    "not in live context",
    "requires explicit user authorization",
    "not yet integrated",
    "not yet connected",
)


def verify_action_result(action_name: str, result: dict[str, Any]) -> Verification:
    text = (result.get("result") or "").lower()

    if result.get("requires_authorization"):
        return Verification(
            ok=True,
            notes="Action blocked by safety gate — explain authorization requirement to user.",
        )

    if "unknown action" in text:
        return Verification(ok=False, notes="Action not found in registry.", retry_recommended=False)

    if any(marker in text for marker in FAILURE_MARKERS):
        return Verification(
            ok=False,
            notes=f"Action {action_name} returned a failure or empty signal.",
            retry_recommended=True,
        )

    if not text.strip():
        return Verification(ok=False, notes="Empty result.", retry_recommended=True)

    client_actions = result.get("client_actions") or []
    if client_actions:
        return Verification(ok=True, notes=f"Client actions queued: {[a.get('type') for a in client_actions]}")

    return Verification(ok=True, notes="Result looks usable.")
