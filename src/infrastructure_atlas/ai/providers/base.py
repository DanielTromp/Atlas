"""Base class for AI providers."""

from __future__ import annotations

import abc
from collections.abc import AsyncGenerator
from typing import Any

from infrastructure_atlas.ai.models import (
    ChatMessage,
    ChatResponse,
    ProviderConfig,
    StreamChunk,
    ToolCall,
)


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, message: str, provider: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class RateLimitError(ProviderError):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class AIProvider(abc.ABC):
    """Abstract base class for AI providers.

    All AI providers must implement this interface to ensure consistent
    behavior across different backends (Azure OpenAI, OpenAI, Anthropic, etc.)
    """

    provider_name: str = "base"

    def __init__(self, config: ProviderConfig):
        """Initialize the provider with configuration."""
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate provider configuration. Override in subclasses."""
        if not self.config.api_key:
            raise ProviderError(f"API key is required for {self.provider_name}", provider=self.provider_name)

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Generate a chat completion.

        Args:
            messages: List of chat messages
            model: Model to use (provider-specific)
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            tools: List of tool definitions
            tool_choice: Tool choice mode ("auto", "none", or specific tool)

        Returns:
            ChatResponse with the completion
        """
        pass

    @abc.abstractmethod
    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Generate a streaming chat completion.

        Args:
            messages: List of chat messages
            model: Model to use (provider-specific)
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            tools: List of tool definitions
            tool_choice: Tool choice mode

        Yields:
            StreamChunk objects with partial content
        """
        pass

    @abc.abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Test the provider connection and return status.

        Returns:
            Dict with connection status and info
        """
        pass

    @abc.abstractmethod
    def list_models(self) -> list[dict[str, Any]]:
        """List available models for this provider.

        Returns:
            List of model info dicts with id, name, context_window, etc.
        """
        pass

    def _format_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Format messages for the provider's API format.

        Override in subclasses if the provider uses a different format.
        """
        return [msg.to_dict() for msg in messages]

    def _parse_tool_calls(self, raw_tool_calls: list[dict[str, Any]] | None) -> list[ToolCall] | None:
        """Parse tool calls from API response."""
        if not raw_tool_calls:
            return None
        return [ToolCall.from_api_response(tc) for tc in raw_tool_calls]

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self.config.default_model or self._get_fallback_model()

    @abc.abstractmethod
    def _get_fallback_model(self) -> str:
        """Get the fallback model when none is configured."""
        pass

    def supports_tools(self) -> bool:
        """Check if this provider supports tool/function calling."""
        return True

    def supports_streaming(self) -> bool:
        """Check if this provider supports streaming."""
        return True

    def get_info(self) -> dict[str, Any]:
        """Get provider information."""
        return {
            "name": self.provider_name,
            "default_model": self.get_default_model(),
            "supports_tools": self.supports_tools(),
            "supports_streaming": self.supports_streaming(),
        }

