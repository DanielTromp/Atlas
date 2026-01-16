"""Claude Code CLI provider for AI chat.

Uses the local Claude Code CLI (`claude --dangerously-skip-permissions`)
to provide AI responses. This allows using Claude Code's capabilities
including its context and tools directly from the Atlas chat interface.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncGenerator
from typing import Any

from infrastructure_atlas.ai.models import (
    ChatMessage,
    ChatResponse,
    MessageRole,
    ProviderConfig,
    StreamChunk,
    TokenUsage,
)

from .base import AIProvider, ProviderError

logger = logging.getLogger(__name__)


class ClaudeCodeProvider(AIProvider):
    """AI Provider that uses the Claude Code CLI.

    This provider executes the local `claude` CLI with
    `--dangerously-skip-permissions` to get AI responses.

    Note: This provider does NOT support tools or streaming in the
    traditional sense - it runs Claude Code as a subprocess and
    returns the full response.
    """

    provider_name = "claude_code"

    def __init__(self, config: ProviderConfig):
        """Initialize the Claude Code provider."""
        self.config = config
        self._claude_path: str | None = None
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate that Claude CLI is available."""
        self._claude_path = shutil.which("claude")
        if not self._claude_path:
            raise ProviderError(
                "Claude Code CLI not found in PATH. Install it with: npm install -g @anthropic-ai/claude-code",
                provider=self.provider_name,
            )

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
        """Generate a completion using Claude Code CLI.

        Takes the last user message and sends it to Claude Code.
        """
        # Extract the last user message as the prompt
        user_messages = [m for m in messages if m.role == MessageRole.USER]
        if not user_messages:
            raise ProviderError("No user message found", provider=self.provider_name)

        prompt = user_messages[-1].content

        # Include system prompt if present
        system_messages = [m for m in messages if m.role == MessageRole.SYSTEM]
        if system_messages:
            # Prepend system context to the prompt
            system_context = system_messages[0].content
            prompt = f"Context: {system_context}\n\nUser request: {prompt}"

        # Build command
        cmd = [
            self._claude_path,
            "--dangerously-skip-permissions",
            "-p",  # Print mode
            prompt,
        ]

        # Add model flag if specified
        if model and model != "claude-code":
            # Claude Code supports --model flag for specific models
            cmd.extend(["--model", model])

        logger.info(f"Running Claude Code CLI with prompt length: {len(prompt)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout or 300,
            )

            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""

            if proc.returncode != 0:
                logger.error(f"Claude Code CLI failed: {error}")
                raise ProviderError(
                    f"Claude Code CLI error: {error or 'Unknown error'}",
                    provider=self.provider_name,
                )

            # Log any stderr as warning (Claude Code may output progress there)
            if error:
                logger.debug(f"Claude Code stderr: {error}")

            return ChatResponse(
                content=output.strip(),
                role=MessageRole.ASSISTANT,
                finish_reason="stop",
                model=model or "claude-code",
                provider=self.provider_name,
                # We don't have token counts from CLI
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )

        except asyncio.TimeoutError:
            raise ProviderError(
                f"Claude Code CLI timed out after {self.config.timeout}s",
                provider=self.provider_name,
            )
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            logger.exception("Claude Code CLI error")
            raise ProviderError(f"Claude Code error: {e}", provider=self.provider_name)

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
        """Stream responses from Claude Code CLI.

        Note: This simulates streaming by running the full command
        and then yielding the response in chunks.
        """
        # Get the full response first
        response = await self.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )

        # Simulate streaming by yielding chunks
        content = response.content
        chunk_size = 50  # Characters per chunk

        for i in range(0, len(content), chunk_size):
            chunk = content[i : i + chunk_size]
            is_last = i + chunk_size >= len(content)

            yield StreamChunk(
                content=chunk,
                finish_reason="stop" if is_last else None,
                is_complete=is_last,
                usage=response.usage if is_last else None,
            )

            # Small delay to simulate streaming
            if not is_last:
                await asyncio.sleep(0.01)

    async def test_connection(self) -> dict[str, Any]:
        """Test that Claude Code CLI is available."""
        if not self._claude_path:
            return {
                "status": "error",
                "name": self.provider_name,
                "error": "Claude Code CLI not found",
            }

        try:
            proc = await asyncio.create_subprocess_exec(
                self._claude_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            version = stdout.decode().strip() if stdout else "unknown"

            return {
                "status": "ok",
                "name": self.provider_name,
                "version": version,
                "path": self._claude_path,
            }
        except Exception as e:
            return {
                "status": "error",
                "name": self.provider_name,
                "error": str(e),
            }

    def list_models(self) -> list[dict[str, Any]]:
        """List available models for Claude Code.

        Claude Code can use different Claude models via --model flag.
        """
        return [
            {
                "id": "claude-code",
                "name": "Claude Code (Default)",
                "description": "Uses Claude Code's default model",
                "context_window": 200000,
            },
            {
                "id": "claude-sonnet-4-5-20250929",
                "name": "Claude Sonnet 4.5",
                "description": "Latest Claude Sonnet via Claude Code",
                "context_window": 200000,
            },
            {
                "id": "claude-opus-4-5-20251101",
                "name": "Claude Opus 4.5",
                "description": "Most capable Claude model via Claude Code",
                "context_window": 200000,
            },
        ]

    def _get_fallback_model(self) -> str:
        """Get the fallback model."""
        return "claude-code"

    def supports_tools(self) -> bool:
        """Claude Code handles its own tools internally."""
        return False

    def supports_streaming(self) -> bool:
        """We simulate streaming from full response."""
        return True
