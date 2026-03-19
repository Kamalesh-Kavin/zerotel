"""
zerotel
~~~~~~~

Zero-config observability SDK for Python services.

Wraps a FastAPI application with OpenTelemetry distributed tracing, Prometheus
metrics, and structured JSON logging — all wired together with a single call:

    from zerotel import Zerotel
    Zerotel(app, service_name="my-api")

For full control over every setting, pass a ``ZerotelConfig`` instance:

    from zerotel import Zerotel, ZerotelConfig
    Zerotel(app, config=ZerotelConfig(
        service_name="my-api",
        otlp_endpoint="http://otel-collector:4317",
        enable_metrics=True,
        enable_logging=True,
        exclude_paths=["/health", "/metrics"],
        log_request_body=False,
        trace_sample_rate=1.0,
    ))

Individual functions can be wrapped in a named child span using the ``@trace``
decorator, which works transparently on both ``async def`` and ``def``:

    from zerotel import trace

    @trace(name="send-email")
    async def send_email(user_id: int): ...

    @trace
    def compute_score(data): ...

Public API
----------
- ``Zerotel``       — Main SDK entrypoint; instruments a FastAPI app.
- ``ZerotelConfig`` — Typed configuration dataclass with sensible defaults.
- ``trace``         — Decorator that adds a child span to any function.
- ``get_trace_id``  — Helper to read the current trace ID anywhere.
- ``get_span_id``   — Helper to read the current span ID anywhere.
"""

from __future__ import annotations

from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from prometheus_client import make_asgi_app
from starlette.routing import Mount

from zerotel._config import ZerotelConfig
from zerotel._context import get_span_id, get_trace_id
from zerotel._decorators import trace
from zerotel._logging import configure_logging
from zerotel._middleware import ZerotelMiddleware

# --------------------------------------------------------------------------- #
# Re-export the full public surface so users can do:                          #
#   from zerotel import Zerotel, ZerotelConfig, trace, get_trace_id           #
# --------------------------------------------------------------------------- #
__all__ = [
    "Zerotel",
    "ZerotelConfig",
    "get_span_id",
    "get_trace_id",
    "trace",
]

__version__ = "0.1.0"


