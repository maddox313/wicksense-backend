"""ARIA Executive v2 — server-side intelligence, action dispatcher, and reasoning layer."""

from aria.dispatcher import dispatch_action, get_registry_catalog, list_tools
from aria.reasoning.agent import ReasoningAgent, create_reasoning_agent
from aria.reasoning.execute import execute_with_reasoning
from aria.routes import register_aria_routes

__all__ = [
    "register_aria_routes",
    "dispatch_action",
    "get_registry_catalog",
    "list_tools",
    "ReasoningAgent",
    "create_reasoning_agent",
    "execute_with_reasoning",
]
