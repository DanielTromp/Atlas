"""Logging helpers centralised for CLI, API, and background workers."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict

_LOGGING_INITIALISED = False
_LOG_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("enreach_log_context", default={})
_CONTEXT_FILTER: _ContextFilter | None = None
_ORIGINAL_FACTORY = logging.getLogRecordFactory()


def setup_logging(level: str | int | None = None, *, structured: bool | None = None) -> None:
    """Initialise application logging with safe defaults."""

    global _LOGGING_INITIALISED

    if _LOGGING_INITIALISED:
        return

    resolved_level = _resolve_level(level)
    resolved_structured = _resolve_structured(structured)

    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s%(log_context)s",
    )

    _install_log_record_factory()
    _install_context_filter()

    if resolved_structured:
        _configure_structlog(resolved_level)

    _LOGGING_INITIALISED = True


def _install_log_record_factory() -> None:
    def factory(*args, **kwargs):  # type: ignore[override]
        record = _ORIGINAL_FACTORY(*args, **kwargs)
        if "log_context" not in record.__dict__:
            record.log_context = ""
        context = _LOG_CONTEXT.get()
        for key, value in context.items():
            if key not in record.__dict__:
                setattr(record, key, value)
        return record

    logging.setLogRecordFactory(factory)


def _install_context_filter() -> None:
    global _CONTEXT_FILTER
    if _CONTEXT_FILTER is not None:
        return
    _CONTEXT_FILTER = _ContextFilter()
    root = logging.getLogger()
    root.addFilter(_CONTEXT_FILTER)
    for handler in root.handlers:
        handler.addFilter(_CONTEXT_FILTER)


def _resolve_level(level: str | int | None) -> int:
    if level is not None:
        return _coerce_level(level)
    env_level = os.getenv("ENREACH_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO"))
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
        from structlog.contextvars import merge_contextvars
    except Exception:
        logging.getLogger(__name__).debug("structlog not available; falling back to stdlib logging")
        return

    shared_processors: list[Any] = [
        merge_contextvars,
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


def get_logger(name: str | None = None) -> logging.Logger:
    if not _LOGGING_INITIALISED:
        setup_logging()
    return logging.getLogger(name or "enreach")


@contextmanager
def logging_context(**kwargs: Any):
    current = dict(_LOG_CONTEXT.get())
    current.update({k: v for k, v in kwargs.items() if v is not None})
    token = _LOG_CONTEXT.set(current)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _LOG_CONTEXT.get()
        if context:
            for key, value in context.items():
                if key not in record.__dict__:
                    setattr(record, key, value)
            record.log_context = " " + " ".join(f"{k}={value}" for k, value in context.items())
        else:
            record.log_context = ""
        return True


__all__ = ["get_logger", "logging_context", "setup_logging"]
