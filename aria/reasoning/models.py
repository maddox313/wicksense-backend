"""Data models for the ARIA reasoning cycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Observation:
    """OBSERVE — what ARIA sees right now."""

    user_message: str
    active_market: str | None
    active_signal: str | None
    open_trades_count: int
    risk_warning_count: int
    history_tail: list[dict[str, str]]
    intent_hints: list[str] = field(default_factory=list)
    raw_context_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_message": self.user_message,
            "active_market": self.active_market,
            "active_signal": self.active_signal,
            "open_trades_count": self.open_trades_count,
            "risk_warning_count": self.risk_warning_count,
            "intent_hints": self.intent_hints,
        }


@dataclass
class MemoryItem:
    """Single recalled memory fragment."""

    kind: str  # preference, conversation, project, routine, strategy, fact
    content: str
    relevance: float
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryRecall:
    """RECALL — relevant long-term memory for this turn."""

    items: list[MemoryItem] = field(default_factory=list)

    def to_prompt_section(self) -> str:
        if not self.items:
            return "LONG-TERM MEMORY: No strongly relevant memories for this turn."
        lines = ["LONG-TERM MEMORY (use to personalize — do not invent):"]
        for item in self.items[:8]:
            lines.append(f"- [{item.kind}|{item.relevance:.0%}] {item.content}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "kind": i.kind,
                    "content": i.content,
                    "relevance": i.relevance,
                    "source": i.source,
                    "metadata": i.metadata,
                }
                for i in self.items
            ]
        }


@dataclass
class ReasoningPlan:
    """PLAN — how ARIA should approach this request."""

    goal: str
    suggested_actions: list[str] = field(default_factory=list)
    reasoning_notes: str = ""
    personalization: str = ""

    def to_prompt_section(self) -> str:
        actions = ", ".join(self.suggested_actions) if self.suggested_actions else "Let conversation guide tool choice"
        parts = [
            "REASONING PLAN:",
            f"- Goal: {self.goal}",
            f"- Suggested tool sequence (if needed): {actions}",
        ]
        if self.personalization:
            parts.append(f"- Personalization: {self.personalization}")
        if self.reasoning_notes:
            parts.append(f"- Notes: {self.reasoning_notes}")
        parts.append(
            "- Always verify tool results before answering. Prefer read-only tools unless user authorized execution."
        )
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "suggested_actions": self.suggested_actions,
            "reasoning_notes": self.reasoning_notes,
            "personalization": self.personalization,
        }


@dataclass
class Verification:
    """VERIFY — did the action succeed and make sense?"""

    ok: bool
    notes: str = ""
    retry_recommended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "notes": self.notes,
            "retry_recommended": self.retry_recommended,
        }


@dataclass
class Learning:
    """LEARN — something worth remembering."""

    kind: str
    key: str
    value: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "value": self.value,
            "reason": self.reason,
        }


@dataclass
class ReasoningTrace:
    """Full trace of one reasoning cycle (for debugging/transparency)."""

    observe: dict[str, Any]
    recall: dict[str, Any]
    plan: dict[str, Any]
    executions: list[dict[str, Any]] = field(default_factory=list)
    verifications: list[dict[str, Any]] = field(default_factory=list)
    learnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observe": self.observe,
            "recall": self.recall,
            "plan": self.plan,
            "executions": self.executions,
            "verifications": self.verifications,
            "learnings": self.learnings,
        }
