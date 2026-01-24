"""Google Gemini provider implementation."""

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


class GeminiProvider(AIProvider):
    """Google Gemini API provider.

    Configuration:
        - api_key: Google AI API key
        - default_model: Default model (e.g., gemini-1.5-flash)
    """

    provider_name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    # Available Gemini models
    # See https://ai.google.dev/gemini-api/docs/models
    MODELS = {
        # Gemini 3 models (latest)
        "gemini-3-pro-preview": {"context_window": 2097152, "max_output": 65536},
        "gemini-3-flash-preview": {"context_window": 1048576, "max_output": 65536},
        # Gemini 2.5 models
        "gemini-2.5-pro": {"context_window": 1048576, "max_output": 65536},
        "gemini-2.5-flash": {"context_window": 1048576, "max_output": 65536},
        # Gemini 2.0 models (deprecated March 2026)
        "gemini-2.0-flash": {"context_window": 1048576, "max_output": 8192},
    }

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout))
        return self._client

    def _format_messages(self, messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        """Format messages for Gemini API."""
        system_instruction = None
        contents = []

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_instruction = msg.content
            elif msg.role == MessageRole.USER:
                contents.append(
                    {
                        "role": "user",
                        "parts": [{"text": msg.content}],
                    }
                )
            elif msg.role == MessageRole.ASSISTANT:
                parts: list[dict[str, Any]] = []
                if msg.content:
                    parts.append({"text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        parts.append(
                            {
                                "functionCall": {
                                    "name": tc.name,
                                    "args": tc.arguments,
                                }
                            }
                        )
                contents.append(
                    {
                        "role": "model",
                        "parts": parts,
                    }
                )
            elif msg.role == MessageRole.TOOL:
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": msg.name or "",
                                    "response": {"result": msg.content},
                                }
                            }
                        ],
                    }
                )

        return system_instruction, contents

    def _format_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Convert OpenAI tool format to Gemini format."""
        if not tools:
            return None

        function_declarations = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                function_declarations.append(
                    {
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                    }
                )

        return [{"function_declarations": function_declarations}]

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
        """Generate a chat completion using Gemini."""
        start_time = time.perf_counter()
        model = model or self.get_default_model()

        system_instruction, contents = self._format_messages(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {},
        }

        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        if temperature is not None:
            payload["generationConfig"]["temperature"] = temperature
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        gemini_tools = self._format_tools(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools

        client = await self._get_client()
        url = f"{self.BASE_URL}/models/{model}:generateContent?key={self.config.api_key}"

        logger.debug(
            "Gemini completion request",
            extra={
                "event": "gemini_request",
                "model": model,
                "message_count": len(contents),
            },
        )

        try:
            response = await client.post(url, json=payload)

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
                f"Gemini API error: {e.response.text}",
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
        candidates = data.get("candidates", [])
        if not candidates:
            raise ProviderError("No response candidates", provider=self.provider_name)

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        text_content = ""
        tool_calls = []

        for part in parts:
            if "text" in part:
                text_content += part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    ToolCall(
                        id=f"call_{len(tool_calls)}",  # Gemini doesn't provide IDs
                        name=fc.get("name", ""),
                        arguments=fc.get("args", {}),
                    )
                )

        # Parse usage
        usage_metadata = data.get("usageMetadata", {})
        usage = TokenUsage(
            prompt_tokens=usage_metadata.get("promptTokenCount", 0),
            completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
            total_tokens=usage_metadata.get("totalTokenCount", 0),
        )

        finish_reason = candidates[0].get("finishReason", "")

        logger.info(
            "Gemini completion completed",
            extra={
                "event": "gemini_response",
                "model": model,
                "duration_ms": duration_ms,
                "total_tokens": usage.total_tokens,
            },
        )

        return ChatResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=finish_reason,
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

        system_instruction, contents = self._format_messages(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {},
        }

        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        if temperature is not None:
            payload["generationConfig"]["temperature"] = temperature
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        gemini_tools = self._format_tools(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools

        client = await self._get_client()
        url = f"{self.BASE_URL}/models/{model}:streamGenerateContent?key={self.config.api_key}&alt=sse"

        accumulated_tool_calls: list[ToolCall] = []

        try:
            async with client.stream("POST", url, json=payload) as response:
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
                    if not data_str:
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue

                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])

                    text_content = ""
                    for part in parts:
                        if "text" in part:
                            text_content += part["text"]
                        elif "functionCall" in part:
                            fc = part["functionCall"]
                            accumulated_tool_calls.append(
                                ToolCall(
                                    id=f"call_{len(accumulated_tool_calls)}",
                                    name=fc.get("name", ""),
                                    arguments=fc.get("args", {}),
                                )
                            )

                    finish_reason = candidates[0].get("finishReason")
                    is_complete = finish_reason is not None

                    usage = None
                    if "usageMetadata" in data:
                        usage_metadata = data["usageMetadata"]
                        usage = TokenUsage(
                            prompt_tokens=usage_metadata.get("promptTokenCount", 0),
                            completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
                            total_tokens=usage_metadata.get("totalTokenCount", 0),
                        )

                    yield StreamChunk(
                        content=text_content,
                        tool_calls=accumulated_tool_calls if is_complete and accumulated_tool_calls else None,
                        finish_reason=finish_reason,
                        is_complete=is_complete,
                        usage=usage,
                    )

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Gemini streaming error: {e.response.text}",
                provider=self.provider_name,
                status_code=e.response.status_code,
            ) from e

    async def test_connection(self) -> dict[str, Any]:
        """Test connection to Gemini."""
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
        """List available Gemini models."""
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
        return "gemini-2.5-flash"

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
