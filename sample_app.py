"""
sample_app.py — zerotel smoke-test
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run this to verify your zerotel installation works end-to-end:

    pip install zerotel uvicorn httpx
    python sample_app.py

What it does:
  1. Starts a tiny FastAPI app instrumented with Zerotel
  2. Fires three HTTP requests against it
  3. Checks /metrics for the expected Prometheus counters
  4. Prints a pass/fail summary — no external services needed

Traces won't be exported (no OTLP collector running locally) but the
SDK initialises cleanly — you'll see the expected spans in Grafana
once you point otlp_endpoint at a real collector.
"""

from __future__ import annotations

import sys
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI

from zerotel import Zerotel, ZerotelConfig, trace

# ──────────────────────────────────────────────────────────────────────────────
# 1. Build a small demo app
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="zerotel-sample")

Zerotel(
    app,
    config=ZerotelConfig(
        service_name="zerotel-sample",
        # No OTLP collector — disable trace export so we don't get gRPC errors.
        enable_traces=False,
        enable_metrics=True,
        enable_logging=True,
    ),
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/users/{user_id}")
async def get_user(user_id: int) -> dict[str, int | str]:
    result = _compute(user_id)
    return {"user_id": user_id, "result": result}


@app.get("/fail")
async def fail() -> dict[str, str]:
    raise RuntimeError("intentional error for testing")


# @trace works on sync functions too — creates a child span.
@trace(name="compute")
def _compute(n: int) -> int:
    return n * 42


# ──────────────────────────────────────────────────────────────────────────────
# 2. Run server in a background thread
# ──────────────────────────────────────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 18765
BASE = f"http://{HOST}:{PORT}"

config = uvicorn.Config(app, host=HOST, port=PORT, log_level="critical")
server = uvicorn.Server(config)
thread = threading.Thread(target=server.run, daemon=True)
thread.start()

# Wait for the server to be ready (up to 5 s)
for _ in range(50):
    try:
        httpx.get(f"{BASE}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)
else:
    print("ERROR: server did not start within 5 seconds")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# 3. Fire test requests
# ──────────────────────────────────────────────────────────────────────────────

results: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    results.append((label, condition, detail))
    status = "\033[32mPASS\033[0m" if condition else "\033[31mFAIL\033[0m"
    print(f"  [{status}]  {label}" + (f"  — {detail}" if detail else ""))


print()
print("\033[1mzerotel smoke-test\033[0m")
print("─" * 50)

# GET /health → 200
r = httpx.get(f"{BASE}/health")
check("GET /health returns 200", r.status_code == 200)
check("GET /health body", r.json() == {"status": "ok"}, str(r.json()))

# GET /users/7 → 200
r = httpx.get(f"{BASE}/users/7")
check("GET /users/7 returns 200", r.status_code == 200)
check("GET /users/7 result = 294 (7×42)", r.json().get("result") == 294, str(r.json()))

# GET /fail → 500
r = httpx.get(f"{BASE}/fail")
check("GET /fail returns 500", r.status_code == 500)

# GET /metrics — check Prometheus counters exist
# Note: Starlette mounts redirect /metrics → /metrics/ — follow it.
r = httpx.get(f"{BASE}/metrics/", follow_redirects=True)
check("GET /metrics returns 200", r.status_code == 200)
metrics_text = r.text

check(
    "zerotel_requests_total counter present",
    "zerotel_requests_total" in metrics_text,
)
check(
    "zerotel_request_duration_seconds histogram present",
    "zerotel_request_duration_seconds" in metrics_text,
)
check(
    "/users/{user_id} route labelled in metrics",
    'route="/users/{user_id}"' in metrics_text,
)
check(
    "status=200 recorded",
    'status="200"' in metrics_text,
)
check(
    "status=500 recorded",
    'status="500"' in metrics_text,
)

# ──────────────────────────────────────────────────────────────────────────────
# 4. Summary
# ──────────────────────────────────────────────────────────────────────────────

print("─" * 50)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n  {passed}/{total} checks passed\n")

server.should_exit = True
thread.join(timeout=3)

sys.exit(0 if passed == total else 1)
