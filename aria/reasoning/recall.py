"""RECALL — search long-term memory for relevant context."""

from __future__ import annotations

import re
from typing import Any

from aria.reasoning.models import MemoryItem, MemoryRecall


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", (text or "").lower()) if len(t) > 2}


def _score(query_tokens: set[str], content: str, base: float = 0.3) -> float:
    if not content or not query_tokens:
        return 0.0
    content_tokens = _tokenize(content)
    if not content_tokens:
        return 0.0
    overlap = len(query_tokens & content_tokens)
    if overlap == 0:
        return 0.0
    return min(1.0, base + overlap / max(len(query_tokens), 1) * 0.5)


def recall_memories(
    user_message: str,
    context: dict[str, Any] | None,
    *,
    min_relevance: float = 0.35,
) -> MemoryRecall:
    ctx = context or {}
    memory = ctx.get("memory") or {}
    preferences = ctx.get("preferences") or memory.get("preferences") or {}
    query_tokens = _tokenize(user_message)

    # Boost tokens from active market/signal
    state = ctx.get("state") or {}
    if state.get("activeMarket"):
        query_tokens |= _tokenize(str(state.get("activeMarket")))
    if state.get("currentSignal"):
        query_tokens |= _tokenize(str(state.get("currentSignal")))

    candidates: list[MemoryItem] = []

    def add(kind: str, content: str, source: str, base: float = 0.35, metadata: dict | None = None):
        if not content:
            return
        score = _score(query_tokens, content, base)
        if score >= min_relevance:
            candidates.append(
                MemoryItem(
                    kind=kind,
                    content=content,
                    relevance=score,
                    source=source,
                    metadata=metadata or {},
                )
            )

    # Preferences
    for m in preferences.get("preferredMarkets") or []:
        add("preference", f"Preferred market: {m}", "preferences", 0.45)
    for s in preferences.get("favoriteStrategies") or []:
        add("strategy", f"Favorite strategy: {s}", "preferences", 0.5)
    add("preference", f"Risk tolerance: {preferences.get('riskTolerance')}", "preferences", 0.3)
    for tf in preferences.get("preferredTimeframes") or []:
        add("preference", f"Preferred timeframe: {tf}", "preferences", 0.4)

    # Routines & projects from extra
    extra = preferences.get("extra") or memory.get("extra") or {}
    for routine in extra.get("routines") or memory.get("routines") or []:
        label = routine if isinstance(routine, str) else routine.get("label") or str(routine)
        add("routine", f"Routine: {label}", "memory", 0.45, routine if isinstance(routine, dict) else {})
    for project in extra.get("projects") or memory.get("projects") or []:
        label = project if isinstance(project, str) else project.get("name") or str(project)
        add("project", f"Project: {label}", "memory", 0.45, project if isinstance(project, dict) else {})

    # Learned facts
    for fact in extra.get("learnedFacts") or memory.get("learnedFacts") or []:
        text = fact if isinstance(fact, str) else fact.get("text") or str(fact)
        add("fact", text, "learned", 0.4)

    # Frequently used commands — boost if similar to current message
    for cmd in preferences.get("frequentlyUsedCommands") or extra.get("frequentlyUsedCommands") or []:
        add("routine", f"Often asks: {cmd}", "usage", 0.55)

    # Recent conversations
    for conv in memory.get("recentConversations") or []:
        role = conv.get("role", "")
        content = (conv.get("content") or "")[:300]
        if content:
            add("conversation", f"{role}: {content}", "conversations", 0.38, {"role": role})

    # Episodic memories
    for ep in memory.get("episodicMemories") or []:
        text = ep if isinstance(ep, str) else ep.get("summary") or str(ep)
        add("fact", text, "episodic", 0.42)

    # Coaching notes from risk profile
    for note in memory.get("coachingNotes") or []:
        add("fact", f"Coaching note: {note}", "risk_profile", 0.4)

    trading_types = {
        "Trading Preference",
        "Learning",
        "Watch List",
        "Strategy Rule",
        "Decision",
    }
    persistent = memory.get("persistentMemories") or {}
    for row in persistent.get("recent") or []:
        if isinstance(row, str):
            add("fact", row, "persistent_recent", 0.4)
            continue
        if not isinstance(row, dict):
            continue
        mem_id = row.get("id")
        title = (row.get("title") or "").strip()
        body = (row.get("content") or "").strip()
        if not title and not body:
            continue
        memory_type = row.get("memoryType") or row.get("memory_type") or "Note"
        text = f"[{memory_type}] {title}: {body}".strip() if title else f"[{memory_type}] {body}".strip()
        if memory_type == "Project":
            kind = "project"
        elif memory_type == "Reminder":
            kind = "routine"
        elif memory_type in trading_types:
            kind = "strategy"
        else:
            kind = "fact"
        meta = {"id": mem_id} if mem_id else {}
        add(kind, text, "persistent_recent", 0.4, meta)

    candidates.sort(key=lambda x: x.relevance, reverse=True)
    seen_ids: set[str] = set()
    seen: set[str] = set()
    unique: list[MemoryItem] = []
    for item in candidates:
        mem_id = (item.metadata or {}).get("id")
        if mem_id:
            sid = str(mem_id)
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
        key = item.content[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return MemoryRecall(items=unique[:10])
