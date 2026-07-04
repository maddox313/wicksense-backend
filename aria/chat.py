"""ARIA chat orchestration — reasoning layer + Anthropic tool loop."""

from __future__ import annotations

import os
from typing import Any

import requests

from aria.dispatcher import list_tools
from aria.prompt import build_aria_system_prompt
from aria.reasoning.agent import create_reasoning_agent

ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = (os.environ.get("ARIA_MODEL") or "claude-sonnet-4-6").strip()
MAX_TOOL_ITERATIONS = 6


def _anthropic_headers() -> dict[str, str]:
    return {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _call_anthropic(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 600,
    temperature: float = 0.7,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    resp = requests.post(
        ANTHROPIC_API_URL,
        headers=_anthropic_headers(),
        json=payload,
        timeout=120,
    )
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = {"message": resp.text}
        raise RuntimeError(f"Anthropic API error {resp.status_code}: {detail}")

    return resp.json()


def _extract_text(content_blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in content_blocks or []:
        if block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "".join(parts).strip()


def run_aria_chat(
    message: str,
    history: list[dict[str, str]] | None,
    context: dict[str, Any] | None,
    permissions: dict[str, Any] | None,
    *,
    max_tokens: int = 600,
    temperature: float = 0.7,
) -> dict[str, Any]:
    """
    Run ARIA chat through the reasoning layer, then Anthropic tool-use loop.
    Cycle: Observe → Recall → Plan → Execute → Verify → Learn
    """
    if not ANTHROPIC_API_KEY or "your-" in ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured on backend")

    agent = create_reasoning_agent()

    # OBSERVE → RECALL → PLAN
    reasoning_prompt, trace = agent.prepare_turn(message, history, context)
    system = build_aria_system_prompt(context) + "\n" + reasoning_prompt

    messages: list[dict[str, Any]] = []
    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    client_actions: list[dict[str, Any]] = []
    tool_calls_made: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = _call_anthropic(
            messages,
            system,
            tools=list_tools(),
            max_tokens=max_tokens,
            temperature=temperature,
        )

        stop_reason = response.get("stop_reason")
        content_blocks = response.get("content") or []

        if stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": content_blocks})

            tool_results: list[dict[str, Any]] = []
            for block in content_blocks:
                if block.get("type") != "tool_use":
                    continue

                tool_name = block.get("name")
                tool_id = block.get("id")
                tool_input = block.get("input") or {}

                # EXECUTE → VERIFY (via reasoning agent → dispatcher)
                exec_result = agent.execute_action(
                    tool_name, tool_input, context, permissions
                )
                tool_calls_made.append(
                    {
                        "name": tool_name,
                        "input": tool_input,
                        "result": exec_result.get("result"),
                        "verification": exec_result.get("verification"),
                    }
                )
                client_actions.extend(exec_result.get("client_actions") or [])

                result_content = exec_result.get("result") or ""
                if exec_result.get("reasoning_hint"):
                    result_content += f"\n[Reasoning: {exec_result['reasoning_hint']}]"

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_content,
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            continue

        text = _extract_text(content_blocks)

        # LEARN
        learnings = agent.finalize_turn(message, text, tool_calls_made, context)

        return {
            "content": text or "I'm here to help with your WickSense trading intelligence.",
            "client_actions": client_actions,
            "tool_calls_made": tool_calls_made,
            "model": response.get("model") or DEFAULT_MODEL,
            "reasoning": trace.to_dict() if trace else {},
            "learnings": learnings,
        }

    learnings = agent.finalize_turn(message, "", tool_calls_made, context)

    return {
        "content": "I need a moment — please try your question again.",
        "client_actions": client_actions,
        "tool_calls_made": tool_calls_made,
        "model": DEFAULT_MODEL,
        "reasoning": trace.to_dict() if trace else {},
        "learnings": learnings,
    }
