# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.2.0] - 2025-03-01

### Added

- `zerotel` CLI entry-point (`zerotel --help`, `--version`, `info`, `quickstart`, `config`)
  registered via `[project.scripts]` so it is available immediately after `pip install zerotel`.
- `sample_app.py` — self-contained smoke test (11/11 checks, no external services needed).

### Fixed

- CI workflows no longer use `enable-cache: true` with `astral-sh/setup-uv@v3` — this
  requires `uv.lock` which is gitignored for library projects and caused all CI runs to fail.
- `mypy --strict` was passed on the CLI, overriding `warn_unused_ignores = false` in
  `pyproject.toml`. Strict mode is now configured entirely in `[tool.mypy]`.

---

## [0.1.0] - 2025-01-01

### Added

- `Zerotel(app, service_name="my-api")` — single-call FastAPI instrumentation.
- `ZerotelConfig` — full configuration dataclass with fields for `service_name`,
  `service_version`, `otlp_endpoint`, `enable_traces`, `enable_metrics`,
  `enable_logging`, `exclude_paths`, `log_request_body`, `trace_sample_rate`,
  `metrics_endpoint`.
- `@trace` decorator — transparent child-span creation for both `async def` and `def`.
  Span name defaults to `module.function`; can be overridden with `@trace(name="...")`.
- `get_trace_id()` / `get_span_id()` — context helpers returning the current OTel IDs.
- OpenTelemetry traces via OTLP gRPC exporter (Grafana Tempo compatible).
- Prometheus metrics: `zerotel_requests_total`, `zerotel_request_duration_seconds`,
  `zerotel_requests_in_flight` — labelled by `method`, `route`, `status`.
- Structured JSON logging via `structlog` with `trace_id`, `span_id`, `service`
  auto-injected into every log record.
- `zerotel[sqlalchemy]` — async SQLAlchemy query tracing (child spans with sanitised SQL).
- `zerotel[flask]` — Flask WSGI adapter.
- `docker/` — ready-to-use Docker Compose stack: OTel Collector, Grafana Tempo,
  Prometheus, Grafana Loki, Grafana (pre-provisioned datasources + dashboard).
- `example/` — annotated example FastAPI service with Dockerfile.
- `docs/index.md` — full documentation.
- `CONTRIBUTING.md` — development setup, code style, test, and PR guidelines.
- CI: `lint.yml` (ruff + mypy), `test.yml` (matrix 3.10/3.11/3.12),
  `publish.yml` (tag-triggered, test-gated PyPI release).
- 61 unit tests covering config, context, decorators, logging, metrics,
  middleware, and FastAPI integration.
