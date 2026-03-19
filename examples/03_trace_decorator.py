"""
examples/03_trace_decorator.py — @trace decorator reference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shows all the ways to use the @trace decorator:
  1. @trace on an async function (most common — FastAPI handlers call async code)
  2. @trace on a sync function (works transparently)
  3. @trace(name="custom-name") to override the default span name
  4. get_trace_id() / get_span_id() to read the current OTel context

Run:
    pip install zerotel uvicorn httpx
    python examples/03_trace_decorator.py

What you see:
    - The server starts and several requests are fired
    - Each response includes the live trace_id from get_trace_id()
    - The console shows the span names that would appear in Grafana Tempo
"""

from __future__ import annotations

import sys
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

from zerotel import Zerotel, ZerotelConfig, get_span_id, get_trace_id, trace

app = FastAPI(title="zerotel-trace-decorator")

Zerotel(
    app,
    config=ZerotelConfig(
        service_name="trace-decorator-demo",
        # No collector running — disable export so we don't get gRPC errors.
        # Traces are still created in-process; they're just not shipped anywhere.
        enable_traces=False,
        enable_metrics=True,
        enable_logging=True,
    ),
)

# ── Pattern 1: @trace with a custom name ──────────────────────────────────────
#
# The span will appear as "validate-input" in Tempo, nested under the
# root request span created by ZerotelMiddleware.
#
# Use this when the function name alone is not descriptive enough, or when
# you want a stable name that won't change if you rename the function.


@trace(name="validate-input")
async def validate(payload: dict) -> bool:
    """Async function — @trace wraps it in an async context manager internally."""
    # Simulate some validation logic.
    return bool(payload.get("name"))


# ── Pattern 2: @trace without arguments (auto-name from module.function) ──────
#
# Span name becomes "examples.03_trace_decorator.score" (module + function).
# Works on plain sync functions too — zerotel detects sync vs async automatically.


@trace
def score(value: int) -> float:
    """Sync function — @trace uses run_in_executor internally so it doesn't
    block the event loop."""
    return value * 3.14


# ── Pattern 3: nested @trace — child spans nest correctly ────────────────────
#
# Calling a @trace function from inside another @trace function produces a
# nested span tree, exactly as you'd expect in Tempo.


@trace(name="orchestrate")
async def orchestrate(payload: dict) -> dict:
    """Calls both validate() and score() — each becomes a child span of
    'orchestrate', which is itself a child of the root request span."""
    is_valid = await validate(payload)
    value = int(payload.get("value", 0))
    result = score(value)
    return {"valid": is_valid, "score": result}


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/process")
async def process(payload: dict) -> dict:
    """Full span tree for a single request:

    GET /process                     ← root span (ZerotelMiddleware)
      └── orchestrate               ← @trace(name="orchestrate")
            ├── validate-input      ← @trace(name="validate-input")
            └── ...score            ← @trace (auto-name)
    """
    result = await orchestrate(payload)

    # get_trace_id() / get_span_id() are safe to call from anywhere inside
    # a request.  Outside a request they return the OTel zero values.
    tid = get_trace_id()  # 32-char hex
    sid = get_span_id()  # 16-char hex

    return {**result, "trace_id": tid, "span_id": sid}


@app.get("/context")
async def show_context() -> dict[str, str]:
    """Demonstrates get_trace_id() / get_span_id() from a plain handler."""
    return {
        "trace_id": get_trace_id(),
        "span_id": get_span_id(),
        "note": "These IDs are auto-injected into every structlog log line too.",
    }


# ── Run and demonstrate ───────────────────────────────────────────────────────

HOST, PORT = "127.0.0.1", 18103

server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()

for _ in range(50):
    try:
        httpx.get(f"http://{HOST}:{PORT}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)
else:
    print("Server did not start in time.")
    sys.exit(1)

print("\n=== zerotel @trace decorator example ===\n")

# Hit /process — the span tree is created in-process.
r = httpx.post(
    f"http://{HOST}:{PORT}/process",
    json={"name": "Alice", "value": 7},
)
data = r.json()
print(f"POST /process → {r.status_code}")
print(f"  valid     = {data['valid']}")
print(f"  score     = {data['score']}  (7 × 3.14 = {7 * 3.14})")
print(f"  trace_id  = {data['trace_id']}")
print(f"  span_id   = {data['span_id']}")

r2 = httpx.get(f"http://{HOST}:{PORT}/context")
ctx = r2.json()
print(f"\nGET /context → {r2.status_code}")
print(f"  trace_id  = {ctx['trace_id']}")
print(f"  span_id   = {ctx['span_id']}")

print("""
Span tree (visible in Grafana Tempo when otlp_endpoint is configured):

  GET /process                      ← root (ZerotelMiddleware)
    └── orchestrate                 ← @trace(name="orchestrate")
          ├── validate-input        ← @trace(name="validate-input")
          └── <module>.score        ← @trace (auto-name from function)
""")

server.should_exit = True
thread.join(timeout=3)
