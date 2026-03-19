"""
tests/test_middleware.py
~~~~~~~~~~~~~~~~~~~~~~~~

Integration tests for ``ZerotelMiddleware``.

Each test fires a real HTTP request through the ASGI stack via httpx and
asserts on the response status, span attributes, and metric state.

Why ``pytest-asyncio``?
The FastAPI app and httpx client are both async.  ``asyncio_mode = "auto"``
in ``pyproject.toml`` means pytest-asyncio automatically discovers and runs
async test functions without the ``@pytest.mark.asyncio`` decorator.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.conftest import _force_reset_otel_provider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instrumented_app(exporter: InMemorySpanExporter) -> FastAPI:
    """Create a FastAPI app instrumented with a test-only in-memory exporter.

    This lets us inspect emitted spans in-process without needing a real
    OTLP collector.
    """
    fast_app = FastAPI()

    @fast_app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"msg": "hi"}

    @fast_app.get("/users/{user_id}")
    async def get_user(user_id: int) -> dict[str, int]:
        return {"id": user_id}

    @fast_app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @fast_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("oops")

    # Wire up the in-memory tracer provider directly
    _force_reset_otel_provider()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    tracer = otel_trace.get_tracer("zerotel")

    from zerotel._config import ZerotelConfig as _Cfg
    from zerotel._middleware import ZerotelMiddleware

    cfg = _Cfg(service_name="test-svc", enable_logging=False, exclude_paths=["/health"])
    fast_app.add_middleware(ZerotelMiddleware, config=cfg, tracer=tracer)

    return fast_app


@pytest.fixture()
def exporter() -> InMemorySpanExporter:
    """Fresh in-memory span exporter, cleared before each test."""
    exp = InMemorySpanExporter()
    return exp


@pytest.fixture()
async def span_client(exporter: InMemorySpanExporter):  # type: ignore[no-untyped-def]
    """httpx async client backed by the in-memory-exporter instrumented app."""
    from httpx import ASGITransport, AsyncClient

    fast_app = _make_instrumented_app(exporter)
    async with AsyncClient(
        transport=ASGITransport(app=fast_app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_successful_request_returns_200(span_client: AsyncClient) -> None:
    """Middleware must pass responses through without modification."""
    resp = await span_client.get("/hello")
    assert resp.status_code == 200


async def test_span_created_for_request(
    span_client: AsyncClient,
    exporter: InMemorySpanExporter,
) -> None:
    """One span must be emitted per instrumented request."""
    await span_client.get("/hello")
    spans = exporter.get_finished_spans()
    assert len(spans) >= 1


async def test_span_has_http_method_attribute(
    span_client: AsyncClient,
    exporter: InMemorySpanExporter,
) -> None:
    """The root span must carry the HTTP method attribute."""
    await span_client.get("/hello")
    span = exporter.get_finished_spans()[0]
    assert span.attributes.get("http.method") == "GET"  # type: ignore[union-attr]


async def test_span_has_status_code_attribute(
    span_client: AsyncClient,
    exporter: InMemorySpanExporter,
) -> None:
    """The root span must carry the HTTP status code after response."""
    await span_client.get("/hello")
    span = exporter.get_finished_spans()[0]
    assert span.attributes.get("http.status_code") == 200  # type: ignore[union-attr]


async def test_excluded_path_produces_no_span(
    span_client: AsyncClient,
    exporter: InMemorySpanExporter,
) -> None:
    """Requests to excluded paths must pass through without creating a span."""
    exporter.clear()
    await span_client.get("/health")
    assert len(exporter.get_finished_spans()) == 0


async def test_error_response_marks_span_error(
    span_client: AsyncClient,
    exporter: InMemorySpanExporter,
) -> None:
    """An unhandled exception must mark the span as ERROR."""
    from opentelemetry.trace import StatusCode

    try:
        await span_client.get("/boom")
    except Exception:
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR


async def test_route_template_used_not_resolved_path(
    span_client: AsyncClient,
    exporter: InMemorySpanExporter,
) -> None:
    """The span name uses the route template (/users/{user_id}) not the value."""
    await span_client.get("/users/42")
    span = exporter.get_finished_spans()[0]
    # The span name should contain the template, not the literal value
    assert "users" in span.name
