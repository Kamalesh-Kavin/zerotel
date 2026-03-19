"""
zerotel._config
~~~~~~~~~~~~~~~

Configuration dataclass for Zerotel.

All settings have sensible defaults so the minimal usage is simply:

    Zerotel(app, service_name="my-api")

For full control pass a ``ZerotelConfig`` instance:

    Zerotel(app, config=ZerotelConfig(
        service_name="my-api",
        otlp_endpoint="http://otel-collector:4317",
        enable_metrics=True,
        enable_logging=True,
        exclude_paths=["/health", "/metrics"],
    ))
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ZerotelConfig:
    """Central configuration for the Zerotel SDK.

    Attributes:
        service_name: Logical name of the service. Appears in every trace,
            metric label, and log line. Required — no default.
        service_version: Optional semver string attached to all telemetry.
            Useful for correlating a spike in errors to a specific deploy.
        otlp_endpoint: gRPC endpoint of the OpenTelemetry Collector.
            Defaults to ``http://localhost:4317`` (the standard OTEL Collector
            port). Override to point at a remote collector or a managed
            backend that accepts OTLP (e.g. Grafana Cloud, Honeycomb, Datadog).
        enable_traces: When ``True`` (default), every HTTP request is captured
            as an OpenTelemetry root span and exported to the collector.
        enable_metrics: When ``True`` (default), Prometheus counters, histograms,
            and gauges are collected and exposed on ``/metrics``.
        enable_logging: When ``True`` (default), structlog is configured to emit
            structured JSON logs with ``trace_id`` and ``span_id`` auto-injected
            on every log line.
        exclude_paths: List of URL paths to skip entirely — no traces, no metrics
            incremented. Useful for health-check and liveness endpoints that
            would otherwise flood your trace backend.
        log_request_body: When ``True``, the raw request body is captured as a
            span attribute. **Off by default** — request bodies often contain
            PII or secrets and should only be enabled in controlled environments.
        trace_sample_rate: Fraction of requests to sample, between 0.0 and 1.0.
            Defaults to 1.0 (sample everything). Lower this in high-throughput
            production environments to control costs.
        metrics_endpoint: Path at which the Prometheus ``/metrics`` endpoint is
            mounted. Defaults to ``/metrics``. Must start with ``/``.
    """

    # --- Identity ---------------------------------------------------------
    service_name: str = "unknown-service"
    service_version: str = "0.0.0"

    # --- Export -----------------------------------------------------------
    otlp_endpoint: str = "http://localhost:4317"

    # --- Feature flags ----------------------------------------------------
    enable_traces: bool = True
    enable_metrics: bool = True
    enable_logging: bool = True

    # --- Filtering --------------------------------------------------------
    exclude_paths: list[str] = field(default_factory=lambda: ["/health", "/metrics"])

    # --- Advanced ---------------------------------------------------------
    log_request_body: bool = False
    trace_sample_rate: float = 1.0
    metrics_endpoint: str = "/metrics"

    def __post_init__(self) -> None:
        """Validate config values at construction time to fail fast."""
        if not self.service_name:
            raise ValueError("ZerotelConfig.service_name must not be empty.")
        if not (0.0 <= self.trace_sample_rate <= 1.0):
            raise ValueError(
                f"ZerotelConfig.trace_sample_rate must be between 0.0 and 1.0, "
                f"got {self.trace_sample_rate!r}."
            )
        if not self.metrics_endpoint.startswith("/"):
            raise ValueError(
                f"ZerotelConfig.metrics_endpoint must start with '/', "
                f"got {self.metrics_endpoint!r}."
            )