class Zerotel:
    """Main SDK entrypoint — instruments a FastAPI application in one call.

    ``Zerotel`` wires together three observability pillars:

    1. **Traces** — every request becomes a root span exported to an OTEL
       Collector via gRPC (OTLP).  Child spans can be added via ``@trace``.
    2. **Metrics** — Prometheus counters, histograms, and gauges are collected
       per-request and exposed on the ``/metrics`` endpoint.
    3. **Logs** — structlog is configured to emit structured JSON lines with
       ``trace_id`` and ``span_id`` auto-injected so logs correlate to traces.

    Args:
        app: The FastAPI (or Starlette) application to instrument.
        service_name: Shorthand for setting ``ZerotelConfig.service_name``.
            Ignored when ``config`` is provided explicitly.
        config: A fully-populated ``ZerotelConfig`` instance.  When omitted,
            a config is constructed from ``service_name`` (or the default
            ``"unknown-service"``).

    Raises:
        ValueError: If both ``service_name`` and ``config`` are supplied, or if
            the resolved config fails its own ``__post_init__`` validation.

    Example::

        from fastapi import FastAPI
        from zerotel import Zerotel

        app = FastAPI()
        Zerotel(app, service_name="payments-api")
    """

    def __init__(
        self,
        app: object,  # FastAPI / Starlette app — avoid hard dep on FastAPI type
        *,
        service_name: str | None = None,
        config: ZerotelConfig | None = None,
    ) -> None:
        # ------------------------------------------------------------------
        # 1. Resolve configuration
        # ------------------------------------------------------------------
        if config is not None and service_name is not None:
            raise ValueError(
                "Pass either 'service_name' or 'config', not both. "
                "When using ZerotelConfig, set service_name inside it."
            )

        if config is None:
            # Build a minimal config from just a name, using all other defaults.
            config = ZerotelConfig(service_name=service_name or "unknown-service")

        self.config = config

        # ------------------------------------------------------------------
        # 2. Structured JSON logging (structlog)
        # ------------------------------------------------------------------
        if config.enable_logging:
            configure_logging(service_name=config.service_name)

        # ------------------------------------------------------------------
        # 3. OpenTelemetry tracing
        # ------------------------------------------------------------------
        tracer: otel_trace.Tracer

        if config.enable_traces:
            tracer = self._setup_tracing(config)
        else:
            # Use the no-op tracer so @trace decorators still work safely
            # without exporting anything.
            tracer = otel_trace.get_tracer(config.service_name)

        # ------------------------------------------------------------------
        # 4. ASGI middleware — wraps every request
        # ------------------------------------------------------------------
        # FastAPI / Starlette apps expose ``add_middleware``.
        if hasattr(app, "add_middleware"):
            app.add_middleware(ZerotelMiddleware, config=config, tracer=tracer)  # type: ignore

        # ------------------------------------------------------------------
        # 5. Prometheus /metrics endpoint
        # ------------------------------------------------------------------
        if config.enable_metrics:
            self._setup_metrics(app, config)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_tracing(config: ZerotelConfig) -> otel_trace.Tracer:
        """Configure the OpenTelemetry SDK and return a ``Tracer``.

        Sets up:
        - A ``Resource`` with service name and version (visible in Grafana/Tempo).
        - A ``TraceIdRatioBased`` sampler to honour ``trace_sample_rate``.
        - A ``BatchSpanProcessor`` that exports to the OTLP gRPC endpoint.

        The provider is registered globally so that ``otel_trace.get_tracer()``
        calls anywhere in the application use it automatically.

        Args:
            config: Resolved ``ZerotelConfig`` instance.

        Returns:
            A ``Tracer`` scoped to the ``"zerotel"`` instrumentation library.
        """
        # Resource attributes appear as metadata in Grafana Tempo and other
        # backends — they identify *which* service produced a given trace.
        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
            }
        )

        # Sampler: TraceIdRatioBased(1.0) = sample everything.
        # Lower this (e.g. 0.1) to sample only 10% of requests in production.
        sampler = TraceIdRatioBased(config.trace_sample_rate)

        provider = TracerProvider(resource=resource, sampler=sampler)

        # BatchSpanProcessor buffers spans and exports them in the background —
        # much lower overhead than SimpleSpanProcessor (which blocks per-span).
        exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Register as the global provider so all otel_trace.get_tracer() calls
        # across the whole process use this configured provider.
        otel_trace.set_tracer_provider(provider)

        return otel_trace.get_tracer("zerotel", __version__)

    @staticmethod
    def _setup_metrics(app: object, config: ZerotelConfig) -> None:
        """Mount the Prometheus metrics ASGI app at ``config.metrics_endpoint``.

        Prometheus scrapes this endpoint periodically to collect the counters,
        histograms, and gauges defined in ``zerotel._metrics``.

        The endpoint is intentionally excluded from tracing via
        ``ZerotelConfig.exclude_paths`` (``/metrics`` is in the default list).

        Args:
            app: The FastAPI / Starlette application.
            config: Resolved ``ZerotelConfig`` instance.
        """
        # ``make_asgi_app()`` returns a minimal ASGI app that renders the
        # Prometheus text exposition format when called.
        metrics_app = make_asgi_app()

        # Mount it at the configured path.  FastAPI/Starlette support mounting
        # sub-applications via app.mount() or by appending to app.routes.
        if hasattr(app, "mount"):
            app.mount(config.metrics_endpoint, metrics_app)  # type: ignore
        elif hasattr(app, "routes"):
            # Fallback: directly append a Mount to the route list.
            app.routes.append(Mount(config.metrics_endpoint, app=metrics_app))  # type: ignore
