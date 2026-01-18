"""Platform-specific message formatters for bot responses.

Each platform has different constraints and capabilities:
- Telegram: 4096 char limit, Markdown v2, compact formatting
- Slack: 40000 char limit, Block Kit, rich formatting with sections
- Teams: 28000 char limit, Adaptive Cards, collapsible sections
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FormattedMessage:
    """Represents a formatted message ready for platform delivery."""

    content: Any  # Platform-specific content (str, dict, list)
    platform: str
    truncated: bool = False
    original_length: int = 0


class MessageFormatter(ABC):
    """Base class for platform-specific message formatting."""

    platform: str
    max_length: int

    @abstractmethod
    def format_text(self, text: str, compact: bool = False) -> FormattedMessage:
        """Format plain text for the platform."""

    @abstractmethod
    def format_error(self, error: str) -> FormattedMessage:
        """Format an error message."""

    @abstractmethod
    def format_tool_result(self, tool_name: str, result: dict[str, Any]) -> FormattedMessage:
        """Format a tool call result."""

    @abstractmethod
    def format_agent_response(self, agent_id: str, response: str, tool_calls: list[dict] | None = None) -> FormattedMessage:
        """Format a complete agent response, optionally with tool calls."""

    def truncate(self, text: str, max_length: int | None = None) -> tuple[str, bool]:
        """Truncate text to fit platform limit. Returns (text, was_truncated)."""
        limit = max_length or self.max_length
        if len(text) <= limit:
            return text, False
        # Leave room for truncation indicator
        truncated = text[: limit - 50] + "\n\n... [truncated]"
        return truncated, True


class TelegramFormatter(MessageFormatter):
    """Compact formatting for Telegram (4096 char limit).

    Uses MarkdownV2 with careful escaping.
    Optimizes for mobile viewing with compact bullet points.
    """

    platform = "telegram"
    max_length = 4096

    # Characters that need escaping in MarkdownV2
    ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!"

    def _escape_markdown(self, text: str) -> str:
        """Escape special characters for Telegram MarkdownV2."""
        # Don't escape inside code blocks
        parts = re.split(r"(```[\s\S]*?```|`[^`]+`)", text)
        result = []
        for i, part in enumerate(parts):
            if i % 2 == 0:  # Not a code block
                for char in self.ESCAPE_CHARS:
                    part = part.replace(char, f"\\{char}")
            result.append(part)
        return "".join(result)

    def format_text(self, text: str, compact: bool = False) -> FormattedMessage:
        """Format plain text for Telegram."""
        if compact:
            # Remove extra whitespace, compress lists
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = re.sub(r"^[-*] ", "- ", text, flags=re.MULTILINE)

        text, truncated = self.truncate(text)
        escaped = self._escape_markdown(text)

        return FormattedMessage(
            content=escaped,
            platform=self.platform,
            truncated=truncated,
            original_length=len(text),
        )

    def format_error(self, error: str) -> FormattedMessage:
        """Format an error message with warning emoji."""
        formatted = f"*Error:* {self._escape_markdown(error)}"
        return FormattedMessage(
            content=formatted,
            platform=self.platform,
            truncated=False,
            original_length=len(formatted),
        )

    def format_tool_result(self, tool_name: str, result: dict[str, Any]) -> FormattedMessage:
        """Format tool result compactly - summarize instead of full JSON."""
        # Summarize common tool results
        summary = self._summarize_tool_result(tool_name, result)
        formatted = f"*{self._escape_markdown(tool_name)}:* {self._escape_markdown(summary)}"

        formatted, truncated = self.truncate(formatted)
        return FormattedMessage(
            content=formatted,
            platform=self.platform,
            truncated=truncated,
            original_length=len(formatted),
        )

    def _summarize_tool_result(self, tool_name: str, result: dict[str, Any]) -> str:
        """Create a compact summary of tool results."""
        if "error" in result:
            return f"Error: {result['error']}"

        # Handle common patterns
        if "items" in result and isinstance(result["items"], list):
            count = len(result["items"])
            return f"Found {count} item(s)"

        if "count" in result:
            return f"Count: {result['count']}"

        if "status" in result:
            return f"Status: {result['status']}"

        # Generic summary - first few keys
        keys = list(result.keys())[:3]
        parts = []
        for key in keys:
            value = result[key]
            if isinstance(value, str) and len(value) < 50:
                parts.append(f"{key}: {value}")
            elif isinstance(value, (int, float, bool)):
                parts.append(f"{key}: {value}")
            elif isinstance(value, list):
                parts.append(f"{key}: {len(value)} items")
        return "; ".join(parts) if parts else "Completed"

    def format_agent_response(
        self, agent_id: str, response: str, tool_calls: list[dict] | None = None
    ) -> FormattedMessage:
        """Format agent response with optional tool call summary."""
        parts = [f"*{self._escape_markdown(agent_id)}*"]

        if tool_calls:
            # Escape tool names to avoid breaking markdown
            tool_names = [self._escape_markdown(tc.get("name", "unknown")) for tc in tool_calls]
            parts.append(f"_Used: {', '.join(tool_names)}_")

        parts.append("")
        parts.append(self._escape_markdown(response))

        content = "\n".join(parts)
        content, truncated = self.truncate(content)

        return FormattedMessage(
            content=content,
            platform=self.platform,
            truncated=truncated,
            original_length=len(content),
        )


class SlackFormatter(MessageFormatter):
    """Rich Block Kit formatting for Slack.

    Uses Slack's Block Kit for structured responses with:
    - Section blocks for text
    - Code blocks for JSON/code
    - Dividers between sections
    - Context blocks for metadata
    """

    platform = "slack"
    max_length = 40000

    def format_text(self, text: str, compact: bool = False) -> FormattedMessage:
        """Format plain text as Slack blocks."""
        text, truncated = self.truncate(text)

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ]

        return FormattedMessage(
            content={"blocks": blocks},
            platform=self.platform,
            truncated=truncated,
            original_length=len(text),
        )

    def format_error(self, error: str) -> FormattedMessage:
        """Format error with emoji and styling."""
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":warning: *Error*\n{error}"},
            }
        ]

        return FormattedMessage(
            content={"blocks": blocks},
            platform=self.platform,
            truncated=False,
            original_length=len(error),
        )

    def format_tool_result(self, tool_name: str, result: dict[str, Any]) -> FormattedMessage:
        """Format tool result with code block for JSON."""
        # Pretty print JSON
        json_str = json.dumps(result, indent=2, default=str)
        json_str, truncated = self.truncate(json_str, 3000)  # Smaller limit for code blocks

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":gear: *{tool_name}*"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{json_str}```"},
            },
        ]

        return FormattedMessage(
            content={"blocks": blocks},
            platform=self.platform,
            truncated=truncated,
            original_length=len(json_str),
        )

    def format_agent_response(
        self, agent_id: str, response: str, tool_calls: list[dict] | None = None
    ) -> FormattedMessage:
        """Format agent response with header and optional tool context."""
        blocks: list[dict[str, Any]] = []

        # Header with agent name
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Agent: {agent_id}", "emoji": True},
            }
        )

        # Tool calls context
        if tool_calls:
            tool_names = [tc.get("name", "unknown") for tc in tool_calls]
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":tools: Used: {', '.join(tool_names)}",
                        }
                    ],
                }
            )

        blocks.append({"type": "divider"})

        # Main response
        response, truncated = self.truncate(response)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": response},
            }
        )

        return FormattedMessage(
            content={"blocks": blocks},
            platform=self.platform,
            truncated=truncated,
            original_length=len(response),
        )


class TeamsFormatter(MessageFormatter):
    """Adaptive Cards formatting for Microsoft Teams.

    Uses Adaptive Cards JSON format for rich, interactive messages with:
    - TextBlock for text with various weights/sizes
    - FactSet for key-value pairs
    - Container for grouping with collapsible sections
    - ActionSet for buttons
    """

    platform = "teams"
    max_length = 28000

    def _create_card(self, body: list[dict[str, Any]], actions: list[dict] | None = None) -> dict[str, Any]:
        """Create an Adaptive Card wrapper."""
        card: dict[str, Any] = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": body,
        }
        if actions:
            card["actions"] = actions
        return card

    def format_text(self, text: str, compact: bool = False) -> FormattedMessage:
        """Format plain text as Adaptive Card."""
        text, truncated = self.truncate(text)

        body = [
            {
                "type": "TextBlock",
                "text": text,
                "wrap": True,
            }
        ]

        return FormattedMessage(
            content={"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": self._create_card(body)}]},
            platform=self.platform,
            truncated=truncated,
            original_length=len(text),
        )

    def format_error(self, error: str) -> FormattedMessage:
        """Format error with red styling."""
        body = [
            {
                "type": "TextBlock",
                "text": "Error",
                "weight": "Bolder",
                "color": "Attention",
            },
            {
                "type": "TextBlock",
                "text": error,
                "wrap": True,
                "color": "Attention",
            },
        ]

        return FormattedMessage(
            content={"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": self._create_card(body)}]},
            platform=self.platform,
            truncated=False,
            original_length=len(error),
        )

    def format_tool_result(self, tool_name: str, result: dict[str, Any]) -> FormattedMessage:
        """Format tool result with collapsible JSON."""
        json_str = json.dumps(result, indent=2, default=str)
        json_str, truncated = self.truncate(json_str, 3000)

        body = [
            {
                "type": "TextBlock",
                "text": f"Tool: {tool_name}",
                "weight": "Bolder",
            },
            {
                "type": "Container",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": f"```\n{json_str}\n```",
                        "wrap": True,
                        "fontType": "Monospace",
                    }
                ],
            },
        ]

        return FormattedMessage(
            content={"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": self._create_card(body)}]},
            platform=self.platform,
            truncated=truncated,
            original_length=len(json_str),
        )

    def format_agent_response(
        self, agent_id: str, response: str, tool_calls: list[dict] | None = None
    ) -> FormattedMessage:
        """Format agent response with header and collapsible tool section."""
        body: list[dict[str, Any]] = []

        # Header
        body.append(
            {
                "type": "TextBlock",
                "text": f"Agent: {agent_id}",
                "weight": "Bolder",
                "size": "Medium",
            }
        )

        # Tool calls in collapsible container
        if tool_calls:
            tool_names = [tc.get("name", "unknown") for tc in tool_calls]
            body.append(
                {
                    "type": "TextBlock",
                    "text": f"Tools used: {', '.join(tool_names)}",
                    "isSubtle": True,
                    "spacing": "None",
                }
            )

        # Separator
        body.append(
            {
                "type": "TextBlock",
                "text": "---",
                "spacing": "Medium",
            }
        )

        # Response
        response, truncated = self.truncate(response)
        body.append(
            {
                "type": "TextBlock",
                "text": response,
                "wrap": True,
            }
        )

        return FormattedMessage(
            content={"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": self._create_card(body)}]},
            platform=self.platform,
            truncated=truncated,
            original_length=len(response),
        )


@dataclass
class FormatterRegistry:
    """Registry for platform-specific message formatters."""

    _formatters: dict[str, MessageFormatter] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Register default formatters."""
        self.register(TelegramFormatter())
        self.register(SlackFormatter())
        self.register(TeamsFormatter())

    def register(self, formatter: MessageFormatter) -> None:
        """Register a formatter for a platform."""
        self._formatters[formatter.platform] = formatter

    def get(self, platform: str) -> MessageFormatter:
        """Get formatter for a platform. Raises KeyError if not found."""
        if platform not in self._formatters:
            raise KeyError(f"No formatter registered for platform: {platform}")
        return self._formatters[platform]

    def has(self, platform: str) -> bool:
        """Check if a formatter exists for the platform."""
        return platform in self._formatters

    @property
    def platforms(self) -> list[str]:
        """List all registered platforms."""
        return list(self._formatters.keys())
