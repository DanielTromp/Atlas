"""Logging helpers centralised for CLI, API, and background workers."""
from __future__ import annotations

import logging
import os
from typing import Any

_LOGGING_INITIALISED = False


def setup_logging(level: str | int | None = None, *, structured: bool | None = None) -> None:
    """Initialise application logging with safe defaults.

    Parameters
    ----------
    level:
        Explicit logging level. When omitted, derived from the `ENREACH_LOG_LEVEL`
        environment variable (default: `INFO`).
    structured:
        When True, attempt to enable `structlog` if the optional dependency is
        available. A value of None auto-detects based on `ENREACH_LOG_STRUCTURED`.
    """
    global _LOGGING_INITIALISED

    if _LOGGING_INITIALISED:
        return

    resolved_level = _resolve_level(level)
    resolved_structured = _resolve_structured(structured)

    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if resolved_structured:
        _configure_structlog(resolved_level)

    _LOGGING_INITIALISED = True


def _resolve_level(level: str | int | None) -> int:
    if level is not None:
        return _coerce_level(level)
    env_level = os.getenv("ENREACH_LOG_LEVEL", "INFO")
    return _coerce_level(env_level)


def _coerce_level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    try:
        return logging.getLevelName(value.upper())  # type: ignore[return-value]
    except Exception:
        return logging.INFO


def _resolve_structured(structured: bool | None) -> bool:
    if structured is not None:
        return structured
    raw = os.getenv("ENREACH_LOG_STRUCTURED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _configure_structlog(level: int) -> None:
    try:
        import structlog  # type: ignore
    except Exception:
        logging.getLogger(__name__).debug("structlog not available; falling back to stdlib logging")
        return

    shared_processors: list[Any] = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
    )


__all__ = ["setup_logging"]
