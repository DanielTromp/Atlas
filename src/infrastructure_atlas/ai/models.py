"""Data models for the AI Chat system."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    """Role of a chat message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ProviderType(str, Enum):
    """Supported AI provider types."""

    AZURE_OPENAI = "azure_openai"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    GEMINI = "gemini"
    OLLAMA = "ollama"


@dataclass
class ProviderConfig:
    """Configuration for an AI provider."""

    provider_type: ProviderType
    api_key: str

    # Azure OpenAI specific
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    api_version: str = "2024-08-01-preview"

    # OpenRouter specific
    referer: str | None = None
    title: str = "Infrastructure Atlas"

    # Ollama specific
    base_url: str | None = None

    # Common settings
    default_model: str | None = None
    max_retries: int = 3
    timeout: int = 120

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "provider_type": self.provider_type.value,
            "api_key": "***",  # Mask API key
            "azure_endpoint": self.azure_endpoint,
            "azure_deployment": self.azure_deployment,
            "api_version": self.api_version,
            "referer": self.referer,
            "title": self.title,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
        }


@dataclass
class AgentConfig:
    """Configuration for a chat agent."""

    agent_id: str
    name: str
    provider_type: ProviderType
    model: str

    # Optional overrides
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    # Features
    tools_enabled: bool = True
    streaming_enabled: bool = True

    # Metadata
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "provider_type": self.provider_type.value,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "tools_enabled": self.tools_enabled,
            "streaming_enabled": self.streaming_enabled,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentConfig:
        """Create from dictionary."""
        return cls(
            agent_id=data["agent_id"],
            name=data["name"],
            provider_type=ProviderType(data["provider_type"]),
            model=data["model"],
            system_prompt=data.get("system_prompt"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            tools_enabled=data.get("tools_enabled", True),
            streaming_enabled=data.get("streaming_enabled", True),
            description=data.get("description"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(UTC),
        )


@dataclass
class ChatMessage:
    """A single chat message."""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        data: dict[str, Any] = {
            "role": self.role.value,
            "content": self.content,
        }
        if self.name:
            data["name"] = self.name
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return data

    @classmethod
    def system(cls, content: str) -> ChatMessage:
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> ChatMessage:
        """Create a user message."""
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str, tool_calls: list[ToolCall] | None = None) -> ChatMessage:
        """Create an assistant message."""
        return cls(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, content: str, tool_call_id: str, name: str | None = None) -> ChatMessage:
        """Create a tool result message."""
        return cls(role=MessageRole.TOOL, content=content, tool_call_id=tool_call_id, name=name)


@dataclass
class ToolCall:
    """A tool call requested by the AI."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments),
            },
        }

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> ToolCall:
        """Create from API response format."""
        function_data = data.get("function", {})
        arguments = function_data.get("arguments", "{}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        return cls(
            id=data.get("id", ""),
            name=function_data.get("name", ""),
            arguments=arguments,
        )


@dataclass
class ToolResult:
    """Result from executing a tool."""

    tool_call_id: str
    tool_name: str
    result: Any
    success: bool = True
    error: str | None = None
    duration_ms: int = 0

    def to_message(self) -> ChatMessage:
        """Convert to a tool message."""
        if self.success:
            content = json.dumps(self.result) if not isinstance(self.result, str) else self.result
        else:
            content = json.dumps({"error": self.error})
        return ChatMessage.tool(content=content, tool_call_id=self.tool_call_id, name=self.tool_name)


@dataclass
class TokenUsage:
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Add two token usages."""
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class ChatResponse:
    """Response from an AI chat completion."""

    content: str
    role: MessageRole = MessageRole.ASSISTANT
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    model: str | None = None
    provider: str | None = None
    duration_ms: int = 0

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return bool(self.tool_calls)

    def to_message(self) -> ChatMessage:
        """Convert to a ChatMessage."""
        return ChatMessage.assistant(content=self.content, tool_calls=self.tool_calls)


@dataclass
class StreamChunk:
    """A chunk from a streaming response."""

    content: str = ""
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    is_complete: bool = False
    usage: TokenUsage | None = None


# Default system prompts
DEFAULT_SYSTEM_PROMPT = """You are Atlas AI, an intelligent assistant for Infrastructure Atlas.
You help users manage and monitor their infrastructure across multiple systems including:
- NetBox (CMDB and inventory)
- Zabbix (monitoring and alerts)
- Jira (issue tracking)
- Confluence (documentation)
- vCenter (virtualization)
- Foreman (provisioning)
- Puppet (configuration management)

You have access to various tools to query these systems and perform actions.
Be concise, helpful, and accurate. When using tools, explain what you're doing.
If you're unsure about something, say so rather than guessing.

Use /help to see available commands."""

TOOL_USE_SYSTEM_PROMPT = """When responding to user queries:
1. Analyze what information is needed
2. Use available tools to gather accurate data
3. Present findings clearly and concisely
4. If multiple tools are needed, execute them efficiently
5. Always verify tool results before presenting to the user

Available tool categories:
- Search: NetBox, Zabbix, Jira, Confluence
- Monitoring: Zabbix alerts, vCenter VMs
- Documentation: Confluence pages
- Infrastructure: NetBox devices/VMs

Use tools proactively when the user's question involves infrastructure data."""

