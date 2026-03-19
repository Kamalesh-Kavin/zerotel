"""
tests/test_decorators.py
~~~~~~~~~~~~~~~~~~~~~~~~

Unit tests for the ``@trace`` decorator (``zerotel._decorators``).

Tests cover:
- ``@trace`` without parentheses on sync functions
- ``@trace`` without parentheses on async functions
- ``@trace(name="...")`` with an explicit span name
- Exceptions propagate correctly (span is marked ERROR, exception re-raised)
- The decorator preserves the function's ``__name__`` and ``__doc__``
- Both sync and async wrappers produce finished spans
"""

from __future__ import annotations

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from tests.conftest import _force_reset_otel_provider
from zerotel._decorators import trace

# ---------------------------------------------------------------------------
# Fixture: in-memory span exporter
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def in_memory_provider() -> InMemorySpanExporter:
    """Install a fresh in-memory OTel provider before each test.

    Uses the internal reset so the provider can actually be swapped even
    when another test already configured the global provider.

    Returns the exporter so individual tests can inspect emitted spans.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Reset the global sentinel so set_tracer_provider is accepted
    _force_reset_otel_provider()
    otel_trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture()
def exporter(in_memory_provider: InMemorySpanExporter) -> InMemorySpanExporter:
    """Expose the in-memory exporter to tests that need to inspect spans."""
    return in_memory_provider


# ---------------------------------------------------------------------------
# Sync function tests
# ---------------------------------------------------------------------------


class TestTraceSyncFunction:
    """Tests for ``@trace`` on synchronous (def) functions."""

    def test_bare_decorator_runs_function(self) -> None:
        """The decorated function must still return its original value."""

        @trace
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    def test_bare_decorator_emits_span(self, exporter: InMemorySpanExporter) -> None:
        """Each call must produce exactly one finished span."""

        @trace
        def noop() -> None:
            pass

        noop()
        assert len(exporter.get_finished_spans()) == 1

    def test_named_decorator_uses_custom_span_name(self, exporter: InMemorySpanExporter) -> None:
        """``@trace(name='custom')`` must use the provided name."""

        @trace(name="custom-span")
        def noop() -> None:
            pass

        noop()
        span = exporter.get_finished_spans()[0]
        assert span.name == "custom-span"

    def test_exception_marks_span_error(self, exporter: InMemorySpanExporter) -> None:
        """Exceptions must be recorded on the span and re-raised."""

        @trace
        def explode() -> None:
            raise ValueError("bang")

        with pytest.raises(ValueError, match="bang"):
            explode()

        span = exporter.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR

    def test_preserves_function_name(self) -> None:
        """``functools.wraps`` must preserve ``__name__``."""

        @trace
        def my_function() -> None:
            pass

        assert my_function.__name__ == "my_function"

    def test_preserves_docstring(self) -> None:
        """``functools.wraps`` must preserve ``__doc__``."""

        @trace
        def documented() -> None:
            """My docstring."""

        assert documented.__doc__ == "My docstring."


# ---------------------------------------------------------------------------
# Async function tests
# ---------------------------------------------------------------------------


class TestTraceAsyncFunction:
    """Tests for ``@trace`` on asynchronous (async def) functions."""

    async def test_bare_decorator_runs_coroutine(self) -> None:
        """The decorated coroutine must still return its original value."""

        @trace
        async def add(a: int, b: int) -> int:
            return a + b

        assert await add(2, 3) == 5

    async def test_bare_decorator_emits_span(self, exporter: InMemorySpanExporter) -> None:
        """Each await must produce exactly one finished span."""

        @trace
        async def noop() -> None:
            pass

        await noop()
        assert len(exporter.get_finished_spans()) == 1

    async def test_named_decorator_uses_custom_span_name(
        self, exporter: InMemorySpanExporter
    ) -> None:
        """``@trace(name='custom')`` must use the provided name."""

        @trace(name="async-span")
        async def noop() -> None:
            pass

        await noop()
        span = exporter.get_finished_spans()[0]
        assert span.name == "async-span"

    async def test_exception_marks_span_error(self, exporter: InMemorySpanExporter) -> None:
        """Async exceptions must be recorded on the span and re-raised."""

        @trace
        async def explode() -> None:
            raise RuntimeError("async-bang")

        with pytest.raises(RuntimeError, match="async-bang"):
            await explode()

        span = exporter.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR

    async def test_preserves_function_name(self) -> None:
        """``functools.wraps`` must preserve ``__name__`` on coroutines."""

        @trace
        async def my_coroutine() -> None:
            pass

        assert my_coroutine.__name__ == "my_coroutine"
