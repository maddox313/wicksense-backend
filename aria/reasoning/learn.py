"""LEARN — extract durable memories from interactions."""

from __future__ import annotations

import re
from typing import Any

from aria.reasoning.models import Learning, Observation

MARKET_PATTERN = re.compile(r"\b(gold|xau|nasdaq|qqq|forex|eur|natural gas|ng|dow|spy)\b", re.I)
STRATEGY_PATTERN = re.compile(r"\b(s\d{3}|strategy_\d+|hammer|s108|wick rejection)\b", re.I)


def extract_learnings_from_turn(
    observation: Observation,
    user_message: str,
    assistant_response: str,
    tool_calls: list[dict[str, Any]] | None,
) -> list[Learning]:
    learnings: list[Learning] = []
    msg = user_message or ""

    # Track frequently useful tool patterns
    for call in tool_calls or []:
        name = call.get("name")
        if name and call.get("result"):
            learnings.append(
                Learning(
                    kind="tool_pattern",
                    key=f"successful_{name}",
                    value={"action": name, "input": call.get("input")},
                    reason=f"Successful use of {name} this session",
                )
            )

    # Detect market interest
    for match in MARKET_PATTERN.finditer(msg):
        market = match.group(0)
        learnings.append(
            Learning(
                kind="preference",
                key="market_interest",
                value=market,
                reason="User mentioned market in query",
            )
        )

    # Detect strategy interest
    for match in STRATEGY_PATTERN.finditer(msg):
        strat = match.group(0)
        learnings.append(
            Learning(
                kind="preference",
                key="strategy_interest",
                value=strat,
                reason="User mentioned strategy in query",
            )
        )

    # Store episodic summary for notable exchanges
    if tool_calls and len(tool_calls) >= 2:
        learnings.append(
            Learning(
                kind="episodic",
                key="multi_tool_session",
                value={
                    "question": msg[:150],
                    "tools": [c.get("name") for c in tool_calls],
                    "answer_preview": (assistant_response or "")[:150],
                },
                reason="Multi-step tool session worth remembering",
            )
        )

    if observation.risk_warning_count > 0 and "risk" in msg.lower():
        learnings.append(
            Learning(
                kind="fact",
                key="risk_awareness",
                value={"warnings": observation.risk_warning_count, "market": observation.active_market},
                reason="User asked about risk while warnings active",
            )
        )

    # Deduplicate by key
    seen: set[str] = set()
    unique: list[Learning] = []
    for item in learnings:
        dedup = f"{item.kind}:{item.key}:{str(item.value)[:40]}"
        if dedup in seen:
            continue
        seen.add(dedup)
        unique.append(item)

    return unique[:8]
