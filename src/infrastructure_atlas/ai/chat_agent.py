"""Chat agent implementation with multi-provider support and tool calling."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from infrastructure_atlas.ai.models import (
    DEFAULT_SYSTEM_PROMPT,
    TOOL_USE_SYSTEM_PROMPT,
    AgentConfig,
    ChatMessage,
    ChatResponse,
    ProviderType,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from infrastructure_atlas.ai.providers import AIProvider, get_provider
from infrastructure_atlas.ai.tools import ToolRegistry, get_tool_registry
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ChatAgent:
    """AI chat agent with tool calling capabilities.

    Each agent can have its own provider/model configuration and maintains
    its own conversation history within a session.
    """

    def __init__(
        self,
        config: AgentConfig,
        provider: AIProvider | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self.config = config
        self._provider = provider
        self._tool_registry = tool_registry
        self._history: list[ChatMessage] = []
        self._total_usage = TokenUsage()

    @property
    def provider(self) -> AIProvider:
        """Get the AI provider for this agent."""
        if self._provider is None:
            self._provider = get_provider(self.config.provider_type.value)
        return self._provider

    @property
    def tool_registry(self) -> ToolRegistry:
        """Get the tool registry for this agent."""
        if self._tool_registry is None:
            self._tool_registry = get_tool_registry()
        return self._tool_registry

    def _get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        base_prompt = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        if self.config.tools_enabled:
            return f"{base_prompt}\n\n{TOOL_USE_SYSTEM_PROMPT}"
        return base_prompt

    def _build_messages(self, user_message: str) -> list[ChatMessage]:
        """Build the message list for a completion request."""
        messages = [ChatMessage.system(self._get_system_prompt())]
        messages.extend(self._history)
        messages.append(ChatMessage.user(user_message))
        return messages

    async def chat(
        self,
        message: str,
        *,
        max_tool_iterations: int = 5,
    ) -> ChatResponse:
        """Send a message and get a response, handling tool calls automatically.

        Args:
            message: User message
            max_tool_iterations: Maximum number of tool call iterations

        Returns:
            Final ChatResponse after processing all tool calls
        """
        logger.info(
            "Chat agent processing message",
            extra={
                "event": "chat_agent_message",
                "agent_id": self.config.agent_id,
                "provider": self.config.provider_type.value,
                "model": self.config.model,
            },
        )

        messages = self._build_messages(message)
        tools = self.tool_registry.get_tools() if self.config.tools_enabled else None

        # Add user message to history
        self._history.append(ChatMessage.user(message))

        iteration = 0
        total_usage = TokenUsage()

        while iteration < max_tool_iterations:
            iteration += 1

            # Get completion from provider
            response = await self.provider.complete(
                messages=messages,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                tools=tools,
                tool_choice="auto" if tools else None,
            )

            if response.usage:
                total_usage = total_usage + response.usage

            # If no tool calls, we're done
            if not response.has_tool_calls:
                # Add assistant response to history
                self._history.append(response.to_message())
                response.usage = total_usage
                self._total_usage = self._total_usage + total_usage
                return response

            # Process tool calls
            assistant_message = response.to_message()
            messages.append(assistant_message)
            self._history.append(assistant_message)

            for tool_call in response.tool_calls or []:
                logger.info(
                    "Executing tool call",
                    extra={
                        "event": "chat_agent_tool_call",
                        "agent_id": self.config.agent_id,
                        "tool_name": tool_call.name,
                    },
                )

                result = await self.tool_registry.execute(tool_call)
                tool_message = result.to_message()
                messages.append(tool_message)
                self._history.append(tool_message)

        # Max iterations reached, return last response
        logger.warning(
            "Max tool iterations reached",
            extra={
                "event": "chat_agent_max_iterations",
                "agent_id": self.config.agent_id,
                "iterations": max_tool_iterations,
            },
        )

        # Get final response without tools
        response = await self.provider.complete(
            messages=messages,
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        if response.usage:
            total_usage = total_usage + response.usage

        self._history.append(response.to_message())
        response.usage = total_usage
        self._total_usage = self._total_usage + total_usage

        return response

    async def stream_chat(
        self,
        message: str,
        *,
        max_tool_iterations: int = 5,
    ) -> AsyncGenerator[StreamChunk | ToolResult, None]:
        """Stream a chat response, handling tool calls.

        Yields:
            StreamChunk for text content
            ToolResult for tool execution results
        """
        if not self.config.streaming_enabled:
            # Fall back to non-streaming
            response = await self.chat(message, max_tool_iterations=max_tool_iterations)
            yield StreamChunk(
                content=response.content,
                finish_reason=response.finish_reason,
                is_complete=True,
                usage=response.usage,
            )
            return

        logger.info(
            "Chat agent streaming message",
            extra={
                "event": "chat_agent_stream",
                "agent_id": self.config.agent_id,
                "provider": self.config.provider_type.value,
                "model": self.config.model,
            },
        )

        messages = self._build_messages(message)
        tools = self.tool_registry.get_tools() if self.config.tools_enabled else None

        self._history.append(ChatMessage.user(message))

        iteration = 0
        total_usage = TokenUsage()
        accumulated_content = ""
        accumulated_tool_calls: list[ToolCall] = []

        while iteration < max_tool_iterations:
            iteration += 1
            accumulated_content = ""
            accumulated_tool_calls = []

            async for chunk in self.provider.stream(
                messages=messages,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                tools=tools,
                tool_choice="auto" if tools else None,
            ):
                accumulated_content += chunk.content

                if chunk.usage:
                    total_usage = total_usage + chunk.usage

                if chunk.tool_calls:
                    accumulated_tool_calls = chunk.tool_calls

                # Yield content chunks
                if chunk.content:
                    yield chunk

            # If no tool calls, we're done
            if not accumulated_tool_calls:
                self._history.append(ChatMessage.assistant(accumulated_content))
                yield StreamChunk(
                    content="",
                    finish_reason="stop",
                    is_complete=True,
                    usage=total_usage,
                )
                self._total_usage = self._total_usage + total_usage
                return

            # Process tool calls
            assistant_message = ChatMessage.assistant(accumulated_content, accumulated_tool_calls)
            messages.append(assistant_message)
            self._history.append(assistant_message)

            for tool_call in accumulated_tool_calls:
                logger.info(
                    "Executing tool call (streaming)",
                    extra={
                        "event": "chat_agent_stream_tool_call",
                        "agent_id": self.config.agent_id,
                        "tool_name": tool_call.name,
                    },
                )

                result = await self.tool_registry.execute(tool_call)
                tool_message = result.to_message()
                messages.append(tool_message)
                self._history.append(tool_message)

                # Yield tool result
                yield result

        # Max iterations - get final response
        accumulated_content = ""
        async for chunk in self.provider.stream(
            messages=messages,
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        ):
            accumulated_content += chunk.content
            if chunk.usage:
                total_usage = total_usage + chunk.usage
            if chunk.content:
                yield chunk

        self._history.append(ChatMessage.assistant(accumulated_content))
        yield StreamChunk(
            content="",
            finish_reason="stop",
            is_complete=True,
            usage=total_usage,
        )
        self._total_usage = self._total_usage + total_usage

    def clear_history(self) -> None:
        """Clear the conversation history."""
        self._history.clear()

    def get_history(self) -> list[ChatMessage]:
        """Get the conversation history."""
        return list(self._history)

    def set_history(self, messages: list[ChatMessage]) -> None:
        """Set the conversation history."""
        self._history = list(messages)

    def get_usage(self) -> TokenUsage:
        """Get total token usage for this agent."""
        return self._total_usage

    def get_info(self) -> dict[str, Any]:
        """Get agent information."""
        return {
            "agent_id": self.config.agent_id,
            "name": self.config.name,
            "provider": self.config.provider_type.value,
            "model": self.config.model,
            "tools_enabled": self.config.tools_enabled,
            "streaming_enabled": self.config.streaming_enabled,
            "history_length": len(self._history),
            "total_tokens": self._total_usage.total_tokens,
        }


def create_chat_agent(
    *,
    name: str = "Atlas AI",
    provider_type: ProviderType | str = ProviderType.AZURE_OPENAI,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools_enabled: bool = True,
    streaming_enabled: bool = True,
    api_base_url: str = "http://127.0.0.1:8000",
    api_token: str | None = None,
) -> ChatAgent:
    """Create a new chat agent with the specified configuration.

    Args:
        name: Agent name
        provider_type: AI provider to use
        model: Model name (provider-specific)
        system_prompt: Custom system prompt
        temperature: Sampling temperature
        max_tokens: Maximum tokens for response (default 4096)
        tools_enabled: Enable tool calling
        streaming_enabled: Enable streaming responses
        api_base_url: Atlas API base URL for tool execution
        api_token: Atlas API token for authentication

    Returns:
        Configured ChatAgent instance
    """
    if isinstance(provider_type, str):
        provider_type = ProviderType(provider_type)

    # Get default model for provider if not specified
    if model is None:
        provider = get_provider(provider_type.value)
        model = provider.get_default_model()

    config = AgentConfig(
        agent_id=f"agent_{uuid.uuid4().hex[:8]}",
        name=name,
        provider_type=provider_type,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens or 16384,  # Default to 16384 tokens
        tools_enabled=tools_enabled,
        streaming_enabled=streaming_enabled,
    )

    tool_registry = ToolRegistry(
        api_base_url=api_base_url,
        api_token=api_token,
    )

    return ChatAgent(config=config, tool_registry=tool_registry)
