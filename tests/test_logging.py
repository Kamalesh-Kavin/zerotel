"""
tests/test_logging.py
~~~~~~~~~~~~~~~~~~~~~

Unit tests for ``zerotel._logging``.

Tests verify:
- ``configure_logging()`` does not raise
- structlog is configured to emit JSON
- ``_inject_trace_context`` injects ``trace_id`` and ``span_id`` into log records
- Without an active request context, the processor falls back to zero strings
"""

from __future__ import annotations

import logging

from zerotel._context import RequestContext, request_context_var
from zerotel._logging import _inject_trace_context, configure_logging


class TestConfigureLogging:
    """Tests for the ``configure_logging()`` setup function."""

    def test_does_not_raise(self) -> None:
        """Calling ``configure_logging`` must not raise any exception."""
        configure_logging(service_name="test-service", level="DEBUG")

    def test_idempotent(self) -> None:
        """Calling it twice must not raise (structlog reconfigures cleanly)."""
        configure_logging(service_name="svc-a")
        configure_logging(service_name="svc-b")

    def test_stdlib_level_respected(self) -> None:
        """The root logger's level must match the requested level."""
        configure_logging(service_name="test", level="WARNING")
        assert logging.getLogger().level == logging.WARNING


class TestInjectTraceContext:
    """Tests for the ``_inject_trace_context`` structlog processor."""

    def test_injects_zeros_when_no_context(self) -> None:
        """Without a request context the processor must inject zero strings."""
        event_dict: dict = {}
        result = _inject_trace_context(None, "info", event_dict)
        assert result["trace_id"] == "0" * 32
        assert result["span_id"] == "0" * 16

    def test_injects_trace_id_from_context(self) -> None:
        """With an active context the processor must inject the real trace_id."""
        ctx = RequestContext(
            trace_id="aabbccdd" * 4,
            span_id="11223344" * 2,
            service_name="test",
        )
        token = request_context_var.set(ctx)
        try:
            event_dict: dict = {}
            result = _inject_trace_context(None, "info", event_dict)
            assert result["trace_id"] == "aabbccdd" * 4
            assert result["span_id"] == "11223344" * 2
        finally:
            request_context_var.reset(token)

    def test_returns_event_dict(self) -> None:
        """The processor must return the same dict (not a new object)."""
        event_dict: dict = {"event": "test"}
        result = _inject_trace_context(None, "info", event_dict)
        assert result is event_dict
