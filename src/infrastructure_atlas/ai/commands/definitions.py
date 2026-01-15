"""Slash command definitions for AI chat."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class CommandDefinition:
    """Definition of a slash command."""

    name: str
    description: str
    usage: str | None = None
    examples: list[str] | None = None
    handler: Callable[..., Any] | None = None
    aliases: list[str] | None = None


# Available commands
COMMANDS: list[CommandDefinition] = [
    CommandDefinition(
        name="help",
        description="Show available commands and how to use them",
        usage="/help [command]",
        examples=["/help", "/help tools"],
        aliases=["h", "?"],
    ),
    CommandDefinition(
        name="tools",
        description="List available tools that Atlas AI can use",
        usage="/tools [category]",
        examples=["/tools", "/tools monitoring", "/tools inventory"],
    ),
    CommandDefinition(
        name="models",
        description="List available AI models for the current provider",
        usage="/models [provider]",
        examples=["/models", "/models openai", "/models anthropic"],
    ),
    CommandDefinition(
        name="providers",
        description="List configured AI providers and their status",
        usage="/providers",
        examples=["/providers"],
    ),
    CommandDefinition(
        name="agent",
        description="Show or change current agent configuration",
        usage="/agent [set provider=... model=...]",
        examples=["/agent", "/agent set model=gpt-4o", "/agent set provider=anthropic model=claude-sonnet-4-5"],
    ),
    CommandDefinition(
        name="clear",
        description="Clear the current conversation history",
        usage="/clear",
        examples=["/clear"],
        aliases=["reset", "new"],
    ),
    CommandDefinition(
        name="history",
        description="Show conversation history summary",
        usage="/history [count]",
        examples=["/history", "/history 5"],
    ),
    CommandDefinition(
        name="usage",
        description="Show token usage statistics for this session",
        usage="/usage",
        examples=["/usage"],
        aliases=["tokens", "stats"],
    ),
    CommandDefinition(
        name="search",
        description="Quick search across all Atlas systems",
        usage="/search <query>",
        examples=["/search webserver01", "/search 10.0.0.1"],
    ),
    CommandDefinition(
        name="alerts",
        description="Show current Zabbix alerts",
        usage="/alerts [severity] [limit]",
        examples=["/alerts", "/alerts high", "/alerts disaster 10"],
    ),
    CommandDefinition(
        name="status",
        description="Show Atlas system status and health",
        usage="/status",
        examples=["/status"],
    ),
    CommandDefinition(
        name="export",
        description="Export conversation or data",
        usage="/export [format]",
        examples=["/export", "/export json", "/export markdown"],
    ),
    CommandDefinition(
        name="settings",
        description="View or modify chat settings",
        usage="/settings [key=value]",
        examples=["/settings", "/settings temperature=0.7", "/settings streaming=false"],
    ),
]


def get_command_by_name(name: str) -> CommandDefinition | None:
    """Get a command definition by name or alias."""
    name_lower = name.lower().lstrip("/")
    for cmd in COMMANDS:
        if cmd.name == name_lower:
            return cmd
        if cmd.aliases and name_lower in cmd.aliases:
            return cmd
    return None


def get_all_commands() -> list[CommandDefinition]:
    """Get all available commands."""
    return COMMANDS


def format_help_text() -> str:
    """Format help text for all commands."""
    lines = [
        "# Atlas AI Commands",
        "",
        "Use slash commands for quick actions. Type `/help <command>` for detailed help.",
        "",
    ]

    for cmd in COMMANDS:
        aliases = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
        lines.append(f"**/{cmd.name}**{aliases}")
        lines.append(f"  {cmd.description}")
        if cmd.usage:
            lines.append(f"  Usage: `{cmd.usage}`")
        lines.append("")

    return "\n".join(lines)


def format_command_help(cmd: CommandDefinition) -> str:
    """Format detailed help for a single command."""
    lines = [
        f"# /{cmd.name}",
        "",
        cmd.description,
        "",
    ]

    if cmd.aliases:
        lines.append(f"**Aliases:** {', '.join(f'/{a}' for a in cmd.aliases)}")
        lines.append("")

    if cmd.usage:
        lines.append(f"**Usage:** `{cmd.usage}`")
        lines.append("")

    if cmd.examples:
        lines.append("**Examples:**")
        for example in cmd.examples:
            lines.append(f"  - `{example}`")
        lines.append("")

    return "\n".join(lines)

