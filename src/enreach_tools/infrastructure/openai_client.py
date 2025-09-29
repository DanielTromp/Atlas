"""Enhanced OpenAI client with rate limiting, retry logic, and comprehensive token tracking."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

import requests

from enreach_tools.infrastructure.logging import get_logger
from enreach_tools.infrastructure.rate_limiting import (
    RateLimiter,
    TokenUsageTracker,
    get_rate_limiter,
    get_token_tracker,
    with_rate_limiting,
)

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

logger = get_logger(__name__)


@dataclass
class OpenAIResponse:
    """Response from OpenAI API with comprehensive metadata."""
    
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    provider: str = "openai"
    duration_ms: int = 0
    retry_count: int = 0
    rate_limited: bool = False


class EnhancedOpenAIClient:
    """OpenAI client with rate limiting, retry logic, and token tracking."""
    
    # Token costs per 1K tokens (as of 2024)
    TOKEN_COSTS: ClassVar[dict[str, dict[str, float]]] = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "gpt-5-nano": {"input": 0.0001, "output": 0.0004},  # Estimated
        "gpt-5-mini": {"input": 0.0002, "output": 0.0008},  # Estimated
    }
    
    def __init__(
        self,
        api_key: str,
        rate_limiter: RateLimiter | None = None,
        token_tracker: TokenUsageTracker | None = None,
    ):
        self.api_key = api_key
        self.rate_limiter = rate_limiter or get_rate_limiter()
        self.token_tracker = token_tracker or get_token_tracker()
        self._client = OpenAI(api_key=api_key) if OpenAI else None
    
    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost in USD for token usage."""
        model_key = model.lower()
        
        # Find matching cost structure
        costs = None
        for key, cost_info in self.TOKEN_COSTS.items():
            if model_key.startswith(key.lower()):
                costs = cost_info
                break
        
        if not costs:
            # Default to gpt-4o-mini pricing for unknown models
            costs = self.TOKEN_COSTS["gpt-4o-mini"]
        
        input_cost = (prompt_tokens / 1000) * costs["input"]
        output_cost = (completion_tokens / 1000) * costs["output"]
        
        return input_cost + output_cost
    
    def _normalize_usage(self, raw: Any) -> tuple[int, int, int]:
        """Extract token usage from various response formats."""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        
        if not raw:
            return prompt_tokens, completion_tokens, total_tokens
        
        # Handle different usage formats
        if isinstance(raw, dict):
            prompt_tokens = int(raw.get("prompt_tokens", 0) or 0)
            completion_tokens = int(raw.get("completion_tokens", 0) or 0)
            total_tokens = int(raw.get("total_tokens", 0) or 0)
            
            # Alternative field names
            if not prompt_tokens:
                prompt_tokens = int(raw.get("input_tokens", 0) or 0)
            if not completion_tokens:
                completion_tokens = int(raw.get("output_tokens", 0) or 0)
        else:
            # Handle object with attributes
            prompt_tokens = int(getattr(raw, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(raw, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(raw, "total_tokens", 0) or 0)
            
            # Alternative attribute names
            if not prompt_tokens:
                prompt_tokens = int(getattr(raw, "input_tokens", 0) or 0)
            if not completion_tokens:
                completion_tokens = int(getattr(raw, "output_tokens", 0) or 0)
        
        # Calculate total if not provided
        if not total_tokens and (prompt_tokens or completion_tokens):
            total_tokens = prompt_tokens + completion_tokens
        
        return prompt_tokens, completion_tokens, total_tokens

    def _safe_normalize_usage(self, raw: Any) -> tuple[int, int, int]:
        try:
            return self._normalize_usage(raw)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Skipping malformed usage payload", extra={"error": str(exc)})
            return 0, 0, 0
    
    def _format_responses_messages(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Format messages for OpenAI Responses API."""
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            text = str(msg.get("content", ""))
            content_type = "output_text" if role == "assistant" else "input_text"
            formatted.append({
                "role": role,
                "content": [{"type": content_type, "text": text}],
            })
        return formatted
    
    def _use_responses_api(self, model: str) -> bool:
        """Check if model should use the Responses API."""
        return model.lower().startswith("gpt-5")
    
    def _supports_temperature(self, model: str) -> bool:
        """Check if model supports temperature parameter in Responses API."""
        return not model.lower().startswith("gpt-5")
    
    async def _make_completion_request(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        session_id: str | None = None,
    ) -> OpenAIResponse:
        """Make a completion request with rate limiting and error handling."""
        
        start_time = time.perf_counter()
        
        # Estimate token usage for rate limiting
        estimated_tokens = sum(len(str(msg.get("content", ""))) for msg in messages) // 4
        
        def _execute_request() -> OpenAIResponse:
            if self._client and self._use_responses_api(model):
                return self._call_responses_api_sync(model, messages, temperature)
            elif self._client:
                return self._call_chat_completions_sync(model, messages, temperature)
            else:
                return self._call_http_api_sync(model, messages, temperature)
        
        # Execute with rate limiting
        response = await with_rate_limiting(
            _execute_request,
            self.rate_limiter,
            estimated_tokens,
        )
        
        # Calculate duration and update response
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        response.duration_ms = duration_ms
        
        # Record token usage
        if response.total_tokens > 0:
            await self.token_tracker.record_usage(
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                cost_usd=response.cost_usd,
                session_id=session_id,
            )
        
        logger.info(
            "OpenAI request completed",
            extra={
                "event": "openai_request_completed",
                "model": model,
                "duration_ms": duration_ms,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
                "cost_usd": response.cost_usd,
                "retry_count": response.retry_count,
                "rate_limited": response.rate_limited,
                "session_id": session_id,
            }
        )
        
        return response
    
    def _call_responses_api_sync(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> OpenAIResponse:
        """Call OpenAI Responses API using the SDK."""
        if not self._client:
            raise RuntimeError("OpenAI client not available")
        
        kwargs: dict[str, Any] = {
            "model": model,
            "input": self._format_responses_messages(messages),
        }
        
        if self._supports_temperature(model) and temperature is not None:
            kwargs["temperature"] = temperature
        
        resp = self._client.responses.create(**kwargs)
        
        # Extract usage and text
        prompt_tokens, completion_tokens, total_tokens = self._normalize_usage(
            getattr(resp, "usage", None)
        )
        
        # Extract text content
        text = ""
        try:
            text = getattr(resp, "output_text", None) or ""
            if not text:
                # Fallback: collect text parts
                for item in getattr(resp, "output", []) or []:
                    for part in getattr(item, "content", []) or []:
                        if getattr(part, "type", "") == "output_text":
                            text += getattr(part, "text", "")
        except Exception:
            text = ""
        
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
        
        return OpenAIResponse(
            text=text.strip(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            model=model,
        )
    
    def _call_chat_completions_sync(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> OpenAIResponse:
        """Call OpenAI Chat Completions API using the SDK."""
        if not self._client:
            raise RuntimeError("OpenAI client not available")
        
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        
        # Extract usage and text
        prompt_tokens, completion_tokens, total_tokens = self._normalize_usage(
            getattr(resp, "usage", None)
        )
        
        text = ""
        try:
            choice = (resp.choices or [None])[0]
            if choice:
                msg = getattr(choice, "message", None)
                if msg:
                    text = getattr(msg, "content", "") or ""
        except Exception:
            text = ""
        
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
        
        return OpenAIResponse(
            text=text.strip(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            model=model,
        )
    
    def _call_http_api_sync(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> OpenAIResponse:
        """Call OpenAI API using HTTP requests as fallback."""
        
        if self._use_responses_api(model):
            url = "https://api.openai.com/v1/responses"
            payload = {
                "model": model,
                "input": self._format_responses_messages(messages),
            }
            if self._supports_temperature(model) and temperature is not None:
                payload["temperature"] = temperature
        else:
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        # Make HTTP request
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        
        # Extract usage and text
        prompt_tokens, completion_tokens, total_tokens = self._normalize_usage(
            data.get("usage")
        )
        
        text = ""
        if self._use_responses_api(model):
            text = data.get("output_text", "")
            if not text:
                try:
                    for item in data.get("output", []):
                        for part in item.get("content", []):
                            if part.get("type") == "output_text":
                                text += part.get("text", "")
                except Exception:
                    pass
        else:
            try:
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception:
                pass
        
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
        
        return OpenAIResponse(
            text=text.strip(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            model=model,
        )
    
    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        session_id: str | None = None,
    ) -> OpenAIResponse:
        """Create a chat completion with rate limiting and token tracking."""
        
        logger.debug(
            "Starting OpenAI completion request",
            extra={
                "event": "openai_request_start",
                "model": model,
                "message_count": len(messages),
                "session_id": session_id,
            }
        )
        
        return await self._make_completion_request(model, messages, temperature, session_id)
    
    async def stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        session_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Create a streaming chat completion with rate limiting."""
        
        logger.debug(
            "Starting OpenAI streaming request",
            extra={
                "event": "openai_stream_start",
                "model": model,
                "message_count": len(messages),
                "session_id": session_id,
            }
        )
        
        start_time = time.perf_counter()
        estimated_tokens = sum(len(str(msg.get("content", ""))) for msg in messages) // 4
        
        # Check rate limits before starting stream
        can_proceed, reason = await self.rate_limiter.can_make_request(estimated_tokens)
        if not can_proceed:
            logger.warning(
                "Streaming request blocked by rate limiter",
                extra={
                    "event": "stream_rate_limited",
                    "reason": reason,
                    "model": model,
                    "session_id": session_id,
                }
            )
            yield f"⏳ Processing delayed: {reason}"
            
            # Wait for rate limit to clear
            await asyncio.sleep(5)
            return
        
        # Record the request
        await self.rate_limiter.record_request(estimated_tokens)
        
        full_text = ""
        usage_data: dict[str, int] = {}
        
        try:
            async for chunk in self._stream_implementation(model, messages, temperature):
                if chunk.startswith("[[TOKENS "):
                    # Extract token usage from special marker
                    try:
                        import json
                        marker_end = chunk.find("]]")
                        if marker_end > 0:
                            token_data = chunk[len("[[TOKENS "):marker_end]
                            usage_data = json.loads(token_data)
                    except Exception:
                        pass
                else:
                    full_text += chunk
                    yield chunk
            
            # Record final usage if available
            if usage_data:
                prompt_tokens = usage_data.get("prompt_tokens", 0)
                completion_tokens = usage_data.get("completion_tokens", 0)
                total_tokens = usage_data.get("total_tokens", prompt_tokens + completion_tokens)
                cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
                
                await self.token_tracker.record_usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost,
                    session_id=session_id,
                )
                
                # Yield token usage marker for frontend
                yield f"[[TOKENS {json.dumps(usage_data)}]]"
            
            await self.rate_limiter.record_success()
            
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(
                "OpenAI streaming request completed",
                extra={
                    "event": "openai_stream_completed",
                    "model": model,
                    "duration_ms": duration_ms,
                    "response_chars": len(full_text),
                    "session_id": session_id,
                    **usage_data,
                }
            )
            
        except Exception as exc:
            await self.rate_limiter.record_rate_limit_error()
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            
            logger.error(
                "OpenAI streaming request failed",
                extra={
                    "event": "openai_stream_error",
                    "model": model,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                    "session_id": session_id,
                }
            )
            
            # Provide user-friendly error message
            if "rate limit" in str(exc).lower() or "429" in str(exc):
                yield "⚠️ Rate limit reached. Please wait a moment before sending another message."
            elif "503" in str(exc) or "service unavailable" in str(exc).lower():
                yield "⚠️ Service temporarily unavailable. Retrying automatically..."
            else:
                yield f"❌ Request failed: {str(exc)[:100]}"
    
    async def _stream_implementation(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncGenerator[str, None]:
        """Implementation of streaming with SDK or HTTP fallback."""
        
        if self._client:
            try:
                if self._use_responses_api(model):
                    async for chunk in self._stream_responses_sdk(model, messages, temperature):
                        yield chunk
                else:
                    async for chunk in self._stream_chat_sdk(model, messages, temperature):
                        yield chunk
                return
            except Exception as exc:
                # Check if streaming is unsupported
                if "stream" in str(exc).lower() and "unsupported" in str(exc).lower():
                    logger.info(
                        "Streaming unsupported, falling back to completion",
                        extra={
                            "event": "stream_fallback_to_completion",
                            "model": model,
                            "error": str(exc),
                        }
                    )
                    # Fall back to non-streaming
                    response = await self._make_completion_request(model, messages, temperature)
                    yield response.text
                    return
                else:
                    raise
        
        # HTTP fallback
        async for chunk in self._stream_http_api(model, messages, temperature):
            yield chunk
    
    async def _stream_responses_sdk(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncGenerator[str, None]:
        """Stream using OpenAI Responses API with SDK."""
        if not self._client:
            raise RuntimeError("OpenAI client not available")
        
        kwargs: dict[str, Any] = {
            "model": model,
            "input": self._format_responses_messages(messages),
        }
        
        if self._supports_temperature(model) and temperature is not None:
            kwargs["temperature"] = temperature
        
        usage_data: dict[str, int] = {}
        
        with self._client.responses.stream(**kwargs) as stream:
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta

                usage = getattr(event, "usage", None)
                if usage:
                    prompt_tokens, completion_tokens, total_tokens = self._safe_normalize_usage(usage)
                    if total_tokens > 0:
                        usage_data = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                        }
            
            # Get final usage from completed response
            final_response = stream.get_final_response()
            if final_response:
                usage = getattr(final_response, "usage", None)
                if usage:
                    prompt_tokens, completion_tokens, total_tokens = self._normalize_usage(usage)
                    if total_tokens > 0:
                        usage_data = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                        }
        
        # Yield usage data if available
        if usage_data:
            import json
            yield f"[[TOKENS {json.dumps(usage_data)}]]"
    
    async def _stream_chat_sdk(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncGenerator[str, None]:
        """Stream using OpenAI Chat Completions API with SDK."""
        if not self._client:
            raise RuntimeError("OpenAI client not available")
        
        usage_data: dict[str, int] = {}
        
        stream = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        
        for chunk in stream:
            choice = (chunk.choices or [None])[0]
            delta = getattr(choice, "delta", None)
            if delta is not None:
                content = getattr(delta, "content", None)
                if content:
                    yield content

            usage = getattr(chunk, "usage", None)
            if usage:
                prompt_tokens, completion_tokens, total_tokens = self._safe_normalize_usage(usage)
                if total_tokens > 0:
                    usage_data = {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    }
        
        # Yield usage data if available
        if usage_data:
            import json
            yield f"[[TOKENS {json.dumps(usage_data)}]]"
    
    async def _stream_http_api(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncGenerator[str, None]:
        """Stream using HTTP API as fallback."""
        
        if self._use_responses_api(model):
            url = "https://api.openai.com/v1/responses"
            payload = {
                "model": model,
                "input": self._format_responses_messages(messages),
                "stream": True,
            }
            if self._supports_temperature(model) and temperature is not None:
                payload["temperature"] = temperature
        else:
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        
        usage_data: dict[str, int] = {}
        
        with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as r:
            r.raise_for_status()
            
            for raw_line in r.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                
                data = raw_line[5:].strip()
                if data == "[DONE]":
                    break
                
                try:
                    import json
                    obj = json.loads(data)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.debug("Skipping malformed OpenAI stream chunk", extra={"error": str(exc)})
                    obj = None
                if not isinstance(obj, dict):
                    continue

                if self._use_responses_api(model):
                    if obj.get("type") == "response.output_text.delta":
                        delta = obj.get("delta", "")
                        if delta:
                            yield delta
                else:
                    delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta

                usage = obj.get("usage")
                if usage:
                    prompt_tokens, completion_tokens, total_tokens = self._safe_normalize_usage(usage)
                    if total_tokens > 0:
                        usage_data = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": total_tokens,
                        }
        
        # Yield usage data if available
        if usage_data:
            import json
            yield f"[[TOKENS {json.dumps(usage_data)}]]"
    
    async def get_usage_stats(self) -> dict[str, Any]:
        """Get comprehensive usage statistics."""
        rate_stats = await self.rate_limiter.get_usage_stats()
        recent_usage = await self.token_tracker.get_recent_usage(24)
        
        return {
            "rate_limiting": rate_stats,
            "token_usage_24h": recent_usage,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# Global client instance
_GLOBAL_CLIENT_STATE: dict[str, EnhancedOpenAIClient | None] = {"instance": None}


def get_enhanced_openai_client(api_key: str | None = None) -> EnhancedOpenAIClient:
    """Get the global enhanced OpenAI client instance."""
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY", "")

    if not api_key:
        raise ValueError("OpenAI API key is required")

    client = _GLOBAL_CLIENT_STATE.get("instance")
    if client is None or client.api_key != api_key:
        client = EnhancedOpenAIClient(api_key)
        _GLOBAL_CLIENT_STATE["instance"] = client

    return client


__all__ = [
    "EnhancedOpenAIClient",
    "OpenAIResponse",
    "get_enhanced_openai_client",
]
