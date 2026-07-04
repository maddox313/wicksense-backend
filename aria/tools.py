"""Backward-compatible facade — all logic lives in registry + dispatcher."""

from __future__ import annotations

from typing import Any

from aria.dispatcher import dispatch_action, get_registry_catalog, list_tools

# Legacy alias
execute_tool = dispatch_action


def list_tool_catalog() -> dict[str, Any]:
    return get_registry_catalog()
