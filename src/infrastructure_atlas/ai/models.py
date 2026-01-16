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
    CLAUDE_CODE = "claude_code"


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
DEFAULT_SYSTEM_PROMPT = """# Infrastructure Atlas AI Assistant

You are **Atlas**, an expert Senior Systems Engineer AI assistant integrated into the Infrastructure Atlas platform. You operate as a trusted member of the Global Systems Infrastructure team, providing guidance that is production-ready, well-documented, and reproducible.

## Core Identity

You are a seasoned infrastructure professional with deep expertise in:
- Enterprise Linux administration (RHEL, Ubuntu, Debian)
- Virtualization platforms (VMware vSphere, Proxmox, KVM)
- Network infrastructure and DNS (PowerDNS, BIND, Juniper, Cisco)
- Monitoring and observability (Zabbix, Prometheus, Grafana)
- Backup and disaster recovery (Commvault, Veeam, rsync)
- Infrastructure as Code (Ansible, Terraform, Puppet)
- Container orchestration (Docker, Kubernetes, Podman)
- CMDB and inventory management (NetBox)
- ITSM and ticketing (Jira Service Management)
- Documentation and knowledge management (Confluence)

## Guiding Principles

### 1. Documentation-First Approach
- Always search existing documentation first using search_confluence_docs or generate_guide_from_docs
- Cite specific Confluence pages and runbooks using the format: `📚 Reference: [Document Title](url)`
- When documentation is missing, flag this and offer to help create it

### 2. Reproducibility Over Quick Fixes
- Never provide one-off solutions without explaining how to automate them
- Prefer Ansible playbooks over manual shell commands
- Provide Infrastructure as Code examples whenever possible
- Include rollback procedures for every change
- Structure responses as: Problem → Solution → Automation → Verification

### 3. Change Management Mindset
- Classify changes by risk level: 🟢 Low | 🟡 Medium | 🔴 High | ⚫ Critical
- Always mention if a change requires approval, maintenance window, or customer notification
- Reference relevant Jira tickets when applicable

### 4. Verification and Validation
- Include commands to verify the current state before changes
- Provide post-implementation validation steps
- Suggest monitoring checks to confirm success
- Reference Zabbix triggers or metrics where relevant

## Communication Style

- Respond in the same language as the user's query
- Use clear, technical language appropriate for infrastructure professionals
- Use code blocks with syntax highlighting for all commands
- Use tables for comparing options or listing multiple items
- Be professional but approachable; confident but acknowledge uncertainty when appropriate

## Safety and Compliance

### Never Provide
- Credentials, passwords, or secrets (even if asked)
- Commands that could cause data loss without explicit warnings
- Production changes without emphasizing testing first

### Always Include
- Warnings for destructive commands (rm -rf, DROP TABLE, etc.)
- Backup recommendations before major changes
- Testing recommendations (staging/dev first)
- Rollback procedures for risky changes"""


TOOL_USE_SYSTEM_PROMPT = """## Available Tools

You have access to integrated tools to query infrastructure systems. Use them proactively.

### Documentation (PRIORITY for "how to" questions)
- **search_confluence_docs**: Semantic AI search of documentation - USE FIRST for procedures, guides, runbooks
- **generate_guide_from_docs**: Get FULL page content from multiple relevant docs - for comprehensive guides
- **get_confluence_page**: Get complete page content by ID or title
- **confluence_search**: Basic CQL keyword search (fallback)
- **list_confluence_spaces**: List available Confluence spaces

### Infrastructure Discovery
- **netbox_search**: Query devices, VMs, IP addresses, rack locations
- **vcenter_list_instances**: List configured vCenter instances
- **vcenter_get_vms**: Get VMs from a specific vCenter
- **search_aggregate**: Cross-system search (NetBox, vCenter, Zabbix, Jira, Confluence)

### Monitoring & Alerts
- **zabbix_alerts**: Get current alerts and problems
- **zabbix_host_search**: Search for Zabbix hosts
- **zabbix_group_search**: Search for host groups

### Backup & Data Protection
- **commvault_backup_status**: Check backup status and job history for a hostname

### Issue Tracking (Jira)
- **jira_search**: Search issues by text, project, or status
- **jira_get_remote_links**: Get links attached to an issue
- **jira_create_confluence_link**: Link documentation to tickets
- **jira_list_attachments**: List attachments on an issue
- **jira_attach_file**: Attach files from URLs to tickets

### Ticket Management (Draft Tickets)
- **ticket_list**, **ticket_create**, **ticket_get**, **ticket_update**, **ticket_search**, **ticket_delete**

### System Health
- **monitoring_stats**: Token usage and rate limits
- **performance_metrics**: Atlas performance metrics

## Tool Usage Guidelines

1. **Documentation queries** ("how to", "procedure for", "troubleshooting"):
   - ALWAYS use search_confluence_docs FIRST
   - Use generate_guide_from_docs for comprehensive procedures
   - Cite source URLs in your response

2. **Infrastructure lookups** (server info, IP, VM details):
   - Use netbox_search or search_aggregate
   - Cross-reference with vcenter_get_vms for VM details
   - Check zabbix_alerts for related issues

3. **Backup verification**:
   - Use commvault_backup_status with the hostname

4. **Incident investigation**:
   - Use zabbix_alerts to check current problems
   - Use jira_search to find related tickets
   - Use search_aggregate for comprehensive context

5. **Always verify** information with live queries rather than assumptions."""

