"""ARIA proactive intelligence event system — tenant-isolated in-memory bus.

Scope model:
  scope='user'   — requires authenticated user_id; never visible cross-tenant
  scope='global' — explicit allowlisted non-private platform events only

NULL user_id is never treated as global. Unknown scope fails closed.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any

log = logging.getLogger("wicksense.aria.events")

SCOPE_USER = "user"
SCOPE_GLOBAL = "global"
VALID_SCOPES = frozenset({SCOPE_USER, SCOPE_GLOBAL})

# Event types ARIA monitors
EVENT_TYPES = {
    "new_signal",
    "trade_opened",
    "trade_closed",
    "large_profit",
    "large_loss",
    "broker_disconnected",
    "broker_connected",
    "strategy_disabled",
    "strategy_promoted",
    "strategy_incubation_completed",
    "market_news_updated",
    "high_impact_event",
    "risk_warning",
    "api_failure",
    "top_trade_changed",
    "alert_triggered",
}

# Explicit global-safe allowlist (non-private platform information only).
GLOBAL_SAFE_EVENT_TYPES = frozenset({
    "market_news_updated",
    "high_impact_event",
    "api_failure",
})

# Default scope by type when caller omits scope.
DEFAULT_SCOPE_BY_TYPE: dict[str, str] = {
    "market_news_updated": SCOPE_GLOBAL,
    "high_impact_event": SCOPE_GLOBAL,
    "api_failure": SCOPE_GLOBAL,
}
for _t in EVENT_TYPES:
    DEFAULT_SCOPE_BY_TYPE.setdefault(_t, SCOPE_USER)

# Payload keys forbidden on global events (tenant-private / PII / trading).
GLOBAL_FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "user_id",
    "userid",
    "account_id",
    "accountid",
    "student_id",
    "studentid",
    "trainer_id",
    "trainerid",
    "balance",
    "pnl",
    "p_and_l",
    "equity",
    "broker",
    "broker_id",
    "alpaca",
    "trade_id",
    "paper_trade_id",
    "strategy_id",
    "strategy_config",
    "memory",
    "aria_memory",
    "conversation",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "authorization",
    "email",
    "phone",
})

# Natural-language templates for proactive notifications
EVENT_TEMPLATES: dict[str, str] = {
    "new_signal": "Based on WickSense data — new {signal} signal on {market} ({confidence}% confidence).",
    "trade_opened": "A trade was opened: {side} {symbol} via {strategy}.",
    "trade_closed": "Trade closed on {symbol}: {pnl} P&L.",
    "large_profit": "Large profit alert: +{pnl} on {symbol}. Nice work — review what worked.",
    "large_loss": "Large loss alert: {pnl} on {symbol}. I recommend reviewing the setup and risk rules.",
    "broker_disconnected": "Broker connection lost ({broker}). Reconnect to resume live execution monitoring.",
    "broker_connected": "Broker connected: {broker}. Account monitoring is active.",
    "strategy_disabled": "Strategy {strategy} was disabled.",
    "strategy_promoted": "Strategy {strategy} was promoted to {stage}.",
    "strategy_incubation_completed": "Strategy {strategy} completed incubation — validation threshold reached.",
    "market_news_updated": "Market news updated for {market}: {headline}",
    "high_impact_event": "High-impact event: {headline} — may affect {market}.",
    "risk_warning": "Risk warning: {message}",
    "api_failure": "API issue detected: {service} — {message}",
    "top_trade_changed": "Top Trade rotated to {market}: {signal} ({confidence}% confidence).",
    "alert_triggered": "Alert triggered: {title}",
}

_PER_USER_MAX = 200
_GLOBAL_MAX = 200
_DEDUP_TTL = 120  # seconds

_lock = threading.Lock()
_events_by_user: dict[str, deque] = defaultdict(lambda: deque(maxlen=_PER_USER_MAX))
_global_events: deque = deque(maxlen=_GLOBAL_MAX)
_seen_signatures: dict[str, float] = {}


class EventIngestRejected(ValueError):
    """Fail-closed ingest rejection (not a dedup)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _signature(event_type: str, payload: dict[str, Any], *, scope: str, user_id: str | None) -> str:
    key_fields = (
        payload.get("market")
        or payload.get("symbol")
        or payload.get("strategy")
        or payload.get("headline")
        or payload.get("service")
        or ""
    )
    owner = user_id or "*"
    return f"{scope}:{owner}:{event_type}:{key_fields}:{payload.get('timestamp', '')}"


def _normalize_event_type(event_type: str) -> str:
    if event_type in EVENT_TYPES:
        return event_type
    if "warning" in (event_type or ""):
        return "risk_warning"
    return event_type


def _payload_has_forbidden_global_keys(payload: dict[str, Any]) -> str | None:
    for key in payload.keys():
        lk = str(key).lower().replace("-", "_")
        if lk in GLOBAL_FORBIDDEN_PAYLOAD_KEYS:
            return lk
        if any(frag in lk for frag in ("user_id", "account", "pnl", "balance", "broker", "secret", "token")):
            return lk
    return None


def resolve_event_scope(
    event_type: str,
    *,
    scope: str | None = None,
) -> str:
    """Resolve and validate scope. Unknown scope fails closed."""
    if scope is None or scope == "":
        resolved = DEFAULT_SCOPE_BY_TYPE.get(event_type, SCOPE_USER)
    else:
        resolved = str(scope).strip().lower()
    if resolved not in VALID_SCOPES:
        raise EventIngestRejected("unknown_event_scope")
    if resolved == SCOPE_GLOBAL and event_type not in GLOBAL_SAFE_EVENT_TYPES:
        raise EventIngestRejected("global_event_type_not_allowlisted")
    return resolved


