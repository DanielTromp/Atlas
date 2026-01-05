"""Command handler for slash commands in AI chat."""

from __future__ import annotations

import re
from typing import Any

from infrastructure_atlas.ai.providers import ProviderRegistry, get_provider_registry
from infrastructure_atlas.ai.tools import get_tool_registry
from infrastructure_atlas.infrastructure.logging import get_logger

from .definitions import (
    format_command_help,
    format_help_text,
    get_command_by_name,
)

logger = get_logger(__name__)


class CommandResult:
    """Result of executing a slash command."""

    def __init__(
        self,
        success: bool,
        message: str,
        data: dict[str, Any] | None = None,
        action: str | None = None,
    ):
        self.success = success
        self.message = message
        self.data = data or {}
        self.action = action  # Optional action hint (e.g., "clear_history", "switch_model")

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "action": self.action,
        }


class CommandHandler:
    """Handler for slash commands in AI chat.

    Parses and executes slash commands, returning structured results
    that can be displayed to the user or used to modify agent behavior.
    """

    def __init__(
        self,
        provider_registry: ProviderRegistry | None = None,
    ):
        self._provider_registry = provider_registry
        self._context: dict[str, Any] = {}  # Context for command execution

    @property
    def provider_registry(self) -> ProviderRegistry:
        if self._provider_registry is None:
            self._provider_registry = get_provider_registry()
        return self._provider_registry

    def set_context(self, **kwargs: Any) -> None:
        """Set context values for command execution."""
        self._context.update(kwargs)

    def is_command(self, message: str) -> bool:
        """Check if a message is a slash command."""
        return message.strip().startswith("/")

    def parse_command(self, message: str) -> tuple[str, list[str]]:
        """Parse a command message into command name and arguments."""
        parts = message.strip().split()
        command = parts[0].lstrip("/").lower()
        args = parts[1:] if len(parts) > 1 else []
        return command, args

    async def execute(self, message: str) -> CommandResult:
        """Execute a slash command and return the result."""
        if not self.is_command(message):
            return CommandResult(False, "Not a command")

        command, args = self.parse_command(message)

        logger.debug(
            "Executing command",
            extra={
                "event": "command_execute",
                "command": command,
                "args": args,
            },
        )

        # Route to handler
        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            # Check aliases
            cmd_def = get_command_by_name(command)
            if cmd_def:
                handler = getattr(self, f"_cmd_{cmd_def.name}", None)

        if handler is None:
            return CommandResult(
                False,
                f"Unknown command: /{command}\n\nType `/help` for available commands.",
            )

        try:
            return await handler(args)
        except Exception as e:
            logger.error(
                "Command execution failed",
                extra={
                    "event": "command_error",
                    "command": command,
                    "error": str(e),
                },
            )
            return CommandResult(False, f"Command failed: {e!s}")

    async def _cmd_help(self, args: list[str]) -> CommandResult:
        """Handle /help command."""
        if args:
            cmd_name = args[0].lstrip("/")
            cmd_def = get_command_by_name(cmd_name)
            if cmd_def:
                return CommandResult(True, format_command_help(cmd_def))
            return CommandResult(False, f"Unknown command: /{cmd_name}")

        return CommandResult(True, format_help_text())

    async def _cmd_tools(self, args: list[str]) -> CommandResult:
        """Handle /tools command."""
        tool_registry = get_tool_registry()
        tools = tool_registry.get_tool_info()

        # Filter by category if specified
        category = args[0].lower() if args else None
        if category:
            tools = [t for t in tools if t["category"] == category]
            if not tools:
                return CommandResult(
                    False,
                    f"No tools found in category '{category}'.\n\nAvailable categories: "
                    + ", ".join(sorted(set(t["category"] for t in tool_registry.get_tool_info()))),
                )

        # Format output
        lines = ["# Available Tools", ""]

        # Group by category
        by_category: dict[str, list[dict]] = {}
        for tool in tools:
            cat = tool["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(tool)

        for cat, cat_tools in sorted(by_category.items()):
            lines.append(f"## {cat.title()}")
            for tool in cat_tools:
                lines.append(f"- **{tool['name']}**: {tool['description']}")
            lines.append("")

        return CommandResult(True, "\n".join(lines), {"tools": tools})

    async def _cmd_models(self, args: list[str]) -> CommandResult:
        """Handle /models command."""
        provider_name = args[0].lower() if args else None

        if provider_name:
            try:
                provider = self.provider_registry.get_provider(provider_name)
                models = provider.list_models()
            except Exception as e:
                return CommandResult(False, f"Error getting models for {provider_name}: {e!s}")
        else:
            # Get current provider from context
            provider_name = self._context.get("provider", "azure_openai")
            try:
                provider = self.provider_registry.get_provider(provider_name)
                models = provider.list_models()
            except Exception:
                models = []

        if not models:
            return CommandResult(False, f"No models available for {provider_name}")

        lines = [f"# Models for {provider_name}", ""]
        for model in models:
            ctx_window = model.get("context_window", "N/A")
            max_out = model.get("max_output", "N/A")
            lines.append(f"- **{model['id']}**")
            lines.append(f"  Context: {ctx_window:,} tokens, Max output: {max_out:,} tokens")

        return CommandResult(True, "\n".join(lines), {"models": models})

    async def _cmd_providers(self, args: list[str]) -> CommandResult:
        """Handle /providers command."""
        providers = self.provider_registry.list_available()

        lines = ["# Configured Providers", ""]
        for p in providers:
            status = "✓ Active" if p["active"] else ("✓ Ready" if p["configured"] else "✗ Not configured")
            lines.append(f"- **{p['name']}**: {status}")

        lines.extend(
            [
                "",
                "Use `/agent set provider=<name>` to switch providers.",
            ]
        )

        return CommandResult(True, "\n".join(lines), {"providers": providers})

    async def _cmd_agent(self, args: list[str]) -> CommandResult:
        """Handle /agent command."""
        if not args:
            # Show current agent info
            agent_info = self._context.get("agent_info", {})
            if not agent_info:
                return CommandResult(True, "No agent information available.")

            lines = [
                "# Current Agent Configuration",
                "",
                f"- **Provider:** {agent_info.get('provider', 'N/A')}",
                f"- **Model:** {agent_info.get('model', 'N/A')}",
                f"- **Tools enabled:** {agent_info.get('tools_enabled', True)}",
                f"- **Streaming:** {agent_info.get('streaming_enabled', True)}",
                f"- **History messages:** {agent_info.get('history_length', 0)}",
                f"- **Total tokens used:** {agent_info.get('total_tokens', 0):,}",
            ]
            return CommandResult(True, "\n".join(lines), {"agent": agent_info})

        if args[0] == "set":
            # Parse settings
            settings: dict[str, Any] = {}
            for arg in args[1:]:
                if "=" in arg:
                    key, value = arg.split("=", 1)
                    settings[key.lower()] = value

            if not settings:
                return CommandResult(False, "No settings provided. Usage: `/agent set provider=... model=...`")

            return CommandResult(
                True,
                f"Agent settings updated: {settings}",
                {"settings": settings},
                action="update_agent",
            )

        return CommandResult(False, "Unknown agent command. Use `/agent` or `/agent set ...`")

    async def _cmd_clear(self, args: list[str]) -> CommandResult:
        """Handle /clear command."""
        return CommandResult(
            True,
            "Conversation history cleared.",
            action="clear_history",
        )

    async def _cmd_history(self, args: list[str]) -> CommandResult:
        """Handle /history command."""
        history = self._context.get("history", [])
        count = int(args[0]) if args and args[0].isdigit() else 10

        if not history:
            return CommandResult(True, "No conversation history.")

        recent = history[-count:] if len(history) > count else history

        lines = [f"# Conversation History (last {len(recent)} messages)", ""]
        for i, msg in enumerate(recent, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:100]
            if len(msg.get("content", "")) > 100:
                content += "..."
            lines.append(f"{i}. **{role}**: {content}")

        return CommandResult(
            True,
            "\n".join(lines),
            {"history_count": len(history), "shown": len(recent)},
        )

    async def _cmd_usage(self, args: list[str]) -> CommandResult:
        """Handle /usage command."""
        usage = self._context.get("usage", {})

        lines = [
            "# Token Usage Statistics",
            "",
            f"- **Prompt tokens:** {usage.get('prompt_tokens', 0):,}",
            f"- **Completion tokens:** {usage.get('completion_tokens', 0):,}",
            f"- **Total tokens:** {usage.get('total_tokens', 0):,}",
        ]

        return CommandResult(True, "\n".join(lines), {"usage": usage})

    async def _cmd_search(self, args: list[str]) -> CommandResult:
        """Handle /search command."""
        if not args:
            return CommandResult(False, "Please provide a search query. Usage: `/search <query>`")

        query = " ".join(args)
        return CommandResult(
            True,
            f"Searching for: {query}\n\n_Use the chat to ask questions about the results._",
            {"query": query},
            action="search",
        )

    async def _cmd_alerts(self, args: list[str]) -> CommandResult:
        """Handle /alerts command."""
        severity = None
        limit = 20

        for arg in args:
            if arg.isdigit():
                limit = int(arg)
            elif arg.lower() in ("disaster", "critical", "high", "5"):
                severity = "5"
            elif arg.lower() in ("average", "medium", "4"):
                severity = "4"
            elif arg.lower() in ("warning", "3"):
                severity = "3"
            elif arg.lower() in ("info", "information", "2"):
                severity = "2"

        return CommandResult(
            True,
            f"Fetching alerts (severity: {severity or 'all'}, limit: {limit})...",
            {"severity": severity, "limit": limit},
            action="get_alerts",
        )

    async def _cmd_status(self, args: list[str]) -> CommandResult:
        """Handle /status command."""
        return CommandResult(
            True,
            "Fetching Atlas system status...",
            action="get_status",
        )

    async def _cmd_export(self, args: list[str]) -> CommandResult:
        """Handle /export command."""
        format_type = args[0].lower() if args else "markdown"
        if format_type not in ("json", "markdown", "md", "text"):
            return CommandResult(False, f"Unknown format: {format_type}. Use: json, markdown, or text")

        return CommandResult(
            True,
            f"Exporting conversation as {format_type}...",
            {"format": format_type},
            action="export",
        )

    async def _cmd_settings(self, args: list[str]) -> CommandResult:
        """Handle /settings command."""
        if not args:
            # Show current settings
            settings = self._context.get("settings", {})
            lines = ["# Current Settings", ""]
            for key, value in settings.items():
                lines.append(f"- **{key}:** {value}")
            if not settings:
                lines.append("_No custom settings configured._")
            return CommandResult(True, "\n".join(lines), {"settings": settings})

        # Parse and apply settings
        updates: dict[str, Any] = {}
        for arg in args:
            if "=" in arg:
                key, value = arg.split("=", 1)
                # Type conversion
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif value.isdigit():
                    value = int(value)
                elif re.match(r"^\d+\.\d+$", value):
                    value = float(value)
                updates[key] = value

        if not updates:
            return CommandResult(False, "No settings to update. Usage: `/settings key=value`")

        return CommandResult(
            True,
            f"Settings updated: {updates}",
            {"updates": updates},
            action="update_settings",
        )


# Global handler instance
_global_handler: CommandHandler | None = None


def get_command_handler() -> CommandHandler:
    """Get the global command handler."""
    global _global_handler
    if _global_handler is None:
        _global_handler = CommandHandler()
    return _global_handler

