"""Universal Action Registry — single source of truth for all ARIA capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ActionContext:
    """Runtime context passed to every action handler."""

    arguments: dict[str, Any]
    state: dict[str, Any]
    news: dict[str, Any]
    preferences: dict[str, Any]
    permissions: dict[str, Any]

    @classmethod
    def from_payload(
        cls,
        arguments: dict[str, Any] | None,
        context: dict[str, Any] | None,
        permissions: dict[str, Any] | None,
    ) -> ActionContext:
        ctx = context or {}
        return cls(
            arguments=arguments or {},
            state=ctx.get("state") or {},
            news=ctx.get("news") or {},
            preferences=ctx.get("preferences") or {},
            permissions=permissions or {},
        )


@dataclass
class ActionResult:
    """Standard result from any registered action."""

    result: str
    client_actions: list[dict[str, Any]] = field(default_factory=list)
    requires_authorization: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "result": self.result,
            "client_actions": self.client_actions,
        }
        if self.requires_authorization:
            out["requires_authorization"] = True
        return out


ActionHandler = Callable[[ActionContext], ActionResult]


@dataclass
class ActionDefinition:
    """Metadata + handler for a single ARIA action."""

    name: str
    description: str
    handler: ActionHandler
    category: str = "platform"
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    permission: str | None = None
    expose_to_llm: bool = True
    expose_to_voice: bool = True
    tags: list[str] = field(default_factory=list)

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.properties,
                "required": self.required,
            },
        }

    def to_catalog_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "permission": self.permission,
            "expose_to_llm": self.expose_to_llm,
            "expose_to_voice": self.expose_to_voice,
            "tags": self.tags,
            "input_schema": {
                "type": "object",
                "properties": self.properties,
                "required": self.required,
            },
        }


class ActionRegistry:
    """Central registry — add capabilities by registration, never by editing core logic."""

    _instance: ActionRegistry | None = None

    def __init__(self) -> None:
        self._actions: dict[str, ActionDefinition] = {}

    @classmethod
    def instance(cls) -> ActionRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test helper — clear registry."""
        cls._instance = None

    def register(self, definition: ActionDefinition) -> ActionDefinition:
        if definition.name in self._actions:
            raise ValueError(f"Action already registered: {definition.name}")
        self._actions[definition.name] = definition
        return definition

    def register_action(
        self,
        name: str,
        description: str,
        handler: ActionHandler,
        *,
        category: str = "platform",
        properties: dict[str, Any] | None = None,
        required: list[str] | None = None,
        permission: str | None = None,
        expose_to_llm: bool = True,
        expose_to_voice: bool = True,
        tags: list[str] | None = None,
    ) -> ActionDefinition:
        """Convenience registrar — preferred API for new actions."""
        definition = ActionDefinition(
            name=name,
            description=description,
            handler=handler,
            category=category,
            properties=properties or {},
            required=required or [],
            permission=permission,
            expose_to_llm=expose_to_llm,
            expose_to_voice=expose_to_voice,
            tags=tags or [],
        )
        return self.register(definition)

    def get(self, name: str) -> ActionDefinition | None:
        return self._actions.get(name)

    def has(self, name: str) -> bool:
        return name in self._actions

    def list_names(self) -> list[str]:
        return sorted(self._actions.keys())

    def get_anthropic_tools(self) -> list[dict[str, Any]]:
        return [
            a.to_anthropic_schema()
            for a in self._actions.values()
            if a.expose_to_llm
        ]

    def get_catalog(self) -> dict[str, Any]:
        categories: dict[str, list[dict[str, Any]]] = {}
        actions = []
        for action in sorted(self._actions.values(), key=lambda a: a.name):
            entry = action.to_catalog_entry()
            actions.append(entry)
            categories.setdefault(action.category, []).append(entry["name"])
        return {
            "version": 1,
            "action_count": len(actions),
            "categories": categories,
            "actions": actions,
        }

    def get_voice_tool_names(self) -> list[str]:
        return sorted(
            a.name for a in self._actions.values() if a.expose_to_voice
        )


registry = ActionRegistry.instance()
