"""
zerotel._middleware
~~~~~~~~~~~~~~~~~~~

ASGI middleware that forms the backbone of Zerotel's automatic
instrumentation.

``ZerotelMiddleware`` wraps every incoming HTTP request and:

1. **Skips** requests whose path is in ``ZerotelConfig.exclude_paths``
   (e.g. ``/health``, ``/metrics``) — these pass straight through.
2. **Extracts** the W3C ``traceparent`` header when present so distributed
   traces propagate correctly across service boundaries.
3. **Starts** an OpenTelemetry root span for the request.
4. **Populates** a ``RequestContext`` into the ``ContextVar`` so any code
   downstream (handlers, helpers, ``@trace`` decorators) can read the
   current ``trace_id`` / ``span_id`` without being passed them explicitly.
5. **Increments** the ``zerotel_requests_in_flight`` gauge.
6. **Records** the ``zerotel_requests_total`` counter and
   ``zerotel_request_duration_seconds`` histogram after the response.
7. **Sets** span status to ``ERROR`` for 5xx responses and records the
   exception on the span when one propagates.
8. **Ends** the span and decrements the in-flight gauge — guaranteed via a
   ``try / finally`` block even if an unhandled exception escapes.

The middleware is added to the FastAPI app automatically by ``Zerotel``; you
should not need to add it manually.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from opentelemetry.propagate import extract as otel_extract
from opentelemetry.trace import SpanKind, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

from zerotel._config import ZerotelConfig
from zerotel._context import RequestContext, request_context_var
from zerotel._metrics import REQUEST_COUNTER, REQUEST_DURATION, REQUESTS_IN_FLIGHT


class ZerotelMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that auto-instruments every HTTP request.

    Added to the application automatically by ``Zerotel(app, ...)``. You do
    not need to add it manually.

    Args:
        app: The ASGI application to wrap.
        config: Resolved ``ZerotelConfig`` instance.
        tracer: OpenTelemetry ``Tracer`` obtained from the configured provider.
    """

    def __init__(self, app: ASGIApp, config: ZerotelConfig, tracer: otel_trace.Tracer) -> None:
        super().__init__(app)
        self._config = config
        self._tracer = tracer

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_route_template(self, request: Request) -> str:
        """Return the matched route template, falling back to the raw path.

        Using the template (``/users/{id}``) rather than the resolved path
        (``/users/42``) keeps metric cardinality under control — otherwise
        every unique user ID would create a new label combination.

        Args:
            request: The incoming Starlette request.

        Returns:
            A string like ``"/users/{id}"`` or ``"/unknown"`` if no route
            matched (e.g. a 404).
        """
        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return getattr(route, "path", request.url.path)
        return request.url.path

    def _should_skip(self, path: str) -> bool:
        """Return ``True`` if this path should be excluded from instrumentation.

        Args:
            path: The raw URL path of the request (e.g. ``"/health"``).

        Returns:
            ``True`` when the path is in ``ZerotelConfig.exclude_paths``.
        """
        return path in self._config.exclude_paths

    # ------------------------------------------------------------------
    # Middleware entry point
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process one HTTP request through the full observability pipeline.

        Args:
            request: The incoming HTTP request.
            call_next: Async callable that invokes the next middleware or the
                route handler and returns the response.

        Returns:
            The HTTP response, unchanged — Zerotel is purely observational.
        """
        path = request.url.path

        # Fast path — skip excluded paths (health checks, /metrics, etc.)
        if self._should_skip(path):
            return await call_next(request)

        method = request.method
        route = self._get_route_template(request)

        # ------------------------------------------------------------------
        # Distributed trace propagation
        # Extract the parent context from W3C traceparent / tracestate headers
        # so that if this service is called by another instrumented service,
        # the spans are linked into the same distributed trace.
        # ------------------------------------------------------------------
        carrier = dict(request.headers)
        parent_ctx = otel_extract(carrier)
        token = otel_context.attach(parent_ctx)

        start_time = time.perf_counter()

        # Track concurrent requests
        REQUESTS_IN_FLIGHT.labels(method=method, route=route).inc()

        span_name = f"{method} {route}"

        with self._tracer.start_as_current_span(
            span_name,
            kind=SpanKind.SERVER,
            attributes={
                "http.method": method,
                "http.route": route,
                "http.url": str(request.url),
                "http.scheme": request.url.scheme,
                "http.host": request.url.hostname or "",
                "net.peer.ip": request.client.host if request.client else "",
            },
        ) as span:
            # Populate the per-request ContextVar so downstream code can read
            # trace_id / span_id without being passed them explicitly.
            span_ctx = span.get_span_context()
            trace_id_hex = format(span_ctx.trace_id, "032x")
            span_id_hex = format(span_ctx.span_id, "016x")

            request_id = request.headers.get("x-request-id", trace_id_hex)
            ctx = RequestContext(
                trace_id=trace_id_hex,
                span_id=span_id_hex,
                service_name=self._config.service_name,
                request_id=request_id,
            )
            ctx_token = request_context_var.set(ctx)

            # Optionally capture the request body as a span attribute.
            # Off by default — bodies often contain PII.
            if self._config.log_request_body:
                body = await request.body()
                span.set_attribute("http.request_body", body.decode("utf-8", errors="replace"))

            try:
                response = await call_next(request)
                status_code = response.status_code

                # Annotate the span with the response status
                span.set_attribute("http.status_code", status_code)

                # Mark server errors as span errors so they surface in the
                # trace backend's error views
                if status_code >= 500:
                    span.set_status(StatusCode.ERROR, f"HTTP {status_code}")
                else:
                    span.set_status(StatusCode.OK)

                return response

            except Exception as exc:
                # Record unhandled exceptions on the span before re-raising
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                status_code = 500
                raise

            finally:
                duration = time.perf_counter() - start_time

                # Always update metrics, even if an exception escaped
                REQUEST_COUNTER.labels(
                    method=method,
                    route=route,
                    status=status_code,
                ).inc()
                REQUEST_DURATION.labels(method=method, route=route).observe(duration)
                REQUESTS_IN_FLIGHT.labels(method=method, route=route).dec()

                # Clean up the request context and OTEL context
                request_context_var.reset(ctx_token)
                otel_context.detach(token)
