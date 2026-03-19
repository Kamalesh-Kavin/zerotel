"""
tests/test_config.py
~~~~~~~~~~~~~~~~~~~~

Unit tests for ``zerotel._config.ZerotelConfig``.

Tests cover:
- Default values are sensible
- Explicit overrides work
- Validation rejects bad values at construction time
"""

from __future__ import annotations

import pytest

from zerotel._config import ZerotelConfig


class TestZerotelConfigDefaults:
    """Verify every default value matches the documented spec."""

    def test_service_name_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.service_name == "unknown-service"

    def test_service_version_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.service_version == "0.0.0"

    def test_otlp_endpoint_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.otlp_endpoint == "http://localhost:4317"

    def test_enable_traces_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.enable_traces is True

    def test_enable_metrics_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.enable_metrics is True

    def test_enable_logging_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.enable_logging is True

    def test_exclude_paths_default(self) -> None:
        cfg = ZerotelConfig()
        assert "/health" in cfg.exclude_paths
        assert "/metrics" in cfg.exclude_paths

    def test_log_request_body_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.log_request_body is False

    def test_trace_sample_rate_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.trace_sample_rate == 1.0

    def test_metrics_endpoint_default(self) -> None:
        cfg = ZerotelConfig()
        assert cfg.metrics_endpoint == "/metrics"


class TestZerotelConfigOverrides:
    """Verify that all fields accept explicit values."""

    def test_service_name_override(self) -> None:
        cfg = ZerotelConfig(service_name="payments-api")
        assert cfg.service_name == "payments-api"

    def test_full_override(self) -> None:
        cfg = ZerotelConfig(
            service_name="test",
            service_version="2.3.4",
            otlp_endpoint="http://collector:4317",
            enable_traces=False,
            enable_metrics=False,
            enable_logging=False,
            exclude_paths=["/ping"],
            log_request_body=True,
            trace_sample_rate=0.5,
            metrics_endpoint="/prom",
        )
        assert cfg.service_version == "2.3.4"
        assert cfg.otlp_endpoint == "http://collector:4317"
        assert cfg.enable_traces is False
        assert cfg.enable_metrics is False
        assert cfg.enable_logging is False
        assert cfg.exclude_paths == ["/ping"]
        assert cfg.log_request_body is True
        assert cfg.trace_sample_rate == 0.5
        assert cfg.metrics_endpoint == "/prom"


class TestZerotelConfigValidation:
    """Verify that bad values raise ``ValueError`` at construction time."""

    def test_empty_service_name_raises(self) -> None:
        with pytest.raises(ValueError, match="service_name"):
            ZerotelConfig(service_name="")

    def test_sample_rate_above_1_raises(self) -> None:
        with pytest.raises(ValueError, match="trace_sample_rate"):
            ZerotelConfig(trace_sample_rate=1.1)

    def test_sample_rate_below_0_raises(self) -> None:
        with pytest.raises(ValueError, match="trace_sample_rate"):
            ZerotelConfig(trace_sample_rate=-0.1)

    def test_metrics_endpoint_without_slash_raises(self) -> None:
        with pytest.raises(ValueError, match="metrics_endpoint"):
            ZerotelConfig(metrics_endpoint="metrics")

    def test_boundary_sample_rate_0(self) -> None:
        cfg = ZerotelConfig(trace_sample_rate=0.0)
        assert cfg.trace_sample_rate == 0.0

    def test_boundary_sample_rate_1(self) -> None:
        cfg = ZerotelConfig(trace_sample_rate=1.0)
        assert cfg.trace_sample_rate == 1.0
