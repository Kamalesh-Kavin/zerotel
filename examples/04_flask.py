"""
examples/04_flask.py — zerotel Flask adapter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shows how to use zerotel with a Flask (WSGI) app.

Install the Flask extra first:
    pip install "zerotel[flask]" httpx

Run:
    python examples/04_flask.py

What you see:
    - A Flask app starts with zerotel metrics and logging enabled
    - GET /hello and GET /fail are fired
    - Prometheus metrics are printed confirming both routes were recorded

Note: Flask runs in a thread via werkzeug's dev server.
"""

from __future__ import annotations

import sys
import threading
import time

import httpx

# ── Flask + zerotel Flask integration ────────────────────────────────────────
try:
    import flask
    from zerotel.integrations.flask import instrument_flask
except ImportError:
    print("Flask extra not installed.\nRun: pip install 'zerotel[flask]'")
    sys.exit(1)

from zerotel import ZerotelConfig

# ── 1. Build the Flask app ────────────────────────────────────────────────────

flask_app = flask.Flask(__name__)


@flask_app.get("/health")
def health():
    return flask.jsonify({"status": "ok"})


@flask_app.get("/hello")
def hello():
    name = flask.request.args.get("name", "world")
    return flask.jsonify({"message": f"Hello, {name}!"})


@flask_app.get("/fail")
def fail():
    flask.abort(500, description="demo error")


# ── 2. Instrument with zerotel ────────────────────────────────────────────────
#
# instrument_flask() is the Flask equivalent of Zerotel(app, ...) for FastAPI.
# It patches the WSGI app in-place, wiring:
#   • OpenTelemetry Flask instrumentation (spans per request)
#   • Prometheus metrics (zerotel_requests_total, duration, in-flight)
#   • structlog JSON logging with trace_id / span_id

config = ZerotelConfig(
    service_name="flask-demo",
    # Disable OTLP export — no collector running locally.
    enable_traces=False,
    enable_metrics=True,
    enable_logging=True,
    exclude_paths=["/health"],
)

instrument_flask(flask_app, config=config)

# ── 3. Run the Flask dev server in a background thread ───────────────────────

HOST, PORT = "127.0.0.1", 18104


def _run_flask():
    # use_reloader=False and threaded=True are required for background thread use.
    flask_app.run(host=HOST, port=PORT, use_reloader=False, threaded=True)


thread = threading.Thread(target=_run_flask, daemon=True)
thread.start()

# Wait for the server to be ready (up to 5 s).
for _ in range(50):
    try:
        httpx.get(f"http://{HOST}:{PORT}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)
else:
    print("Flask server did not start in time.")
    sys.exit(1)

# ── 4. Fire demo requests and print results ───────────────────────────────────

print("\n=== zerotel Flask adapter example ===\n")

r = httpx.get(f"http://{HOST}:{PORT}/hello")
print(f"GET /hello   → {r.status_code}  {r.json()}")

r = httpx.get(f"http://{HOST}:{PORT}/hello?name=Flask")
print(f"GET /hello?  → {r.status_code}  {r.json()}")

r = httpx.get(f"http://{HOST}:{PORT}/fail")
print(f"GET /fail    → {r.status_code}  (expected 500)")

# Metrics for Flask are served separately via the Prometheus registry,
# not mounted on the Flask app itself.  Query them directly.
from prometheus_client import REGISTRY, generate_latest  # type: ignore

metrics_text = generate_latest(REGISTRY).decode()
print("\n=== zerotel_requests_total (Flask) ===\n")
for line in metrics_text.splitlines():
    if "zerotel_requests_total" in line and not line.startswith("#"):
        print(" ", line)

health_in_metrics = any('route="/health"' in l for l in metrics_text.splitlines())
hello_in_metrics = any('route="/hello"' in l for l in metrics_text.splitlines())
print()
print(f"  /health in metrics: {health_in_metrics}  (excluded)")
print(f"  /hello  in metrics: {hello_in_metrics}   (instrumented)")
