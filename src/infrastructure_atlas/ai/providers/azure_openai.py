"""Azure OpenAI provider implementation."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from infrastructure_atlas.ai.models import (
    ChatMessage,
    ChatResponse,
    ProviderConfig,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from infrastructure_atlas.infrastructure.logging import get_logger

from .base import AIProvider, ProviderError, RateLimitError

logger = get_logger(__name__)


class AzureOpenAIProvider(AIProvider):
    """Azure OpenAI API provider.

    Supports Azure-hosted OpenAI models with tool calling and streaming.

    Configuration:
        - api_key: Azure OpenAI API key
        - azure_endpoint: Azure OpenAI endpoint URL (e.g., https://your-resource.openai.azure.com/)
        - azure_deployment: Deployment name for the model
        - api_version: API version (default: 2024-08-01-preview)
    """

    provider_name = "azure_openai"

    # Available Azure OpenAI models and their context windows
    MODELS = {
        "gpt-5.2": {"context_window": 500000, "max_output": 32768},
        "gpt-5-mini": {"context_window": 400000, "max_output": 32768},
        "gpt-5-nano": {"context_window": 200000, "max_output": 16384},
    }

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    def _validate_config(self) -> None:
        super()._validate_config()
        if not self.config.azure_endpoint:
            raise ProviderError("Azure endpoint is required", provider=self.provider_name)
        if not self.config.azure_deployment:
            raise ProviderError("Azure deployment name is required", provider=self.provider_name)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout))
        return self._client

    def _get_api_url(self, endpoint: str = "chat/completions") -> str:
        """Build API URL for Azure OpenAI."""
        base = self.config.azure_endpoint.rstrip("/")
        deployment = self.config.azure_deployment
        version = self.config.api_version
        return f"{base}/openai/deployments/{deployment}/{endpoint}?api-version={version}"

    def _get_headers(self) -> dict[str, str]:
        """Get request headers."""
        return {
            "api-key": self.config.api_key,
            "Content-Type": "application/json",
        }

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
        """Generate a chat completion using Azure OpenAI."""
        start_time = time.perf_counter()

        payload: dict[str, Any] = {
            "messages": self._format_messages(messages),
        }

        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        client = await self._get_client()
        url = self._get_api_url()

        logger.debug(
            "Azure OpenAI completion request",
            extra={
                "event": "azure_openai_request",
                "deployment": self.config.azure_deployment,
                "message_count": len(messages),
            },
        )

        try:
            response = await client.post(url, headers=self._get_headers(), json=payload)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                raise RateLimitError(
                    "Rate limit exceeded",
                    provider=self.provider_name,
                    retry_after=retry_after,
                )

            response.raise_for_status()
            data = response.json()

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Azure OpenAI API error: {e.response.text}",
                provider=self.provider_name,
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"Network error: {e!s}",
                provider=self.provider_name,
            ) from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Parse response
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls")

        # Parse usage
        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        logger.info(
            "Azure OpenAI completion completed",
            extra={
                "event": "azure_openai_response",
                "deployment": self.config.azure_deployment,
                "duration_ms": duration_ms,
                "total_tokens": usage.total_tokens,
            },
        )

        return ChatResponse(
            content=content,
            tool_calls=self._parse_tool_calls(raw_tool_calls),
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            model=self.config.azure_deployment,
            provider=self.provider_name,
            duration_ms=duration_ms,
        )

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
        """Generate a streaming chat completion."""
        payload: dict[str, Any] = {
            "messages": self._format_messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        client = await self._get_client()
        url = self._get_api_url()

        accumulated_tool_calls: dict[int, dict[str, Any]] = {}

        try:
            async with client.stream("POST", url, headers=self._get_headers(), json=payload) as response:
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        "Rate limit exceeded",
                        provider=self.provider_name,
                        retry_after=retry_after,
                    )

                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choice = (data.get("choices") or [{}])[0]
                    delta = choice.get("delta", {})

                    # Handle content
                    content = delta.get("content") or ""

                    # Handle tool calls
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": tc.get("id", ""),
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if "id" in tc:
                                accumulated_tool_calls[idx]["id"] = tc["id"]
                            if "function" in tc:
                                if "name" in tc["function"]:
                                    accumulated_tool_calls[idx]["function"]["name"] = tc["function"]["name"]
                                if "arguments" in tc["function"]:
                                    accumulated_tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]

                    # Handle usage (usually in the last chunk)
                    usage = None
                    if "usage" in data:
                        usage_data = data["usage"]
                        usage = TokenUsage(
                            prompt_tokens=usage_data.get("prompt_tokens", 0),
                            completion_tokens=usage_data.get("completion_tokens", 0),
                            total_tokens=usage_data.get("total_tokens", 0),
                        )

                    finish_reason = choice.get("finish_reason")
                    is_complete = finish_reason is not None

                    # Parse accumulated tool calls on completion
                    tool_calls = None
                    if is_complete and accumulated_tool_calls:
                        tool_calls = [ToolCall.from_api_response(tc) for tc in accumulated_tool_calls.values()]

                    yield StreamChunk(
                        content=content,
                        tool_calls=tool_calls if is_complete else None,
                        finish_reason=finish_reason,
                        is_complete=is_complete,
                        usage=usage,
                    )

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Azure OpenAI streaming error: {e.response.text}",
                provider=self.provider_name,
                status_code=e.response.status_code,
            ) from e

    async def test_connection(self) -> dict[str, Any]:
        """Test connection to Azure OpenAI."""
        try:
            # Make a simple completion request
            response = await self.complete(
                messages=[ChatMessage.user("Say 'hello' in one word.")],
                max_tokens=20,
            )
            return {
                "status": "connected",
                "provider": self.provider_name,
                "deployment": self.config.azure_deployment,
                "response_time_ms": response.duration_ms,
                "test_response": response.content[:100],
            }
        except Exception as e:
            return {
                "status": "error",
                "provider": self.provider_name,
                "deployment": self.config.azure_deployment,
                "error": str(e),
            }

    def list_models(self) -> list[dict[str, Any]]:
        """List available Azure OpenAI models."""
        return [
            {
                "id": model_id,
                "name": model_id,
                "context_window": info["context_window"],
                "max_output": info["max_output"],
                "provider": self.provider_name,
            }
            for model_id, info in self.MODELS.items()
        ]

    def _get_fallback_model(self) -> str:
        """Get fallback model."""
        return "gpt-5-mini"

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
