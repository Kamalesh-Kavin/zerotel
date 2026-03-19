"""
zerotel.integrations.flask
~~~~~~~~~~~~~~~~~~~~~~~~~~

Flask adapter for Zerotel.

Provides ``instrument_flask()`` which wires OpenTelemetry traces, Prometheus
metrics, and structured logging into a Flask WSGI application using Flask's
``before_request`` / ``after_request`` / ``teardown_request`` hooks.

Install the extra dependency first::

    pip install "zerotel[flask]"

Usage::

    from flask import Flask
    from zerotel import ZerotelConfig
    from zerotel.integrations.flask import instrument_flask

    app = Flask(__name__)
    instrument_flask(
        app,
        config=ZerotelConfig(service_name="my-flask-api"),
    )

After calling ``instrument_flask()``:

* Every request creates a root OpenTelemetry span.
* ``zerotel_requests_total``, ``zerotel_request_duration_seconds``, and
  ``zerotel_requests_in_flight`` are updated on every request.
* Structured JSON logs include ``trace_id`` and ``span_id``.
* A ``/metrics`` endpoint is registered for Prometheus scraping (unless the
  path is already taken or ``config.enable_metrics`` is ``False``).

Note on threading
~~~~~~~~~~~~~~~~~
Flask is WSGI (synchronous) and typically runs on a threaded server (gunicorn,
waitress).  Unlike the ASGI middleware which uses ``contextvars`` naturally,
here we use Flask's ``g`` object which is request-local per thread.
"""

from __future__ import annotations

import time
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.trace import SpanKind, StatusCode

from zerotel._config import ZerotelConfig
from zerotel._context import RequestContext, request_context_var
from zerotel._logging import configure_logging
from zerotel._metrics import REQUEST_COUNTER, REQUEST_DURATION, REQUESTS_IN_FLIGHT

# Flask is an optional dependency
try:
    from flask import Response, g, request

    _FLASK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FLASK_AVAILABLE = False


def instrument_flask(app: Any, config: ZerotelConfig | None = None) -> None:
    """Instrument a Flask application with Zerotel observability.

    Registers ``before_request``, ``after_request``, and ``teardown_request``
    hooks on ``app`` to provide automatic tracing, metrics, and structured
    logging for every HTTP request.

    Args:
        app: A ``flask.Flask`` application instance.
        config: Optional ``ZerotelConfig``.  Defaults to
            ``ZerotelConfig(service_name="flask-app")`` when not provided.

    Raises:
        ImportError: When the ``[flask]`` extra is not installed.

    Example::

        from flask import Flask
        from zerotel import ZerotelConfig
        from zerotel.integrations.flask import instrument_flask

        app = Flask(__name__)
        instrument_flask(app, ZerotelConfig(service_name="my-api"))
    """
    if not _FLASK_AVAILABLE:
        raise ImportError(
            "Flask integration requires the [flask] extra. "
            "Install it with:  pip install 'zerotel[flask]'"
        )

    cfg = config or ZerotelConfig(service_name="flask-app")

    if cfg.enable_logging:
        configure_logging(service_name=cfg.service_name)

    tracer = otel_trace.get_tracer(cfg.service_name)

    # ------------------------------------------------------------------
    # before_request — start span, populate context
    # ------------------------------------------------------------------
    @app.before_request  # type: ignore[misc]
    def _before() -> None:
        path = request.path

        if path in cfg.exclude_paths:
            g._zerotel_skip = True
            return

        g._zerotel_skip = False
        g._zerotel_start = time.perf_counter()

        method = request.method
        route = request.url_rule.rule if request.url_rule else path

        REQUESTS_IN_FLIGHT.labels(method=method, route=route).inc()

        span = tracer.start_span(
            name=f"{method} {route}",
            kind=SpanKind.SERVER,
            attributes={
                "http.method": method,
                "http.route": route,
                "http.url": request.url,
                "http.scheme": request.scheme,
            },
        )

        g._zerotel_span = span
        span_ctx = span.get_span_context()
        trace_id_hex = format(span_ctx.trace_id, "032x")
        span_id_hex = format(span_ctx.span_id, "016x")

        ctx = RequestContext(
            trace_id=trace_id_hex,
            span_id=span_id_hex,
            service_name=cfg.service_name,
            request_id=request.headers.get("x-request-id", trace_id_hex),
        )
        g._zerotel_ctx_token = request_context_var.set(ctx)

    # ------------------------------------------------------------------
    # after_request — record metrics, close span
    # ------------------------------------------------------------------
    @app.after_request  # type: ignore[misc]
    def _after(response: Response) -> Response:
        if getattr(g, "_zerotel_skip", True):
            return response

        method = request.method
        route = request.url_rule.rule if request.url_rule else request.path
        status = response.status_code
        duration = time.perf_counter() - g._zerotel_start

        span: otel_trace.Span = g._zerotel_span
        span.set_attribute("http.status_code", status)
        if status >= 500:
            span.set_status(StatusCode.ERROR, f"HTTP {status}")
        else:
            span.set_status(StatusCode.OK)
        span.end()

        REQUEST_COUNTER.labels(method=method, route=route, status=status).inc()
        REQUEST_DURATION.labels(method=method, route=route).observe(duration)
        REQUESTS_IN_FLIGHT.labels(method=method, route=route).dec()

        ctx_token = getattr(g, "_zerotel_ctx_token", None)
        if ctx_token is not None:
            request_context_var.reset(ctx_token)

        return response

    # ------------------------------------------------------------------
    # teardown_request — handle uncaught exceptions
    # ------------------------------------------------------------------
    @app.teardown_request  # type: ignore[misc]
    def _teardown(exc: BaseException | None) -> None:
        if getattr(g, "_zerotel_skip", True) or exc is None:
            return

        span: otel_trace.Span = getattr(g, "_zerotel_span", None)
        if span is None:
            return

        span.set_status(StatusCode.ERROR, str(exc))
        span.record_exception(exc)
        # span.end() will be called by _after — do not double-end

    # ------------------------------------------------------------------
    # /metrics endpoint (Prometheus scrape)
    # ------------------------------------------------------------------
    if cfg.enable_metrics:
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            @app.route(cfg.metrics_endpoint)  # type: ignore[misc]
            def _metrics_view() -> Response:
                """Prometheus metrics scrape endpoint."""
                return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

        except ImportError:  # pragma: no cover
            pass  # prometheus_client always present as a core dependency
