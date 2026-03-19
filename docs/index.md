# zerotel Documentation

> Zero-config observability for Python services.  
> One line. Traces + metrics + structured logs.

---

## Contents

- [Quickstart](#quickstart)
- [Configuration Reference](#configuration-reference)
- [The `@trace` Decorator](#the-trace-decorator)
- [FastAPI Integrations](#fastapi-integrations)
- [SQLAlchemy Integration](#sqlalchemy-integration)
- [Flask Integration](#flask-integration)
- [Signals Reference](#signals-reference)
- [Running the Observability Stack](#running-the-observability-stack)
- [Release Checklist](#release-checklist)

---

## Quickstart

### Install

```bash
pip install zerotel
# or with uv
uv add zerotel
```

### Minimal setup

```python
from fastapi import FastAPI
from zerotel import Zerotel

app = FastAPI()
Zerotel(app, service_name="my-api")
```

That's it. Your app now emits:

- **Traces** (OTLP gRPC → OpenTelemetry Collector) for every HTTP request
- **Prometheus metrics** at `GET /metrics`
- **Structured JSON logs** with `trace_id` / `span_id` injected automatically

---

## Configuration Reference

```python
from zerotel import Zerotel, ZerotelConfig

Zerotel(
    app,
    config=ZerotelConfig(
        service_name="my-api",          # required — appears in every span and log line
        otlp_endpoint="http://localhost:4317",  # gRPC OTLP endpoint; default shown
        enable_metrics=True,            # expose /metrics (Prometheus)
        enable_logging=True,            # configure structlog JSON output
        exclude_paths=["/health", "/metrics"],  # skip tracing for these routes
        log_request_body=False,         # set True to log raw request bodies (careful with PII)
        trace_sample_rate=1.0,          # 1.0 = 100 % sampling; 0.1 = 10 %
    ),
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `service_name` | `str` | — | **Required.** Identifies this service in traces / logs. |
| `otlp_endpoint` | `str` | `"http://localhost:4317"` | gRPC endpoint of your OpenTelemetry Collector. |
| `enable_metrics` | `bool` | `True` | Mount a Prometheus `/metrics` endpoint. |
| `enable_logging` | `bool` | `True` | Configure structlog to output JSON with OTel context. |
| `exclude_paths` | `list[str]` | `["/health", "/metrics"]` | Paths that will not generate spans or metric labels. |
| `log_request_body` | `bool` | `False` | Include raw request body in log lines (may leak PII). |
| `trace_sample_rate` | `float` | `1.0` | Fraction of requests to sample (0.0 – 1.0). |

---

## The `@trace` Decorator

Use `@trace` to create child spans for any function — sync or async.

```python
from zerotel import trace

# Default span name = function name ("send_email")
@trace
async def send_email(user_id: int) -> None:
    ...

# Custom span name
@trace(name="compute-recommendation-score")
def compute_score(data: list[float]) -> float:
    ...
```

The decorator:
- Works transparently on `async def` **and** `def` functions
- Resolves the global tracer **lazily** at call time (safe for testing)
- Automatically records any raised exception on the span and re-raises it
- Correctly nests spans inside an active request span when called from a FastAPI route

---

## FastAPI Integrations

### Dependency: inject `trace_id` into a response

```python
from fastapi import FastAPI, Depends
from zerotel.integrations.fastapi import TraceIdDep

app = FastAPI()

@app.get("/users/{user_id}")
async def get_user(user_id: int, trace_id: TraceIdDep):
    return {"user_id": user_id, "trace_id": trace_id}
```

### Dependency: access the full `RequestContext`

```python
from zerotel.integrations.fastapi import RequestContextDep

@app.get("/debug")
async def debug(ctx: RequestContextDep):
    return {"trace_id": ctx.trace_id, "span_id": ctx.span_id}
```

---

## SQLAlchemy Integration

Install the extra:

```bash
pip install "zerotel[sqlalchemy]"
```

Then instrument your async engine **before** your first query:

```python
from sqlalchemy.ext.asyncio import create_async_engine
from zerotel.integrations.sqlalchemy import instrument_sqlalchemy

engine = create_async_engine("postgresql+asyncpg://...")
instrument_sqlalchemy(engine)
```

Every query becomes a child span with:
- `db.statement` — sanitised SQL (string literals and numbers replaced with `?`)
- `db.system` — `"sqlalchemy"`
- Duration measured as span latency

---

## Flask Integration

Install the extra:

```bash
pip install "zerotel[flask]"
```

```python
from flask import Flask
from zerotel.integrations.flask import instrument_flask

app = Flask(__name__)
instrument_flask(app)
```

Attaches `before_request` / `after_request` / `teardown_request` hooks that mirror the FastAPI middleware behaviour.

---

## Signals Reference

### Traces

| Span attribute | Value |
|----------------|-------|
| `http.method` | `GET`, `POST`, … |
| `http.route` | FastAPI path template, e.g. `/users/{user_id}` |
| `http.status_code` | Integer response status |
| `error` | `true` on 5xx responses |

### Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `zerotel_requests_total` | Counter | `method`, `route`, `status` |
| `zerotel_request_duration_seconds` | Histogram | `method`, `route` |
| `zerotel_requests_in_flight` | Gauge | `method`, `route` |

### Logs

Every log line emitted via `structlog.get_logger()` is enriched with:

```json
{
  "timestamp": "2024-01-15T10:30:00.123456Z",
  "level": "info",
  "service": "my-api",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "event": "user fetched",
  "user_id": 42
}
```

---

## Running the Observability Stack

A complete local stack (Collector → Tempo + Prometheus + Loki → Grafana) is included:

```bash
cd docker/
docker compose up -d
```

| Service | URL | Purpose |
|---------|-----|---------|
| Grafana | http://localhost:3000 | Unified UI (traces, metrics, logs) |
| Prometheus | http://localhost:9090 | Metrics query |
| Tempo | http://localhost:3200 | Trace storage |
| Loki | http://localhost:3100 | Log aggregation |
| OTel Collector | localhost:4317 | OTLP gRPC receiver |

All datasources are pre-provisioned — open Grafana and explore immediately.

---

## Release Checklist

1. Bump the version in `pyproject.toml`
2. Update `CHANGELOG.md` (if present)
3. Commit: `git commit -m "chore: release v0.x.y"`
4. Tag: `git tag v0.x.y && git push origin v0.x.y`
5. The `publish.yml` workflow runs automatically, builds the package, and uploads to PyPI.

Make sure the `PYPI_API_TOKEN` secret is set in **GitHub → Settings → Secrets → Actions** before the first release.
