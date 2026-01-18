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
    """HTML formatting for Telegram (4096 char limit).

    Uses HTML mode for reliable formatting:
    - <b>bold</b>, <i>italic</i>, <code>code</code>, <pre>block</pre>
    - Converts agent markdown to HTML
    - Simple escaping (only <, >, &)
    """

    platform = "telegram"
    max_length = 4096

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _markdown_to_html(self, text: str) -> str:
        """Convert common markdown patterns to Telegram HTML.

        Handles:
        - **bold** or __bold__ → <b>bold</b>
        - *italic* or _italic_ → <i>italic</i>
        - `code` → <code>code</code>
        - ```code block``` → <pre>code block</pre>
        - [text](url) → <a href="url">text</a>
        - Markdown tables → formatted list
        """
        # First convert markdown tables to readable format (uses placeholder for bold)
        text = self._convert_markdown_table(text)

        # Escape HTML in the raw text
        text = self._escape_html(text)

        # Convert table bold placeholders to actual HTML (after escaping)
        text = text.replace("[[BOLD]]", "<b>").replace("[[/BOLD]]", "</b>")

        # Convert code blocks first (```...```)
        text = re.sub(
            r"```(\w*)\n?([\s\S]*?)```",
            lambda m: f"<pre>{m.group(2).strip()}</pre>",
            text,
        )

        # Convert inline code (`...`)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

        # Convert bold (**text** or __text__)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

        # Convert italic (*text* or _text_) - but not inside words
        # Use negative lookbehind/ahead to avoid matching underscores in words
        text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
        text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

        # Convert links [text](url)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

        # Convert bullet points for cleaner display
        text = re.sub(r"^[-*•] ", "• ", text, flags=re.MULTILINE)

        return text

    def _convert_markdown_table(self, text: str) -> str:
        """Convert markdown tables to a readable list format for Telegram.

        Converts:
        | Header1 | Header2 |
        |---------|---------|
        | Value1  | Value2  |

        To:
        📋 Header1: Value1
           Header2: Value2
        """
        lines = text.split("\n")
        result = []
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Detect table header row (starts and ends with |)
            if line.startswith("|") and line.endswith("|"):
                # Parse header
                headers = [h.strip() for h in line.strip("|").split("|")]

                # Check if next line is separator (|---|---|)
                if i + 1 < len(lines) and re.match(r"^\|[-:\s|]+\|$", lines[i + 1].strip()):
                    i += 2  # Skip header and separator

                    # Process data rows
                    while i < len(lines):
                        row = lines[i].strip()
                        if row.startswith("|") and row.endswith("|"):
                            values = [v.strip() for v in row.strip("|").split("|")]

                            # Format as compact entry
                            if len(values) >= 2 and len(headers) >= 2:
                                # Use first column as identifier with placeholder for bold
                                entry_parts = [f"📋 [[BOLD]]{values[0]}[[/BOLD]]"]
                                for j, (header, value) in enumerate(zip(headers[1:], values[1:])):
                                    if value and value != "-":
                                        entry_parts.append(f"   {header}: {value}")
                                result.append("\n".join(entry_parts))
                            i += 1
                        else:
                            break
                    continue

            result.append(lines[i])
            i += 1

        return "\n".join(result)

    def format_text(self, text: str, compact: bool = False) -> FormattedMessage:
        """Format plain text for Telegram using HTML."""
        if compact:
            # Remove extra whitespace
            text = re.sub(r"\n{3,}", "\n\n", text)

        text, truncated = self.truncate(text)
        html = self._markdown_to_html(text)

        return FormattedMessage(
            content=html,
            platform=self.platform,
            truncated=truncated,
            original_length=len(text),
        )

    def format_error(self, error: str) -> FormattedMessage:
        """Format an error message with warning emoji."""
        escaped = self._escape_html(error)
        formatted = f"⚠️ <b>Error:</b> {escaped}"
        return FormattedMessage(
            content=formatted,
            platform=self.platform,
            truncated=False,
            original_length=len(formatted),
        )

    def format_tool_result(self, tool_name: str, result: dict[str, Any]) -> FormattedMessage:
        """Format tool result compactly - summarize instead of full JSON."""
        summary = self._summarize_tool_result(tool_name, result)
        escaped_name = self._escape_html(tool_name)
        escaped_summary = self._escape_html(summary)
        formatted = f"<b>{escaped_name}:</b> {escaped_summary}"

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
        parts = [f"🤖 <b>{self._escape_html(agent_id)}</b>"]

        if tool_calls:
            tool_names = [self._escape_html(tc.get("name", "unknown")) for tc in tool_calls]
            parts.append(f"<i>🔧 Used: {', '.join(tool_names)}</i>")

        parts.append("")
        parts.append(self._markdown_to_html(response))

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
