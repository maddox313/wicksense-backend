"""Agent Memory & Reasoning Layer — Observe → Recall → Plan → Execute → Verify → Learn."""

from __future__ import annotations

from typing import Any

from aria.dispatcher import dispatch_action
from aria.reasoning.learn import extract_learnings_from_turn
from aria.reasoning.models import ReasoningTrace
from aria.reasoning.observe import observe
from aria.reasoning.plan import build_plan
from aria.reasoning.recall import recall_memories
from aria.reasoning.verify import verify_action_result


class ReasoningAgent:
    """
    Executive reasoning layer above the Universal Action Dispatcher.
    All tool decisions pass through this cycle; the dispatcher only executes.
    """

    def __init__(self) -> None:
        self._trace: ReasoningTrace | None = None

    @property
    def trace(self) -> ReasoningTrace | None:
        return self._trace

    def prepare_turn(
        self,
        message: str,
        history: list[dict[str, str]] | None,
        context: dict[str, Any] | None,
    ) -> tuple[str, ReasoningTrace]:
        """
        OBSERVE → RECALL → PLAN
        Returns augmented system prompt section + trace.
        """
        observation = observe(message, context, history)
        recall = recall_memories(message, context)
        plan = build_plan(observation, recall)

        reasoning_prompt = "\n\n".join(
            [
                "═" * 40,
                "ARIA EXECUTIVE REASONING LAYER",
                "Before any tool use: Observe → Recall → Plan → Execute → Verify → Learn.",
                recall.to_prompt_section(),
                plan.to_prompt_section(),
                "═" * 40,
            ]
        )

        self._trace = ReasoningTrace(
            observe=observation.to_dict(),
            recall=recall.to_dict(),
            plan=plan.to_dict(),
        )

        return reasoning_prompt, self._trace

    def execute_action(
        self,
        action_name: str,
        arguments: dict[str, Any] | None,
        context: dict[str, Any] | None,
        permissions: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        EXECUTE → VERIFY (+ partial LEARN on action level)
        Dispatches through the Universal Action Dispatcher, never bypasses it.
        """
        result = dispatch_action(action_name, arguments, context, permissions)
        verification = verify_action_result(action_name, result)

        if self._trace:
            self._trace.executions.append(
                {
                    "action": action_name,
                    "arguments": arguments or {},
                    "result_preview": (result.get("result") or "")[:300],
                }
            )
            self._trace.verifications.append(verification.to_dict())

        out = dict(result)
        out["verification"] = verification.to_dict()

        if not verification.ok and verification.retry_recommended:
            out["reasoning_hint"] = (
                f"Verification failed for {action_name}: {verification.notes}. "
                "Consider an alternate tool or ask the user for clarification."
            )

        return out

    def finalize_turn(
        self,
        observation_message: str,
        assistant_response: str,
        tool_calls: list[dict[str, Any]] | None,
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """LEARN — consolidate memories worth storing after the turn completes."""
        observation = observe(observation_message, context, None)
        learnings = extract_learnings_from_turn(
            observation,
            observation_message,
            assistant_response,
            tool_calls,
        )

        learning_dicts = [l.to_dict() for l in learnings]
        if self._trace:
            self._trace.learnings = learning_dicts

        return learning_dicts


# Module singleton — one agent instance per request scope is fine for stateless Flask
def create_reasoning_agent() -> ReasoningAgent:
    return ReasoningAgent()
