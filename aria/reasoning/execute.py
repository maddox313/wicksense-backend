"""Reasoning-wrapped action execution for direct tool/voice calls."""

from __future__ import annotations

from typing import Any

from aria.reasoning.agent import create_reasoning_agent


def execute_with_reasoning(
    action_name: str,
    arguments: dict[str, Any] | None,
    context: dict[str, Any] | None,
    permissions: dict[str, Any] | None,
    *,
    user_message: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Run a single action through Observe → Recall → Plan → Execute → Verify → Learn.
    Used by /aria/actions/execute and voice clientTools.
    """
    agent = create_reasoning_agent()
    msg = user_message or f"Execute action: {action_name}"

    reasoning_prompt, trace = agent.prepare_turn(msg, history, context)

    result = agent.execute_action(action_name, arguments, context, permissions)

    learnings = agent.finalize_turn(
        msg,
        result.get("result") or "",
        [{"name": action_name, "input": arguments, "result": result.get("result")}],
        context,
    )

    return {
        **result,
        "reasoning": trace.to_dict(),
        "learnings": learnings,
        "reasoning_prompt_applied": bool(reasoning_prompt),
    }
