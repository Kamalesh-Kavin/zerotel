"""
examples/01_minimal.py — zerotel minimal example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The smallest possible zerotel setup.  One import, one call, done.

Run:
    pip install zerotel uvicorn httpx
    python examples/01_minimal.py

What you see:
    - A tiny FastAPI app starts on port 18101
    - Three requests are fired automatically
    - Prometheus metrics are printed showing the request counters
    - The server shuts down cleanly

No OTLP collector needed — traces are configured but nothing is exported
(there is no collector listening on localhost:4317).  Metrics and logs
work entirely in-process.
"""

from __future__ import annotations

import sys
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

from zerotel import Zerotel

# ── 1. Create your FastAPI app ────────────────────────────────────────────────

app = FastAPI(title="zerotel-minimal")

# ── 2. Instrument it — one call wires traces, metrics, and structured logs ───
#
#  service_name  appears on every trace, metric label, and log line.
#  That's the only required argument.  Everything else uses safe defaults:
#    otlp_endpoint    = "http://localhost:4317"
#    enable_traces    = True
#    enable_metrics   = True
#    enable_logging   = True
#    exclude_paths    = ["/health", "/metrics"]
#    trace_sample_rate = 1.0

Zerotel(app, service_name="minimal-api")

# ── 3. Define your routes as normal ──────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    # Excluded from tracing by default.
    return {"status": "ok"}


@app.get("/hello")
async def hello(name: str = "world") -> dict[str, str]:
    # This route is fully instrumented:
    #   • A root span is opened and closed around the handler.
    #   • zerotel_requests_total{method="GET", route="/hello", status="200"} += 1
    #   • zerotel_request_duration_seconds updated.
    #   • A JSON log line is emitted with trace_id / span_id injected.
    return {"message": f"Hello, {name}!"}


@app.get("/fail")
async def fail() -> dict[str, str]:
    # Intentional 500 — demonstrates error tracking in metrics.
    raise RuntimeError("demo error")


# ── 4. Run the server in the background and fire demo requests ────────────────

HOST, PORT = "127.0.0.1", 18101

server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()

# Wait for the server to be ready (up to 5 s).
for _ in range(50):
    try:
        httpx.get(f"http://{HOST}:{PORT}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)
else:
    print("Server did not start in time.")
    sys.exit(1)

print("\n=== zerotel minimal example ===\n")

# Fire some requests so we have data to show.
r = httpx.get(f"http://{HOST}:{PORT}/hello")
print(f"GET /hello       → {r.status_code}  {r.json()}")

r = httpx.get(f"http://{HOST}:{PORT}/hello?name=zerotel")
print(f"GET /hello?name= → {r.status_code}  {r.json()}")

r = httpx.get(f"http://{HOST}:{PORT}/fail")
print(f"GET /fail        → {r.status_code}  (expected 500)")

# Fetch and print the Prometheus metrics page.
# Starlette mounts /metrics with a trailing-slash redirect — follow it.
r = httpx.get(f"http://{HOST}:{PORT}/metrics/", follow_redirects=True)
print("\n=== /metrics (excerpt) ===\n")
for line in r.text.splitlines():
    # Print only zerotel-specific lines — skip Prometheus internal counters.
    if line.startswith("zerotel_") and not line.startswith("#"):
        print(" ", line)

print("\nDone — no collector needed, metrics are live in-process.")

server.should_exit = True
thread.join(timeout=3)
