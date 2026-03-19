# Contributing to zerotel

Thank you for your interest in contributing! This document explains how to set up
the development environment, run tests, and submit changes.

---

## Development setup

You need [uv](https://github.com/astral-sh/uv) and Python 3.10+.

```bash
# Clone
git clone https://github.com/Kamalesh-Kavin/zerotel
cd zerotel

# Install all dev dependencies
uv sync --extra dev

# Verify the install
uv run pytest
```

---

## Project layout

```
src/zerotel/
├── __init__.py          # Public API — Zerotel class, re-exports
├── _config.py           # ZerotelConfig dataclass
├── _context.py          # RequestContext, ContextVar helpers
├── _decorators.py       # @trace decorator
├── _logging.py          # structlog JSON configuration
├── _metrics.py          # Prometheus metric definitions
├── _middleware.py       # ASGI middleware (core instrumentation)
└── integrations/
    ├── fastapi.py        # FastAPI dependency helpers
    ├── flask.py          # Flask WSGI adapter
    └── sqlalchemy.py     # Async SQLAlchemy query tracing

tests/
├── conftest.py
├── test_config.py
├── test_context.py
├── test_decorators.py
├── test_logging.py
├── test_metrics.py
├── test_middleware.py
└── integrations/
    └── test_fastapi.py

docker/                  # Full observability stack (docker compose)
example/                 # Demo FastAPI app
docs/                    # Documentation
```

---

## Running tests

```bash
# All tests with coverage
uv run pytest

# Single file
uv run pytest tests/test_decorators.py -v

# Specific test
uv run pytest tests/test_config.py::TestZerotelConfigValidation -v
```

---

## Linting and formatting

We use **ruff** for both linting and formatting.

```bash
# Check for lint errors
uv run ruff check src/ tests/

# Auto-fix fixable issues
uv run ruff check src/ tests/ --fix

# Check formatting
uv run ruff format --check src/ tests/

# Apply formatting
uv run ruff format src/ tests/
```

All CI PRs must pass `ruff check` and `ruff format --check` with zero errors.

---

## Type checking

We use **mypy** in strict mode.

```bash
uv run mypy src/zerotel
```

---

## Code style

- **Every module** must have a module-level docstring explaining its purpose.
- **Every public class and function** must have a Google-style docstring with `Args:`, `Returns:`, and `Raises:` sections where applicable.
- **Every non-trivial line** of logic should have an inline comment explaining *why*, not just *what*.
- Variable names must be descriptive — no single-letter names outside list comprehensions.
- Private helpers are prefixed with `_`.

---

## Submitting a PR

1. Fork the repo and create a feature branch:
   ```bash
   git checkout -b feat/my-new-feature
   ```
2. Make your changes, write tests, ensure all checks pass:
   ```bash
   uv run pytest && uv run ruff check src/ tests/
   ```
3. Push and open a PR against `main`.
4. Fill in the PR template — describe the problem, the solution, and any trade-offs.

Branch protection is active: PRs require passing CI and 1 review.

---

## Release process

Releases are driven by git tags. To publish a new version:

```bash
# Bump the version in pyproject.toml and src/zerotel/__init__.py
# Then tag and push
git tag v0.2.0
git push origin v0.2.0
```

The `publish.yml` GitHub Actions workflow triggers on `v*` tags,
runs `uv build`, and publishes to PyPI via `PYPI_API_TOKEN`.

---

## Questions?

Open a [GitHub Discussion](https://github.com/Kamalesh-Kavin/zerotel/discussions)
or file an issue.
