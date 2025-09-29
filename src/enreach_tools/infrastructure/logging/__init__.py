"""Logging helpers centralised for CLI, API, and background workers."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_LOGGING_STATE: dict[str, Any] = {"initialised": False, "context_filter": None}
_LOG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("enreach_log_context", default=None)
_ORIGINAL_FACTORY = logging.getLogRecordFactory()


def setup_logging(level: str | int | None = None, *, structured: bool | None = None) -> None:
    """Initialise application logging with safe defaults."""

    resolved_level = _resolve_level(level)
    resolved_structured = _resolve_structured(structured)

    root = logging.getLogger()

    if not _LOGGING_STATE["initialised"]:
        logging.basicConfig(
            level=resolved_level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s%(log_context)s",
        )
        _install_log_record_factory()
        _LOGGING_STATE["initialised"] = True

    if _LOG_CONTEXT.get() is None:
        _LOG_CONTEXT.set({})

    root.setLevel(resolved_level)

    _install_context_filter(force=True)
    _install_file_handler(resolved_level)

    if resolved_structured:
        _configure_structlog(resolved_level)


def _install_log_record_factory() -> None:
    def factory(*args, **kwargs):  # type: ignore[override]
        record = _ORIGINAL_FACTORY(*args, **kwargs)
        if "log_context" not in record.__dict__:
            record.log_context = ""
        context = _LOG_CONTEXT.get() or {}
        for key, value in context.items():
            if key not in record.__dict__:
                setattr(record, key, value)
        return record

    logging.setLogRecordFactory(factory)


def _install_context_filter(*, force: bool = False) -> None:
    context_filter = _LOGGING_STATE.get("context_filter")
    if context_filter is None:
        context_filter = _ContextFilter()
        _LOGGING_STATE["context_filter"] = context_filter

    root = logging.getLogger()
    if force or context_filter not in getattr(root, "filters", []):
        root.addFilter(context_filter)

    for handler in root.handlers:
        filters = getattr(handler, "filters", [])
        if force or context_filter not in filters:
            handler.addFilter(context_filter)


def _install_file_handler(level: int) -> None:
    root = logging.getLogger()
    target_path = _resolve_log_path()
    target_str = str(target_path)
    existing = [
        handler
        for handler in root.handlers
        if getattr(handler, "baseFilename", None) == target_str
    ]

    context_filter = _LOGGING_STATE.get("context_filter")

    if existing:
        primary = existing[0]
        primary.setLevel(level)
        primary.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s%(log_context)s")
        )
        if context_filter is not None and context_filter not in getattr(primary, "filters", []):
            primary.addFilter(context_filter)
        for duplicate in existing[1:]:
            root.removeHandler(duplicate)
            try:
                duplicate.close()
            except Exception:
                pass
        return

    handler = RotatingFileHandler(
        target_str,
        maxBytes=_resolve_int_env("ENREACH_LOG_MAX_BYTES", 5 * 1024 * 1024),
        backupCount=_resolve_int_env("ENREACH_LOG_BACKUP_COUNT", 5),
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s%(log_context)s")
    )
    if context_filter is not None:
        handler.addFilter(context_filter)

    root.addHandler(handler)


def _resolve_log_path() -> Path:
    directory = Path(os.getenv("ENREACH_LOG_DIR", "logs")).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    filename = os.getenv("ENREACH_LOG_FILE", "enreach.log").strip() or "enreach.log"
    return (directory / filename).resolve()


def _resolve_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


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
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
    )


def get_logger(name: str | None = None) -> logging.Logger:
    if not _LOGGING_STATE["initialised"]:
        setup_logging()
    logger = logging.getLogger(name or "enreach")
    logger.disabled = False
    return logger


@contextmanager
def logging_context(**kwargs: Any):
    base_context = _LOG_CONTEXT.get() or {}
    current = dict(base_context)
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
