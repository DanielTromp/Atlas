"""Anthropic (Claude) provider implementation."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from infrastructure_atlas.ai.models import (
    ChatMessage,
    ChatResponse,
    MessageRole,
    ProviderConfig,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from infrastructure_atlas.infrastructure.logging import get_logger

from .base import AIProvider, ProviderError, RateLimitError

logger = get_logger(__name__)


class AnthropicProvider(AIProvider):
    """Anthropic Claude API provider.

    Configuration:
        - api_key: Anthropic API key
        - default_model: Default model (e.g., claude-sonnet-4-5-20250929)
    """

    provider_name = "anthropic"
    BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    # Available Claude models
    MODELS = {
        # Claude 4.5 models
        "claude-opus-4-5-20251101": {"context_window": 200000, "max_output": 16384},
        "claude-sonnet-4-5-20250929": {"context_window": 200000, "max_output": 16384},
        "claude-haiku-4-5-20251001": {"context_window": 200000, "max_output": 16384},
    }

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout))
        return self._client

    def _get_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    def _format_messages(self, messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        """Format messages for Anthropic API (separate system from messages)."""
        system_prompt = None
        formatted_messages = []

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_prompt = msg.content
            elif msg.role == MessageRole.TOOL:
                # Anthropic uses tool_result blocks
                formatted_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content,
                            }
                        ],
                    }
                )
            elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                # Assistant message with tool calls
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                formatted_messages.append(
                    {
                        "role": "assistant",
                        "content": content_blocks,
                    }
                )
            else:
                role = "assistant" if msg.role == MessageRole.ASSISTANT else "user"
                formatted_messages.append(
                    {
                        "role": role,
                        "content": msg.content,
                    }
                )

        return system_prompt, formatted_messages

    def _format_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Convert OpenAI tool format to Anthropic format."""
        if not tools:
            return None

        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append(
                    {
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                    }
                )

        return anthropic_tools

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
        """Generate a chat completion using Anthropic Claude."""
        start_time = time.perf_counter()
        model = model or self.get_default_model()

        system_prompt, formatted_messages = self._format_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens or 4096,
        }

        if system_prompt:
            payload["system"] = system_prompt
        if temperature is not None:
            payload["temperature"] = temperature

        anthropic_tools = self._format_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools
            if tool_choice == "auto":
                payload["tool_choice"] = {"type": "auto"}
            elif tool_choice == "none":
                # Don't include tools if none is requested
                del payload["tools"]

        client = await self._get_client()
        url = f"{self.BASE_URL}/messages"

        logger.debug(
            "Anthropic completion request",
            extra={
                "event": "anthropic_request",
                "model": model,
                "message_count": len(formatted_messages),
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
                f"Anthropic API error: {e.response.text}",
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
        content_blocks = data.get("content", [])
        text_content = ""
        tool_calls = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}),
                    )
                )

        # Parse usage
        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
        )

        logger.info(
            "Anthropic completion completed",
            extra={
                "event": "anthropic_response",
                "model": model,
                "duration_ms": duration_ms,
                "total_tokens": usage.total_tokens,
            },
        )

        return ChatResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=data.get("stop_reason"),
            usage=usage,
            model=model,
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

        system_prompt, formatted_messages = self._format_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens or 4096,
            "stream": True,
        }

        if system_prompt:
            payload["system"] = system_prompt
        if temperature is not None:
            payload["temperature"] = temperature

        anthropic_tools = self._format_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        client = await self._get_client()
        url = f"{self.BASE_URL}/messages"

        accumulated_tool_calls: dict[str, dict[str, Any]] = {}
        current_tool_id = None
        input_tokens = 0  # Captured from message_start event

        try:
            async with client.stream("POST", url, headers=self._get_headers(), json=payload) as response:
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise RateLimitError(
                        "Rate limit exceeded",
                        provider=self.provider_name,
                        retry_after=retry_after,
                    )

                # Check for errors before iterating - read body to get error message
                if response.status_code >= 400:
                    await response.aread()
                    error_body = response.text
                    raise ProviderError(
                        f"Anthropic API error: {error_body}",
                        provider=self.provider_name,
                        status_code=response.status_code,
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if not data_str:
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type")

                    if event_type == "message_start":
                        # Capture input_tokens from message_start event
                        message = data.get("message", {})
                        usage_data = message.get("usage", {})
                        input_tokens = usage_data.get("input_tokens", 0)

                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool_id = block.get("id")
                            accumulated_tool_calls[current_tool_id] = {
                                "id": current_tool_id,
                                "name": block.get("name", ""),
                                "input": "",
                            }

                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield StreamChunk(content=delta.get("text", ""))
                        elif delta.get("type") == "input_json_delta":
                            if current_tool_id and current_tool_id in accumulated_tool_calls:
                                accumulated_tool_calls[current_tool_id]["input"] += delta.get("partial_json", "")

                    elif event_type == "message_delta":
                        usage = None
                        usage_data = data.get("usage")
                        if usage_data:
                            output_tokens = usage_data.get("output_tokens", 0)
                            usage = TokenUsage(
                                prompt_tokens=input_tokens,
                                completion_tokens=output_tokens,
                                total_tokens=input_tokens + output_tokens,
                            )

                        stop_reason = data.get("delta", {}).get("stop_reason")

                        # Parse tool calls on completion
                        tool_calls = None
                        if accumulated_tool_calls:
                            tool_calls = []
                            for tc_data in accumulated_tool_calls.values():
                                try:
                                    args = json.loads(tc_data["input"]) if tc_data["input"] else {}
                                except json.JSONDecodeError:
                                    args = {}
                                tool_calls.append(
                                    ToolCall(
                                        id=tc_data["id"],
                                        name=tc_data["name"],
                                        arguments=args,
                                    )
                                )

                        yield StreamChunk(
                            content="",
                            tool_calls=tool_calls,
                            finish_reason=stop_reason,
                            is_complete=True,
                            usage=usage,
                        )

        except httpx.HTTPStatusError as e:
            # For streaming responses, we need to read the body before accessing text
            try:
                await e.response.aread()
                error_body = e.response.text
            except Exception:
                error_body = f"HTTP {e.response.status_code}"
            raise ProviderError(
                f"Anthropic streaming error: {error_body}",
                provider=self.provider_name,
                status_code=e.response.status_code,
            ) from e

    async def test_connection(self) -> dict[str, Any]:
        """Test connection to Anthropic."""
        try:
            response = await self.complete(
                messages=[ChatMessage.user("Say 'hello' in one word.")],
                max_tokens=20,
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

    def list_models(self) -> list[dict[str, Any]]:
        """List available Anthropic models."""
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
        return "claude-sonnet-4-5-20250929"

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
