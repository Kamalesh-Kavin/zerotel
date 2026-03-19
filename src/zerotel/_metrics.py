"""
zerotel._metrics
~~~~~~~~~~~~~~~~

Prometheus metrics definitions for Zerotel.

Three standard HTTP metrics are registered once at module import time and
shared across all requests:

* ``zerotel_requests_total``        — Counter, labelled by method/route/status
* ``zerotel_request_duration_seconds`` — Histogram, labelled by method/route
* ``zerotel_requests_in_flight``    — Gauge, labelled by method/route

All metric names are prefixed with ``zerotel_`` to avoid collisions with
application-defined metrics.

The Prometheus ``/metrics`` scrape endpoint is added to the FastAPI app by
``ZerotelMiddleware`` — this module is purely the metric definitions.

Usage (internal)::

    from zerotel._metrics import (
        REQUEST_COUNTER,
        REQUEST_DURATION,
        REQUESTS_IN_FLIGHT,
    )

    REQUEST_COUNTER.labels(method="GET", route="/users/{id}", status=200).inc()
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Label names reused across all metrics
# ---------------------------------------------------------------------------
_HTTP_LABELS = ["method", "route", "status"]
_HTTP_LABELS_NO_STATUS = ["method", "route"]

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

REQUEST_COUNTER = Counter(
    name="zerotel_requests_total",
    documentation=(
        "Total number of HTTP requests processed, partitioned by HTTP method, "
        "route template (e.g. '/users/{id}' not '/users/42'), and response "
        "status code."
    ),
    labelnames=_HTTP_LABELS,
)
"""Counter: incremented once per completed request."""

REQUEST_DURATION = Histogram(
    name="zerotel_request_duration_seconds",
    documentation=(
        "End-to-end request latency in seconds, from the moment the first byte "
        "of the request is received until the response is fully sent. "
        "Labelled by method and route template. "
        "Use the ``_bucket``, ``_sum``, and ``_count`` suffixes to compute "
        "percentiles (p50, p95, p99) in Prometheus/Grafana."
    ),
    labelnames=_HTTP_LABELS_NO_STATUS,
    # Default Prometheus buckets cover 5ms-10s.  Tighten for low-latency APIs.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
"""Histogram: records request duration with pre-defined latency buckets."""

REQUESTS_IN_FLIGHT = Gauge(
    name="zerotel_requests_in_flight",
    documentation=(
        "Number of requests currently being processed (started but not yet "
        "responded to). A sustained non-zero value under low traffic usually "
        "indicates a slow handler or a hung dependency."
    ),
    labelnames=_HTTP_LABELS_NO_STATUS,
)
"""Gauge: incremented on request start, decremented on request end."""
