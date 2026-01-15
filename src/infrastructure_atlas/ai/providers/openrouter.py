"""OpenRouter provider implementation."""

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


class OpenRouterProvider(AIProvider):
    """OpenRouter API provider.

    OpenRouter provides access to multiple AI models through a unified API.

    Configuration:
        - api_key: OpenRouter API key
        - referer: HTTP Referer header (optional)
        - title: Application title for OpenRouter dashboard
        - default_model: Default model (e.g., openrouter/auto)
    """

    provider_name = "openrouter"
    BASE_URL = "https://openrouter.ai/api/v1"

    # Popular models available on OpenRouter
    MODELS = {
        # OpenAI models
        "openai/gpt-5": {"context_window": 500000, "max_output": 32768},
        "openai/gpt-5-mini": {"context_window": 400000, "max_output": 32768},
        "openai/gpt-5-nano": {"context_window": 200000, "max_output": 16384},
        # Anthropic models
        "anthropic/claude-opus-4.5": {"context_window": 200000, "max_output": 16384},
        "anthropic/claude-sonnet-4.5": {"context_window": 200000, "max_output": 16384},
        "anthropic/claude-haiku-4.5": {"context_window": 200000, "max_output": 16384},
        # Google models
        "google/gemini-3-pro": {"context_window": 2097152, "max_output": 16384},
        "google/gemini-3-flash": {"context_window": 1048576, "max_output": 16384},
        # X.AI models
        "x-ai/grok-4": {"context_window": 131072, "max_output": 16384},
        "x-ai/grok-4.1-fast": {"context_window": 131072, "max_output": 16384},
        # DeepSeek models
        "deepseek/deepseek-chat": {"context_window": 64000, "max_output": 8192},
        "deepseek/deepseek-reasoner": {"context_window": 64000, "max_output": 8192},
    }

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout))
        return self._client

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "X-Title": self.config.title or "Infrastructure Atlas",
        }
        if self.config.referer:
            headers["HTTP-Referer"] = self.config.referer
        return headers

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
        """Generate a chat completion using OpenRouter."""
        start_time = time.perf_counter()
        model = model or self.get_default_model()

        payload: dict[str, Any] = {
            "model": model,
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
        url = f"{self.BASE_URL}/chat/completions"

        logger.debug(
            "OpenRouter completion request",
            extra={
                "event": "openrouter_request",
                "model": model,
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
                f"OpenRouter API error: {e.response.text}",
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

        # Get actual model used (may differ from requested with auto)
        actual_model = data.get("model") or model

        logger.info(
            "OpenRouter completion completed",
            extra={
                "event": "openrouter_response",
                "model": actual_model,
                "duration_ms": duration_ms,
                "total_tokens": usage.total_tokens,
            },
        )

        return ChatResponse(
            content=content,
            tool_calls=self._parse_tool_calls(raw_tool_calls),
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            model=actual_model,
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
        model = model or self.get_default_model()

        payload: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
            "stream": True,
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
        url = f"{self.BASE_URL}/chat/completions"

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
            # For streaming responses, we need to read the content first
            try:
                await e.response.aread()
                error_text = e.response.text
            except Exception:
                error_text = str(e)
            raise ProviderError(
                f"OpenRouter streaming error: {error_text}",
                provider=self.provider_name,
                status_code=e.response.status_code,
            ) from e

    async def test_connection(self) -> dict[str, Any]:
        """Test connection to OpenRouter."""
        try:
            response = await self.complete(
                messages=[ChatMessage.user("Say 'hello' in one word.")],
                max_tokens=20,  # Minimum 16 required by some models like GPT-5 mini
            )
            return {
                "status": "connected",
                "provider": self.provider_name,
                "model": response.model,
                "response_time_ms": response.duration_ms,
                "test_response": response.content[:100],
            }
        except Exception as e:
            return {
                "status": "error",
                "provider": self.provider_name,
                "error": str(e),
            }

    async def fetch_models(self) -> list[dict[str, Any]]:
        """Fetch available models from OpenRouter API."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.BASE_URL}/models", headers=self._get_headers())
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception:
            return []

    def list_models(self) -> list[dict[str, Any]]:
        """List common OpenRouter models."""
        return [
            {
                "id": model_id,
                "name": model_id,
                "provider": self.provider_name,
                **info,
            }
            for model_id, info in self.MODELS.items()
        ]

    def _get_fallback_model(self) -> str:
        return "openai/gpt-5-mini"

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
