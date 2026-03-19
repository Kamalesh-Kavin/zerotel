"""
example/main.py
~~~~~~~~~~~~~~~

Demo FastAPI application instrumented with Zerotel.

This is the reference app for zerotel.  Run it, hit the endpoints,
and see traces in Tempo, metrics in Prometheus, and logs in Loki — all
correlated by trace_id.

Setup:
    # 1. Start the observability stack
    cd docker/ && docker compose up -d

    # 2. Install dependencies
    pip install "zerotel[sqlalchemy]" uvicorn

    # 3. Run this app
    uvicorn example.main:app --reload

Endpoints:
    GET /health                  — excluded from tracing (health check)
    GET /metrics                 — Prometheus scrape endpoint
    GET /users/{user_id}         — simulated user lookup (uses @trace)
    GET /orders                  — simulated order list
    POST /orders                 — simulated order creation

Then open Grafana at http://localhost:3000 (admin/admin) to see all signals.
"""

from __future__ import annotations

import random
import time

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from zerotel import Zerotel, ZerotelConfig, trace

# --------------------------------------------------------------------------- #
# App setup                                                                   #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="Zerotel Example API",
    description="Demo FastAPI app instrumented with Zerotel observability.",
    version="0.1.0",
)

# Single call wires traces, metrics, and structured logging into the app.
# All requests are captured as OTLP spans, Prometheus metrics updated, and
# every log line gets trace_id / span_id injected automatically.
Zerotel(
    app,
    config=ZerotelConfig(
        service_name="example-api",
        service_version="0.1.0",
        otlp_endpoint="http://localhost:4317",  # OTel Collector default
        enable_traces=True,
        enable_metrics=True,
        enable_logging=True,
        exclude_paths=["/health", "/metrics"],  # skip boring endpoints
        trace_sample_rate=1.0,  # sample everything (lower in prod)
    ),
)

# Get a structured logger — trace_id / span_id are injected automatically
log = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Pydantic models                                                              #
# --------------------------------------------------------------------------- #


class User(BaseModel):
    """A minimal user object for demo purposes."""

    id: int
    name: str
    email: str


class Order(BaseModel):
    """A minimal order object."""

    id: int
    user_id: int
    product: str
    amount: float


class CreateOrderRequest(BaseModel):
    """Request body for POST /orders."""

    user_id: int
    product: str
    amount: float


# --------------------------------------------------------------------------- #
# Simulated database — in-memory for demo                                     #
# In a real app this would be replaced by async SQLAlchemy calls.             #
# --------------------------------------------------------------------------- #

_USERS: dict[int, User] = {
    1: User(id=1, name="Alice", email="alice@example.com"),
    2: User(id=2, name="Bob", email="bob@example.com"),
    3: User(id=3, name="Carol", email="carol@example.com"),
}

_ORDERS: list[Order] = [
    Order(id=1, user_id=1, product="Widget", amount=9.99),
    Order(id=2, user_id=2, product="Gadget", amount=49.99),
]
_next_order_id = 3


# --------------------------------------------------------------------------- #
# Helpers annotated with @trace                                               #
# These become child spans nested under the request's root span.              #
# --------------------------------------------------------------------------- #


@trace(name="db.fetch-user")
async def _fetch_user(user_id: int) -> User | None:
    """Simulate a database lookup — becomes a child 'db.fetch-user' span.

    In a real app, replace this with:
        async with session.begin():
            return await session.get(UserModel, user_id)
    """
    # Simulate variable latency (5-50ms)
    await _simulate_latency(0.005, 0.05)
    return _USERS.get(user_id)


@trace(name="db.list-orders")
async def _list_orders() -> list[Order]:
    """Simulate fetching all orders — becomes a 'db.list-orders' child span."""
    await _simulate_latency(0.002, 0.02)
    return list(_ORDERS)


@trace(name="db.create-order")
async def _create_order(req: CreateOrderRequest) -> Order:
    """Simulate inserting an order — becomes a 'db.create-order' child span."""
    global _next_order_id

    await _simulate_latency(0.005, 0.03)
    order = Order(
        id=_next_order_id,
        user_id=req.user_id,
        product=req.product,
        amount=req.amount,
    )
    _ORDERS.append(order)
    _next_order_id += 1
    return order


async def _simulate_latency(min_s: float, max_s: float) -> None:
    """Simulate variable I/O latency for demo realism.

    In production this would be replaced by real async I/O.
    We use ``time.sleep`` in a thread pool here to avoid blocking
    the event loop — but for demo purposes the latency values are small.
    """
    import asyncio

    await asyncio.sleep(random.uniform(min_s, max_s))


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check — excluded from tracing to avoid noise.

    Returns:
        JSON ``{"status": "ok"}`` — used by load balancers and k8s probes.
    """
    return {"status": "ok"}


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int) -> User:
    """Fetch a user by ID.

    Demonstrates:
    - Root span from ZerotelMiddleware (GET /users/{user_id})
    - Child span from @trace on ``_fetch_user``
    - Structured log with trace_id auto-injected

    Args:
        user_id: Integer user ID in the URL path.

    Returns:
        The ``User`` object.

    Raises:
        HTTPException 404: When the user doesn't exist.
    """
    log.info("fetching user", user_id=user_id)

    user = await _fetch_user(user_id)
    if user is None:
        log.warning("user not found", user_id=user_id)
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    log.info("user fetched successfully", user_id=user_id, email=user.email)
    return user


@app.get("/orders", response_model=list[Order])
async def list_orders() -> list[Order]:
    """Return all orders.

    Demonstrates a simple read operation with automatic span + metrics.

    Returns:
        List of all ``Order`` objects.
    """
    log.info("listing orders")
    orders = await _list_orders()
    log.info("orders listed", count=len(orders))
    return orders


@app.post("/orders", response_model=Order, status_code=201)
async def create_order(req: CreateOrderRequest) -> Order:
    """Create a new order.

    Demonstrates:
    - POST request instrumentation
    - Child span for the DB insert
    - Structured log with request context

    Args:
        req: Order details in the request body.

    Returns:
        The created ``Order`` with its assigned ID.
    """
    log.info("creating order", user_id=req.user_id, product=req.product)
    order = await _create_order(req)
    log.info("order created", order_id=order.id, amount=order.amount)
    return order
