
"""API-layer middleware for observability (logging, metrics, tracing)."""
from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from enreach_tools.infrastructure.logging import get_logger, logging_context
from enreach_tools.infrastructure.metrics import record_http_request
from enreach_tools.infrastructure.tracing import span


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Capture structured logs, metrics, and tracing spans for HTTP requests."""

    def __init__(self, app: ASGIApp, *, metrics_enabled: bool = False) -> None:
        super().__init__(app)
        self._metrics_enabled = metrics_enabled
        self._logger = get_logger(__name__)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        start = time.perf_counter()
        request.state.request_id = request_id  # type: ignore[attr-defined]
        path_template = self._resolve_path_template(request)

        with logging_context(
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
            path_template=path_template,
        ), span(
            "http.request",
            method=request.method,
            path=request.url.path,
            path_template=path_template,
        ):
            try:
                response = await call_next(request)
            except Exception:
                duration = time.perf_counter() - start
                if self._metrics_enabled:
                    record_http_request(
                        duration_seconds=duration,
                        method=request.method,
                        path_template=path_template,
                        status_code=500,
                    )
                self._logger.exception(
                    "Request failed",
                    extra={
                        "status_code": 500,
                        "duration_ms": int(duration * 1000),
                    },
                )
                raise

            duration = time.perf_counter() - start
            status_code = getattr(response, "status_code", 500)

            if self._metrics_enabled:
                record_http_request(
                    duration_seconds=duration,
                    method=request.method,
                    path_template=path_template,
                    status_code=status_code,
                )

            response.headers.setdefault("X-Request-ID", request_id)
            self._logger.info(
                "Request completed",
                extra={
                    "status_code": status_code,
                    "duration_ms": int(duration * 1000),
                    "path_template": path_template,
                },
            )
            return response

    @staticmethod
    def _resolve_path_template(request: Request) -> str:
        route = request.scope.get("route")
        if route is None:
            return request.url.path
        template = getattr(route, "path", None) or getattr(route, "path_format", None)
        return template or request.url.path


__all__ = ["ObservabilityMiddleware"]
