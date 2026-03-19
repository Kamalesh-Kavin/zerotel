"""
tests/test_context.py
~~~~~~~~~~~~~~~~~~~~~

Unit tests for ``zerotel._context``.

Tests verify:
- ``get_request_context()`` returns ``None`` outside a request
- ``get_trace_id()`` returns all-zeros fallback outside a request
- ``get_span_id()`` returns all-zeros fallback outside a request
- Setting a ``RequestContext`` makes all helpers return correct values
- The ContextVar is properly reset after cleanup
"""

from __future__ import annotations

from zerotel._context import (
    RequestContext,
    get_request_context,
    get_span_id,
    get_trace_id,
    request_context_var,
)


class TestRequestContextOutsideRequest:
    """Verify safe fallback behaviour when no request context is active."""

    def test_get_request_context_returns_none(self) -> None:
        assert get_request_context() is None

    def test_get_trace_id_returns_zero_string(self) -> None:
        assert get_trace_id() == "0" * 32

    def test_get_span_id_returns_zero_string(self) -> None:
        assert get_span_id() == "0" * 16


class TestRequestContextInsideRequest:
    """Verify correct values are returned when a context is set."""

    def test_get_request_context_returns_context(self) -> None:
        ctx = RequestContext(trace_id="a" * 32, span_id="b" * 16, service_name="svc")
        token = request_context_var.set(ctx)
        try:
            assert get_request_context() is ctx
        finally:
            request_context_var.reset(token)

    def test_get_trace_id_returns_correct_value(self) -> None:
        ctx = RequestContext(trace_id="cafe" * 8, span_id="dead" * 4, service_name="svc")
        token = request_context_var.set(ctx)
        try:
            assert get_trace_id() == "cafe" * 8
        finally:
            request_context_var.reset(token)

    def test_get_span_id_returns_correct_value(self) -> None:
        ctx = RequestContext(trace_id="a" * 32, span_id="b" * 16, service_name="svc")
        token = request_context_var.set(ctx)
        try:
            assert get_span_id() == "b" * 16
        finally:
            request_context_var.reset(token)

    def test_context_cleaned_up_after_reset(self) -> None:
        ctx = RequestContext(trace_id="a" * 32, span_id="b" * 16, service_name="svc")
        token = request_context_var.set(ctx)
        request_context_var.reset(token)
        assert get_request_context() is None


class TestRequestContextDataclass:
    """Tests for the ``RequestContext`` dataclass itself."""

    def test_request_id_defaults_to_trace_id(self) -> None:
        ctx = RequestContext(trace_id="a" * 32, span_id="b" * 16, service_name="svc")
        assert ctx.request_id == "a" * 32

    def test_explicit_request_id(self) -> None:
        ctx = RequestContext(
            trace_id="a" * 32, span_id="b" * 16, service_name="svc", request_id="req-123"
        )
        assert ctx.request_id == "req-123"
