"""
tests/integrations/test_fastapi.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests for ``zerotel.integrations.fastapi`` — FastAPI dependency helpers.

Tests verify:
- ``TraceIdDep`` resolves to the current trace ID string
- ``RequestContextDep`` resolves to the full ``RequestContext`` or ``None``
- Dependencies work end-to-end through a real request
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.conftest import _force_reset_otel_provider
from zerotel._config import ZerotelConfig
from zerotel._middleware import ZerotelMiddleware
from zerotel.integrations.fastapi import RequestContextDep, TraceIdDep


@pytest.fixture()
def dep_app() -> FastAPI:
    """FastAPI app with Zerotel middleware and dependency-using routes."""
    fast_app = FastAPI()

    # Install an in-memory OTEL provider so spans are captured synchronously
    exporter = InMemorySpanExporter()
    _force_reset_otel_provider()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    tracer = otel_trace.get_tracer("zerotel")

    cfg = ZerotelConfig(service_name="dep-test", enable_logging=False)
    fast_app.add_middleware(ZerotelMiddleware, config=cfg, tracer=tracer)

    @fast_app.get("/trace-id")
    async def get_trace_id(trace_id: TraceIdDep) -> dict[str, str]:  # type: ignore[valid-type]
        return {"trace_id": trace_id}

    @fast_app.get("/context")
    async def get_context(ctx: RequestContextDep) -> dict[str, str | None]:  # type: ignore[valid-type]
        if ctx is None:
            return {"trace_id": None}
        return {"trace_id": ctx.trace_id, "service": ctx.service_name}

    return fast_app


@pytest.fixture()
async def dep_client(dep_app: FastAPI):  # type: ignore[no-untyped-def]
    """Async httpx client for the dependency test app."""
    async with AsyncClient(
        transport=ASGITransport(app=dep_app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as ac:
        yield ac


async def test_trace_id_dep_returns_string(dep_client: AsyncClient) -> None:
    """TraceIdDep must inject a non-empty string into the route handler."""
    resp = await dep_client.get("/trace-id")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["trace_id"], str)
    assert len(data["trace_id"]) > 0


async def test_trace_id_dep_is_hex(dep_client: AsyncClient) -> None:
    """The injected trace_id must be a valid 32-char hex string."""
    resp = await dep_client.get("/trace-id")
    trace_id = resp.json()["trace_id"]
    # Should be parseable as a hex integer
    int(trace_id, 16)  # raises ValueError if not hex
    assert len(trace_id) == 32


async def test_request_context_dep_includes_service_name(
    dep_client: AsyncClient,
) -> None:
    """RequestContextDep must expose the service name from config."""
    resp = await dep_client.get("/context")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "dep-test"
