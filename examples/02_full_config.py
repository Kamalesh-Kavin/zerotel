"""
examples/02_full_config.py — zerotel ZerotelConfig reference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shows every ZerotelConfig field with an explanation of what it controls.

Run:
    pip install zerotel uvicorn httpx
    python examples/02_full_config.py

What you see:
    - A server starts with a fully-configured ZerotelConfig
    - Requests are fired to show exclude_paths in action (no metrics for /ping)
    - The metrics page is printed, confirming /ping was not recorded
"""

from __future__ import annotations

import sys
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

from zerotel import Zerotel, ZerotelConfig

app = FastAPI(title="zerotel-full-config")

# ── ZerotelConfig — every field explained ────────────────────────────────────

Zerotel(
    app,
    config=ZerotelConfig(
        # ── Identity ──────────────────────────────────────────────────────────
        # Appears on every trace resource, metric label, and log line.
        service_name="full-config-api",
        # Attached to the OTel resource — useful when correlating across deploys.
        service_version="1.0.0",
        # ── Trace export ──────────────────────────────────────────────────────
        # OTLP gRPC endpoint for your collector (Grafana Agent, OTel Collector…).
        # If nothing is listening here, spans are dropped silently — no crash.
        otlp_endpoint="http://localhost:4317",
        # Set False to skip OTel initialisation entirely (e.g. local dev).
        enable_traces=True,
        # Fraction of requests to sample.  1.0 = 100%, 0.1 = 10%.
        # Lower this in high-volume production to reduce storage costs.
        trace_sample_rate=1.0,
        # ── Metrics ───────────────────────────────────────────────────────────
        # Expose a Prometheus /metrics scrape endpoint.
        enable_metrics=True,
        # Change the scrape path if /metrics conflicts with an existing route.
        metrics_endpoint="/metrics",
        # ── Logging ───────────────────────────────────────────────────────────
        # Configure structlog to emit JSON with trace_id / span_id injected.
        enable_logging=True,
        # If True, the raw request body is added as a span attribute.
        # Keep False in production (PII risk, large payloads).
        log_request_body=False,
        # ── Path exclusions ───────────────────────────────────────────────────
        # These paths are skipped by the middleware — no span, no metric label.
        # Useful for health-check and readiness probes that would inflate counters.
        exclude_paths=["/ping", "/health", "/metrics"],
    ),
)


@app.get("/ping")
async def ping() -> dict[str, str]:
    # Excluded — will NOT appear in /metrics or traces.
    return {"status": "pong"}


@app.get("/users/{user_id}")
async def get_user(user_id: int) -> dict[str, int]:
    # Instrumented — will appear in /metrics with route="/users/{user_id}".
    return {"user_id": user_id}


@app.get("/health")
async def health() -> dict[str, str]:
    # Also excluded.
    return {"status": "ok"}


# ── Run and demonstrate ───────────────────────────────────────────────────────

HOST, PORT = "127.0.0.1", 18102

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

print("\n=== zerotel full config example ===\n")

r = httpx.get(f"http://{HOST}:{PORT}/ping")
print(f"GET /ping         → {r.status_code}  {r.json()}  (excluded — no metric)")

r = httpx.get(f"http://{HOST}:{PORT}/users/42")
print(f"GET /users/42     → {r.status_code}  {r.json()}  (instrumented)")

r = httpx.get(f"http://{HOST}:{PORT}/users/42")
r = httpx.get(f"http://{HOST}:{PORT}/users/99")

# Print metrics and verify /ping is absent.
r = httpx.get(f"http://{HOST}:{PORT}/metrics/", follow_redirects=True)
lines = [l for l in r.text.splitlines() if "zerotel_requests_total" in l and not l.startswith("#")]

print("\n=== zerotel_requests_total labels ===\n")
for line in lines:
    print(" ", line)

ping_in_metrics = any('route="/ping"' in l for l in lines)
users_in_metrics = any('route="/users/{user_id}"' in l for l in lines)

print()
print(f"  /ping in metrics:             {ping_in_metrics}   (expected False — excluded)")
print(f"  /users/{{user_id}} in metrics: {users_in_metrics}  (expected True  — instrumented)")

server.should_exit = True
thread.join(timeout=3)
