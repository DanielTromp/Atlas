"""Callback utilities for capturing token usage during agent runs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

__all__ = ["TokenUsageCallback", "merge_token_usage"]


class TokenUsageCallback(BaseCallbackHandler):
    """Collect token usage emitted by LangChain chat models."""

    _ALIASES: Mapping[str, str] = {
        "prompt_tokens": "prompt_tokens",
        "completion_tokens": "completion_tokens",
        "total_tokens": "total_tokens",
        "promptTokens": "prompt_tokens",
        "completionTokens": "completion_tokens",
        "totalTokens": "total_tokens",
        "input_tokens": "prompt_tokens",
        "output_tokens": "completion_tokens",
        "usage_tokens": "total_tokens",
    }

    def __init__(self) -> None:
        super().__init__()
        self._totals: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id,
        parent_run_id=None,
        **kwargs,
    ) -> None:
        usage = {}
        if isinstance(response.llm_output, dict):
            usage = response.llm_output.get("token_usage") or response.llm_output.get("usage") or {}
        self._consume_usage(usage)

    def _consume_usage(self, payload: Mapping[str, object]) -> None:
        if not isinstance(payload, Mapping):
            return
        for key, value in payload.items():
            alias = self._ALIASES.get(str(key), None)
            if not alias:
                continue
            try:
                number = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            self._totals[alias] += max(number, 0)

    def snapshot(self) -> dict[str, int] | None:
        """Return the collected token usage or ``None`` when empty."""

        if not any(self._totals.values()):
            return None
        return dict(self._totals)


def merge_token_usage(*usages: Mapping[str, int] | None) -> dict[str, int] | None:
    """Combine multiple token usage dictionaries by summing shared keys."""

    accumulator: defaultdict[str, int] = defaultdict(int)
    for usage in usages:
        if not isinstance(usage, Mapping):
            continue
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if not isinstance(value, int | float):
                continue
            accumulator[key] += int(value)
    return dict(accumulator) if accumulator else None
