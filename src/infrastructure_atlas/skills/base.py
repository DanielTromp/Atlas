"""Base skill class for the Atlas Agents Platform.

Skills are modular capabilities that agents can use to interact with
external systems. Each skill provides a set of actions that can be
converted to LangChain tools.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

from langchain_core.tools import StructuredTool

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SkillAction:
    """Definition of a single action within a skill.

    Actions are individual operations that a skill can perform,
    like "get_issue" or "search_tickets" for a Jira skill.
    """

    name: str
    description: str
    handler: Callable[..., Any]
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    is_destructive: bool = False
    requires_confirmation: bool = False

    def to_langchain_tool(self, skill_name: str) -> StructuredTool:
        """Convert this action to a LangChain StructuredTool.

        Args:
            skill_name: Name of the parent skill (for namespacing)

        Returns:
            StructuredTool instance
        """
        # Build args schema from handler signature if not provided
        args_schema = self.input_schema
        if args_schema is None:
            args_schema = _extract_schema_from_function(self.handler)

        return StructuredTool(
            name=f"{skill_name}_{self.name}",
            description=self._build_description(),
            func=self.handler,
            args_schema=args_schema if args_schema else None,
        )

    def _build_description(self) -> str:
        """Build a complete description including safety flags."""
        parts = [self.description]

        if self.is_destructive:
            parts.append("[DESTRUCTIVE: This action modifies data]")
        if self.requires_confirmation:
            parts.append("[REQUIRES CONFIRMATION]")

        return " ".join(parts)


@dataclass
class SkillConfig:
    """Configuration for a skill."""

    name: str
    category: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


class BaseSkill(ABC):
    """Abstract base class for skills.

    Skills provide modular capabilities to agents. Each skill:
    - Has a name and category
    - Contains one or more actions
    - Can be enabled/disabled
    - Can require approval for destructive actions

    Example usage:
        class JiraSkill(BaseSkill):
            name = "jira"
            category = "ticketing"
            description = "Jira ticket management"

            def __init__(self, config: SkillConfig):
                super().__init__(config)
                self._client = JiraClient(config.config)
                self.register_action(
                    name="get_issue",
                    func=self._get_issue,
                    description="Get Jira issue details",
                )

            def _get_issue(self, issue_key: str) -> dict:
                return self._client.get_issue(issue_key)
    """

    name: str = "base_skill"
    category: str = "general"
    description: str = "Base skill"

    def __init__(self, config: SkillConfig | None = None):
        self.config = config or SkillConfig(name=self.name, category=self.category)
        self._actions: dict[str, SkillAction] = {}
        self._initialized = False

    @property
    def is_enabled(self) -> bool:
        """Check if the skill is enabled."""
        return self.config.enabled

    def register_action(
        self,
        name: str,
        func: Callable[..., Any],
        description: str,
        is_destructive: bool = False,
        requires_confirmation: bool = False,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register an action with this skill.

        Args:
            name: Action name (will be prefixed with skill name)
            func: Handler function to execute
            description: Human-readable description
            is_destructive: Whether action modifies data
            requires_confirmation: Whether to require human confirmation
            input_schema: Optional JSON schema for input parameters
            output_schema: Optional JSON schema for output
        """
        action = SkillAction(
            name=name,
            description=description,
            handler=func,
            input_schema=input_schema,
            output_schema=output_schema,
            is_destructive=is_destructive,
            requires_confirmation=requires_confirmation,
        )
        self._actions[name] = action

        logger.debug(
            f"Registered action: {self.name}.{name}",
            extra={
                "skill": self.name,
                "action": name,
                "destructive": is_destructive,
            },
        )

    def execute(self, action_name: str, params: dict[str, Any]) -> Any:
        """Execute an action by name.

        Args:
            action_name: Name of the action to execute
            params: Parameters to pass to the action handler

        Returns:
            Result from the action handler

        Raises:
            ValueError: If action not found
            RuntimeError: If skill not enabled
        """
        if not self.is_enabled:
            raise RuntimeError(f"Skill '{self.name}' is not enabled")

        action = self._actions.get(action_name)
        if not action:
            raise ValueError(f"Action '{action_name}' not found in skill '{self.name}'")

        logger.info(
            f"Executing action: {self.name}.{action_name}",
            extra={
                "skill": self.name,
                "action": action_name,
                "params": params,
            },
        )

        return action.handler(**params)

    def get_actions(self) -> list[SkillAction]:
        """Get all registered actions.

        Returns:
            List of SkillAction instances
        """
        return list(self._actions.values())

    def get_langchain_tools(self) -> list[StructuredTool]:
        """Get all actions as LangChain tools.

        Returns:
            List of StructuredTool instances
        """
        return [action.to_langchain_tool(self.name) for action in self._actions.values()]

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the skill.

        This method should:
        - Set up any required clients/connections
        - Register all actions
        - Validate configuration

        Raises:
            Exception: If initialization fails
        """
        ...

    def cleanup(self) -> None:
        """Clean up skill resources.

        Override in subclasses if cleanup is needed.
        """
        pass

    def health_check(self) -> dict[str, Any]:
        """Check skill health.

        Override in subclasses for specific health checks.

        Returns:
            Dict with status and optional details
        """
        return {
            "status": "healthy" if self.is_enabled else "disabled",
            "skill": self.name,
            "actions": len(self._actions),
        }


def _extract_schema_from_function(func: Callable[..., Any]) -> dict[str, Any] | None:
    """Extract a JSON schema from a function's type hints.

    Args:
        func: Function to analyze

    Returns:
        JSON schema dict or None if extraction fails
    """
    try:
        sig = inspect.signature(func)
        hints = get_type_hints(func)

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = hints.get(param_name, str)
            json_type = _python_type_to_json(param_type)

            properties[param_name] = {"type": json_type}

            # Check if parameter has a default
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        if not properties:
            return None

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    except Exception:
        return None


def _python_type_to_json(py_type: type) -> str:
    """Convert a Python type to JSON schema type string."""
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    # Handle Optional types and other generics
    origin = getattr(py_type, "__origin__", None)
    if origin is not None:
        # Handle Optional (Union with None)
        args = getattr(py_type, "__args__", ())
        if type(None) in args:
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                return _python_type_to_json(non_none[0])

    return type_map.get(py_type, "string")