def ingest_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    source: str = "frontend",
    user_id: str | None = None,
    scope: str | None = None,
) -> dict[str, Any] | None:
    """
    Ingest an event.

    Returns the event record, or None if deduplicated.
    Raises EventIngestRejected on fail-closed validation errors.

    TENANT_EVENT_NULL_USER_ALLOWED = NO for scope=user.
    Global events must not carry private payload keys and must be allowlisted.
    Caller-supplied ownership is only accepted when scope=user and user_id is
    the server-authenticated identity (routes must pass JWT user, never trust body).
    """
    event_type = _normalize_event_type(str(event_type or "").strip())
    if event_type not in EVENT_TYPES:
        raise EventIngestRejected("unknown_event_type")

    resolved_scope = resolve_event_scope(event_type, scope=scope)
    payload = dict(payload or {})

    # Never trust payload user_id as ownership authority.
    payload.pop("user_id", None)
    payload.pop("userId", None)

    owner_id: str | None = None
    if resolved_scope == SCOPE_USER:
        if not user_id or not str(user_id).strip():
            raise EventIngestRejected("tenant_event_null_user_rejected")
        owner_id = str(user_id).strip()
    else:
        # Global: user_id must not establish a tenant owner; ignore if passed.
        owner_id = None
        forbidden = _payload_has_forbidden_global_keys(payload)
        if forbidden:
            raise EventIngestRejected(f"private_payload_on_global_event:{forbidden}")

    sig = _signature(event_type, payload, scope=resolved_scope, user_id=owner_id)
    now = time.time()

    with _lock:
        last = _seen_signatures.get(sig)
        if last and (now - last) < _DEDUP_TTL:
            return None
        _seen_signatures[sig] = now

        event = {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "scope": resolved_scope,
            "payload": payload,
            "source": source,
            "user_id": owner_id,
            "timestamp": payload.get("timestamp") or int(now * 1000),
            "created_at": now,
            "message": format_proactive_message(event_type, payload),
        }

        if resolved_scope == SCOPE_GLOBAL:
            _global_events.appendleft(event)
        else:
            _events_by_user[owner_id].appendleft(event)
        return event


def format_proactive_message(event_type: str, payload: dict[str, Any]) -> str:
    template = EVENT_TEMPLATES.get(event_type, "WickSense update: {message}")
    try:
        safe = {k: (v if v is not None else "") for k, v in payload.items()}
        safe.setdefault("message", payload.get("title") or payload.get("reason") or event_type)
        return template.format(**safe)
    except (KeyError, ValueError):
        return f"WickSense event ({event_type}): {payload}"


def get_recent_events(
    since: float | None = None,
    limit: int = 20,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return events visible to authenticated user_id only:
      - exact user-scoped events for that user
      - plus allowlisted global-safe events
    Never returns another tenant's events or NULL-owner tenant events.
    Requires authenticated user_id (fail closed).
    """
    if not user_id or not str(user_id).strip():
        raise EventIngestRejected("authenticated_user_id_required_for_event_read")
    uid = str(user_id).strip()
    limit = max(1, min(int(limit or 20), 100))

    with _lock:
        user_items = list(_events_by_user.get(uid, ()))
        global_items = list(_global_events)

    items = user_items + global_items
    # Exact tenant predicate — never include other users or null owners in user lane
    filtered: list[dict[str, Any]] = []
    for e in items:
        scope = e.get("scope")
        owner = e.get("user_id")
        if scope == SCOPE_GLOBAL:
            if e.get("type") not in GLOBAL_SAFE_EVENT_TYPES:
                continue
            if owner is not None:
                # Global events must not carry a tenant owner
                continue
            filtered.append(e)
            continue
        if scope == SCOPE_USER and owner is not None and str(owner) == uid:
            filtered.append(e)
            continue
        # Unknown scope / null owner tenant events: drop (fail closed on read)
        continue

    if since is not None:
        filtered = [e for e in filtered if e.get("created_at", 0) > since]

    filtered.sort(key=lambda e: e.get("created_at", 0), reverse=True)
    return filtered[:limit]


def clear_events_older_than(max_age_seconds: float = 86400) -> int:
    cutoff = time.time() - max_age_seconds
    removed = 0
    with _lock:
        for uid, q in list(_events_by_user.items()):
            keep = deque((e for e in q if e.get("created_at", 0) >= cutoff), maxlen=_PER_USER_MAX)
            removed += len(q) - len(keep)
            if keep:
                _events_by_user[uid] = keep
            else:
                _events_by_user.pop(uid, None)
        keep_g = deque((e for e in _global_events if e.get("created_at", 0) >= cutoff), maxlen=_GLOBAL_MAX)
        removed += len(_global_events) - len(keep_g)
        _global_events.clear()
        _global_events.extend(keep_g)
        # prune stale dedup signatures
        stale = [k for k, ts in _seen_signatures.items() if ts < cutoff]
        for k in stale:
            _seen_signatures.pop(k, None)
    return removed


def reset_event_bus_for_tests() -> None:
    """Test-only: wipe in-memory bus state."""
    with _lock:
        _events_by_user.clear()
        _global_events.clear()
        _seen_signatures.clear()
