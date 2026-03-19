# example/Dockerfile
#
# Dockerfile for the Zerotel example FastAPI application.
#
# Multi-stage build:
#   Stage 1 (builder): installs Python dependencies with uv
#   Stage 2 (runtime): copies only the installed packages — no build tools
#
# Build:
#   docker build -t zerotel-example .
#
# Run:
#   docker run -p 8000:8000 \
#     -e OTLP_ENDPOINT=http://otel-collector:4317 \
#     zerotel-example

# ---- Stage 1: dependency installation ----
FROM python:3.11-slim AS builder

# Install uv — fast Python package installer
RUN pip install uv

WORKDIR /app

# Copy only the dependency spec first so Docker layer caching works:
# if pyproject.toml doesn't change, this layer is cached.
COPY pyproject.toml .
COPY src/ src/
COPY example/ example/

# Install zerotel + its runtime dependencies (no dev tools)
RUN uv pip install --system ".[sqlalchemy]" uvicorn


# ---- Stage 2: runtime image ----
FROM python:3.11-slim AS runtime

# Create a non-root user for security
RUN groupadd -r app && useradd -r -g app app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /app/example /app/example
COPY --from=builder /app/src /app/src

# Set PYTHONPATH so the example can import zerotel from src/
ENV PYTHONPATH=/app/src
ENV OTLP_ENDPOINT=http://localhost:4317

USER app

EXPOSE 8000

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "example.main:app", "--host", "0.0.0.0", "--port", "8000"]
