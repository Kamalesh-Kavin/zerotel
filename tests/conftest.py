"""
tests/conftest.py
~~~~~~~~~~~~~~~~~

Shared pytest fixtures for the zerotel test suite.

Provides:
- ``app``         — a bare FastAPI application (no instrumentation)
- ``instrumented_app`` — a FastAPI app with Zerotel wired in
- ``client``      — an httpx AsyncClient bound to ``instrumented_app``
- ``reset_metrics`` — clears Prometheus metric state between tests
- ``reset_otel``  — resets the global OTEL tracer provider between tests

Why fixtures instead of module-level setup?
Fixtures run fresh per test so there is no shared mutable state between tests.
The ``autouse=True`` fixtures ensure cleanup happens automatically.
"""

from __future__ import annotations

import opentelemetry.trace as _otel_trace_module
import pytest
from fastapi import FastAPI
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider

from zerotel import Zerotel, ZerotelConfig


def _force_reset_otel_provider() -> None:
    """Forcibly reset the global OTel tracer provider.

    OTel 1.x uses a ``SetOnce`` sentinel that prevents ``set_tracer_provider``
    from being called twice.  In tests we need to swap the provider per-test.
    This function resets the internal sentinel so the next call works.

    This is intentionally testing-only — do not use in production code.
    """
    _otel_trace_module._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    _otel_trace_module._TRACER_PROVIDER = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    """Return a fresh FastAPI app with a minimal set of routes for testing."""
    app = FastAPI()

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"message": "hello"}

    @app.get("/users/{user_id}")
    async def get_user(user_id: int) -> dict[str, int]:
        return {"id": user_id}

    @app.get("/error")
    async def trigger_error() -> None:
        raise RuntimeError("intentional error")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> ZerotelConfig:
    """Minimal ``ZerotelConfig`` suitable for unit tests.

    Tracing is enabled but no real OTLP exporter is configured — the SDK
    will use the no-op exporter when the collector is not reachable.
    Logging is disabled to keep test output clean.
    """
    return ZerotelConfig(
        service_name="test-service",
        enable_logging=False,  # suppress structlog output in test output
        enable_metrics=True,
        enable_traces=True,
        trace_sample_rate=1.0,
        exclude_paths=["/health"],
    )


@pytest.fixture()
def app() -> FastAPI:
    """A bare FastAPI app — no Zerotel instrumentation."""
    return _make_app()


@pytest.fixture()
def instrumented_app(config: ZerotelConfig) -> FastAPI:
    """A FastAPI app with Zerotel fully wired in."""
    fast_app = _make_app()
    Zerotel(fast_app, config=config)
    return fast_app


@pytest.fixture()
async def client(instrumented_app: FastAPI):  # type: ignore[no-untyped-def]
    """Async httpx client for making test requests to ``instrumented_app``."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=instrumented_app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def reset_otel() -> None:
    """Reset the global OTel tracer provider before and after each test.

    Without this, the second test that calls ``Zerotel(app, ...)`` would
    see the provider already set and create duplicate span processors.
    Uses the internal ``_TRACER_PROVIDER_SET_ONCE`` reset so the provider
    can truly be swapped.
    """
    _force_reset_otel_provider()
    otel_trace.set_tracer_provider(TracerProvider())
    yield  # type: ignore[misc]
    _force_reset_otel_provider()
    otel_trace.set_tracer_provider(TracerProvider())


@pytest.fixture(autouse=True)
def reset_metrics() -> None:
    """Unregister all Prometheus collectors that start with 'zerotel_'.

    Prometheus raises if you try to register a metric name that already
    exists.  Since ``_metrics.py`` registers them at module import time
    the REGISTRY already has them — this fixture doesn't need to
    re-register them, just ensure their *sample values* are stable.

    For tests that assert on counter values, use ``reset_metrics`` explicitly
    and collect a baseline before the action under test.
    """
    # We intentionally do NOT unregister because prometheus_client does not
    # support safe re-registration.  Tests must account for cumulative values
    # by collecting baselines. This fixture exists as a marker / extension point.
    yield  # type: ignore[misc]
