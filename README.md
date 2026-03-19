# zerotel

[![PyPI](https://img.shields.io/pypi/v/zerotel)](https://pypi.org/project/zerotel/)
[![Python](https://img.shields.io/pypi/pyversions/zerotel)](https://pypi.org/project/zerotel/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Kamalesh-Kavin/zerotel/actions/workflows/test.yml/badge.svg)](https://github.com/Kamalesh-Kavin/zerotel/actions)

**Zero-config observability SDK for Python services.**

Add one line. Get distributed traces, Prometheus metrics, and structured JSON logs — all correlated by `trace_id` and ready to query in Grafana.

```python
from fastapi import FastAPI
from zerotel import Zerotel

app = FastAPI()
Zerotel(app, service_name="my-api")   # done
```

---

## What you get

| Signal | What's captured |
|--------|----------------|
| **Traces** | Root span per request — method, route, status, latency, error |
| **Traces** | `@trace` child spans, nested correctly under the request |
| **Traces** | SQLAlchemy async queries as child spans (with sanitised SQL) |
| **Metrics** | `zerotel_requests_total` — counter by method/route/status |
| **Metrics** | `zerotel_request_duration_seconds` — histogram |
| **Metrics** | `zerotel_requests_in_flight` — gauge |
| **Logs** | Structured JSON with `trace_id`, `span_id`, `service` auto-injected |

---

## Installation

```bash
pip install zerotel
```

Optional extras:

```bash
pip install "zerotel[sqlalchemy]"   # async SQLAlchemy query tracing
pip install "zerotel[flask]"        # Flask WSGI adapter
pip install "zerotel[all]"          # everything
```

---

## Quickstart

### Minimal

```python
from fastapi import FastAPI
from zerotel import Zerotel

app = FastAPI()
Zerotel(app, service_name="payments-api")
```

### Full configuration

```python
from fastapi import FastAPI
from zerotel import Zerotel, ZerotelConfig

app = FastAPI()

Zerotel(app, config=ZerotelConfig(
    service_name="payments-api",
    service_version="2.1.0",
    otlp_endpoint="http://otel-collector:4317",
    enable_traces=True,
    enable_metrics=True,
    enable_logging=True,
    exclude_paths=["/health", "/metrics"],  # skip these from tracing
    log_request_body=False,                 # keep off in prod (PII risk)
    trace_sample_rate=1.0,                  # lower in high-volume prod
))
```

### `@trace` decorator

Add a named child span to any function — works on both `async def` and `def`:

```python
from zerotel import trace

@trace(name="send-email")
async def send_email(user_id: int) -> None:
    ...  # this entire function becomes a child span under the request span

@trace
def compute_score(data: list[float]) -> float:
    ...  # span name defaults to "module.compute_score"
```

### Reading the current trace ID

```python
from zerotel import get_trace_id, get_span_id

def my_helper() -> None:
    tid = get_trace_id()   # 32-char hex or "0" * 32 if outside a request
    sid = get_span_id()    # 16-char hex
```

### FastAPI dependency injection

```python
from fastapi import FastAPI
from zerotel.integrations.fastapi import TraceIdDep, RequestContextDep

app = FastAPI()

@app.get("/profile")
async def get_profile(trace_id: TraceIdDep) -> dict:
    return {"trace_id": trace_id}
```

### SQLAlchemy async query tracing

```python
from sqlalchemy.ext.asyncio import create_async_engine
from zerotel.integrations.sqlalchemy import instrument_sqlalchemy

engine = create_async_engine("postgresql+asyncpg://user:pw@localhost/mydb")
instrument_sqlalchemy(engine)
# Every query is now a child span with sanitised SQL as an attribute
```

---

## Local observability stack

The `docker/` folder contains a ready-to-use Docker Compose stack:

| Service | URL | Purpose |
|---------|-----|---------|
| OTel Collector | — | Receives OTLP, fans out |
| Grafana Tempo | http://localhost:3200 | Trace storage |
| Prometheus | http://localhost:9090 | Metrics storage |
| Grafana Loki | http://localhost:3100 | Log aggregation |
| **Grafana** | **http://localhost:3000** | **Unified UI** |

```bash
cd docker/
docker compose up -d

# Run your service
OTLP_ENDPOINT=http://localhost:4317 uvicorn myapp:app --reload

# Open Grafana (admin / admin)
open http://localhost:3000
```

---

## Configuration reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `service_name` | `str` | `"unknown-service"` | Appears on every trace, metric, and log |
| `service_version` | `str` | `"0.0.0"` | Attached to trace resources |
| `otlp_endpoint` | `str` | `"http://localhost:4317"` | OTLP gRPC collector address |
| `enable_traces` | `bool` | `True` | Export OpenTelemetry spans |
| `enable_metrics` | `bool` | `True` | Expose Prometheus `/metrics` |
| `enable_logging` | `bool` | `True` | Configure structlog JSON |
| `exclude_paths` | `list[str]` | `["/health", "/metrics"]` | Paths to skip from instrumentation |
| `log_request_body` | `bool` | `False` | Capture request body on span (PII risk) |
| `trace_sample_rate` | `float` | `1.0` | Fraction of requests to sample (0.0–1.0) |
| `metrics_endpoint` | `str` | `"/metrics"` | Path for Prometheus scrape endpoint |

---

## Development

```bash
git clone https://github.com/Kamalesh-Kavin/zerotel
cd zerotel
uv sync --extra dev

# Run tests
uv run pytest

# Lint
uv run ruff check src/
uv run ruff format src/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

---

## Philosophy

> "If you cannot explain the code without the AI, you haven't learned it yet."

Every file in this project is heavily commented. The goal is for you to be able to read any file cold and understand exactly what it does and why.

---

## License

MIT — see [LICENSE](LICENSE).
