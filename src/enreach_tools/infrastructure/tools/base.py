"""Common helpers for LangChain tools."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool

from enreach_tools.infrastructure.logging import get_logger

__all__ = [
    "EnreachTool",
    "ToolConfigurationError",
    "ToolExecutionError",
]


class ToolExecutionError(RuntimeError):
    """Raised when a tool encounters a recoverable execution error."""


class ToolConfigurationError(RuntimeError):
    """Raised when a tool is misconfigured (e.g. missing credentials)."""


class EnreachTool(BaseTool):
    """Base class that adds logging and helper utilities for tools."""

    logger: ClassVar[logging.Logger] = get_logger(__name__)
    return_direct: ClassVar[bool] = False

    @staticmethod
    def format_ams_timestamp(value: datetime) -> str:
        """Return a timestamp in Europe/Amsterdam with explicit timezone."""

        tz = ZoneInfo("Europe/Amsterdam")
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        local = dt.astimezone(tz)
        timezone_label = local.tzname() or "CET"
        return local.strftime("%Y-%m-%d %H:%M:%S ") + timezone_label

    def _handle_exception(self, error: Exception) -> ToolExecutionError:
        self.logger.error("Tool execution failed", exc_info=error, extra={"tool": self.name})
        if isinstance(error, ToolExecutionError):
            return error
        return ToolExecutionError(str(error))

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - LangChain handles sync path
        return self._run(*args, **kwargs)
