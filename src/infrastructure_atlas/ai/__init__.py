"""AI Chat Agent System for Infrastructure Atlas.

This module provides a modular, multi-provider AI chat system with:
- Support for Azure OpenAI, OpenAI, Anthropic, OpenRouter, Gemini, and more
- Per-agent model/provider configuration
- Tool calling integration with Atlas functions
- Slash commands for quick actions
- Chat history persistence
- Admin console for configuration and testing

Example usage:
    from infrastructure_atlas.ai import create_chat_agent, ProviderType

    # Create an agent with Azure OpenAI
    agent = create_chat_agent(
        provider_type=ProviderType.AZURE_OPENAI,
        model="gpt-5-mini",
        tools_enabled=True,
    )

    # Send a message
    response = await agent.chat("Show me current Zabbix alerts")
    print(response.content)
"""

from __future__ import annotations

# Lazy imports to avoid circular dependencies and improve startup time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chat_agent import ChatAgent
    from .commands import CommandHandler
    from .models import (
        AgentConfig,
        ChatResponse,
        ProviderConfig,
        ToolCall,
        ToolResult,
    )
    from .models import (
        ChatMessage as AIChatMessage,
    )
    from .providers import (
        AIProvider,
        AnthropicProvider,
        AzureOpenAIProvider,
        GeminiProvider,
        OpenAIProvider,
        OpenRouterProvider,
        ProviderRegistry,
    )
    from .tools import ToolRegistry


def __getattr__(name: str):
    """Lazy import of submodules."""
    if name in (
        "AIProvider",
        "AzureOpenAIProvider",
        "OpenAIProvider",
        "AnthropicProvider",
        "OpenRouterProvider",
        "GeminiProvider",
        "ProviderRegistry",
        "get_provider",
    ):
        from . import providers

        return getattr(providers, name)

    if name in (
        "AIChatMessage",
        "ChatResponse",
        "ToolCall",
        "ToolResult",
        "AgentConfig",
        "ProviderConfig",
        "ProviderType",
        "MessageRole",
        "TokenUsage",
    ):
        from . import models

        if name == "AIChatMessage":
            return models.ChatMessage
        return getattr(models, name)

    if name in ("ChatAgent", "create_chat_agent"):
        from . import chat_agent

        return getattr(chat_agent, name)

    if name in ("ToolRegistry", "get_tool_registry"):
        from . import tools

        return getattr(tools, name)

    if name in ("CommandHandler", "get_command_handler"):
        from . import commands

        return getattr(commands, name)

    if name == "get_ai_admin_service":
        from . import admin

        return admin.get_ai_admin_service

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Providers
    "AIProvider",
    "AzureOpenAIProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OpenRouterProvider",
    "GeminiProvider",
    "ProviderRegistry",
    "get_provider",
    # Models
    "AIChatMessage",
    "ChatResponse",
    "ToolCall",
    "ToolResult",
    "AgentConfig",
    "ProviderConfig",
    "ProviderType",
    "MessageRole",
    "TokenUsage",
    # Chat Agent
    "ChatAgent",
    "create_chat_agent",
    # Tools
    "ToolRegistry",
    "get_tool_registry",
    # Commands
    "CommandHandler",
    "get_command_handler",
    # Admin
    "get_ai_admin_service",
]

