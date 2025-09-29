"""Optional OpenTelemetry tracing utilities."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

try:
    from opentelemetry import trace  # type: ignore
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
    from opentelemetry.sdk.resources import Resource  # type: ignore
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    trace = None  # type: ignore

_TRACING_STATE: dict[str, Any | None] = {"tracer": None}


def tracing_enabled() -> bool:
    raw = os.getenv("ENREACH_TRACING_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def init_tracing(service_name: str = "enreach-tools") -> None:
    if _TRACING_STATE["tracer"] is not None or not tracing_enabled() or trace is None:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip() or "http://localhost:4318"
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _TRACING_STATE["tracer"] = trace.get_tracer(service_name)


def span(name: str, **attributes: Any):
    tracer = _TRACING_STATE.get("tracer")
    if tracer is None:
        return _null_context()
    span = tracer.start_span(name)
    for key, value in attributes.items():
        span.set_attribute(key, value)
    return _SpanContext(span)


@contextmanager
def _null_context():
    yield None


class _SpanContext:
    def __init__(self, span):  # type: ignore
        self._span = span

    def __enter__(self):  # type: ignore
        return self._span

    def __exit__(self, exc_type, exc, tb):  # type: ignore
        if exc:
            self._span.record_exception(exc)
        self._span.end()


__all__ = ["init_tracing", "span", "tracing_enabled"]
