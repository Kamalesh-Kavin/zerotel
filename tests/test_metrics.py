"""
tests/test_metrics.py
~~~~~~~~~~~~~~~~~~~~~

Unit tests for ``zerotel._metrics`` — the Prometheus metric definitions.

Tests verify:
- The three metrics exist and have the correct names
- Labels are correct
- Counter increments work
- Histogram observations work
- Gauge increments and decrements work

Why not test values after a real HTTP request?
Prometheus counters are process-global and cumulative.  Testing exact values
after HTTP requests would require test isolation at the process level, which
is expensive.  Instead we test the metric objects directly with synthetic
label combinations that are unlikely to collide with other test runs.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from zerotel._metrics import REQUEST_COUNTER, REQUEST_DURATION, REQUESTS_IN_FLIGHT

# Synthetic label values that won't appear in any other test
_METHOD = "PATCH"
_ROUTE = "/test-metrics-only"
_STATUS = 418  # I'm a teapot — unlikely to be used by other tests


class TestRequestCounter:
    """Tests for ``zerotel_requests_total`` Counter."""

    def test_metric_name(self) -> None:
        """The counter must be registered with the correct name."""
        names = {m.name for m in REGISTRY.collect()}
        # prometheus_client appends _total automatically for counters
        assert "zerotel_requests" in names or "zerotel_requests_total" in names

    def test_counter_increments(self) -> None:
        """Each ``inc()`` call must increase the counter value by 1."""

        # Collect baseline sample value via public collect() API
        def _get_count() -> float:
            for metric in REGISTRY.collect():
                if "zerotel_requests" in metric.name:
                    for sample in metric.samples:
                        if (
                            sample.labels.get("method") == _METHOD
                            and sample.labels.get("route") == _ROUTE
                            and str(sample.labels.get("status")) == str(_STATUS)
                            and sample.name.endswith("_total")
                        ):
                            return sample.value
            return 0.0

        before = _get_count()
        REQUEST_COUNTER.labels(method=_METHOD, route=_ROUTE, status=_STATUS).inc()
        assert _get_count() == before + 1


class TestRequestDuration:
    """Tests for ``zerotel_request_duration_seconds`` Histogram."""

    def test_metric_name(self) -> None:
        """The histogram must be registered with the correct name."""
        names = {m.name for m in REGISTRY.collect()}
        assert "zerotel_request_duration_seconds" in names

    def test_observation_increases_count(self) -> None:
        """Observing a value must increase the histogram's sample count."""

        def _get_count() -> float:
            for metric in REGISTRY.collect():
                if metric.name == "zerotel_request_duration_seconds":
                    for sample in metric.samples:
                        if (
                            sample.labels.get("method") == _METHOD
                            and sample.labels.get("route") == _ROUTE
                            and sample.name.endswith("_count")
                        ):
                            return sample.value
            return 0.0

        before = _get_count()
        REQUEST_DURATION.labels(method=_METHOD, route=_ROUTE).observe(0.042)
        assert _get_count() == before + 1

    def test_observation_increases_sum(self) -> None:
        """Observing a value must add to the histogram's running sum."""

        def _get_sum() -> float:
            for metric in REGISTRY.collect():
                if metric.name == "zerotel_request_duration_seconds":
                    for sample in metric.samples:
                        if (
                            sample.labels.get("method") == _METHOD
                            and sample.labels.get("route") == _ROUTE
                            and sample.name.endswith("_sum")
                        ):
                            return sample.value
            return 0.0

        before = _get_sum()
        REQUEST_DURATION.labels(method=_METHOD, route=_ROUTE).observe(0.1)
        assert _get_sum() == pytest.approx(before + 0.1, rel=1e-6)


class TestRequestsInFlight:
    """Tests for ``zerotel_requests_in_flight`` Gauge."""

    def test_metric_name(self) -> None:
        """The gauge must be registered with the correct name."""
        names = {m.name for m in REGISTRY.collect()}
        assert "zerotel_requests_in_flight" in names

    def test_gauge_inc_and_dec(self) -> None:
        """Increment followed by decrement must return to the original value."""

        def _get_value() -> float:
            for metric in REGISTRY.collect():
                if metric.name == "zerotel_requests_in_flight":
                    for sample in metric.samples:
                        if (
                            sample.labels.get("method") == _METHOD
                            and sample.labels.get("route") == _ROUTE
                        ):
                            return sample.value
            return 0.0

        before = _get_value()
        REQUESTS_IN_FLIGHT.labels(method=_METHOD, route=_ROUTE).inc()
        assert _get_value() == before + 1
        REQUESTS_IN_FLIGHT.labels(method=_METHOD, route=_ROUTE).dec()
        assert _get_value() == before
