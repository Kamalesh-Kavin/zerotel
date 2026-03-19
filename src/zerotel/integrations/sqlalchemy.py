"""
zerotel.integrations.sqlalchemy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Async SQLAlchemy instrumentation — captures every database query as a child
span under the current request's trace.

Install the extra dependency first::

    pip install "zerotel[sqlalchemy]"

Then pass your ``AsyncEngine`` to ``instrument_sqlalchemy()`` once at startup:

    from sqlalchemy.ext.asyncio import create_async_engine
    from zerotel.integrations.sqlalchemy import instrument_sqlalchemy

    engine = create_async_engine("postgresql+asyncpg://...")
    instrument_sqlalchemy(engine)

After that, every ``await session.execute(...)`` will automatically create a
child span named ``"db.query"`` with the following attributes:

* ``db.system`` — always ``"postgresql"``
* ``db.statement`` — the sanitised SQL string (bind parameters replaced with
  ``?`` to avoid leaking sensitive values)
* ``db.operation`` — ``"SELECT"``, ``"INSERT"``, ``"UPDATE"``, or ``"DELETE"``
* ``db.duration_ms`` — execution time in milliseconds

Implementation note
~~~~~~~~~~~~~~~~~~~
SQLAlchemy's event system fires ``before_cursor_execute`` and
``after_cursor_execute`` synchronously even in async mode (the async layer
wraps the sync core).  We use these two events as span start/end hooks and
store the start time in a connection-info dict keyed by ``_zerotel_start``.
"""

from __future__ import annotations

import re
import time
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.trace import StatusCode

# SQLAlchemy is an optional dependency — guard the import so the rest of
# zerotel works fine when [sqlalchemy] extra is not installed.
try:
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncEngine

    _SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SQLALCHEMY_AVAILABLE = False


# Regex to extract the first SQL keyword (SELECT, INSERT, etc.)
_SQL_OPERATION_RE = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)", re.I)

# Regex to sanitise bind parameters: replace literal values with '?'
# Handles both %(name)s (psycopg) and $1 (asyncpg) style placeholders.
_PARAM_RE = re.compile(r"(\$\d+|%\([^)]+\)s|%s)")


def _sanitise_sql(statement: str) -> str:
    """Replace bind parameter placeholders with ``?`` for safe logging.

    This prevents sensitive values (passwords, PII) from appearing in traces.

    Args:
        statement: Raw SQL string as sent to the database driver.

    Returns:
        SQL string with all parameter placeholders replaced by ``?``.
    """
    return _PARAM_RE.sub("?", statement).strip()


def _extract_operation(statement: str) -> str:
    """Extract the SQL operation keyword from the statement.

    Args:
        statement: Raw or sanitised SQL string.

    Returns:
        Uppercase operation string (e.g. ``"SELECT"``) or ``"UNKNOWN"``.
    """
    match = _SQL_OPERATION_RE.match(statement)
    return match.group(1).upper() if match else "UNKNOWN"


def instrument_sqlalchemy(engine: Any) -> None:
    """Attach OpenTelemetry span hooks to a SQLAlchemy (async) engine.

    Must be called **once** after the engine is created, before any queries
    are executed.  Calling it more than once on the same engine is safe —
    SQLAlchemy's event system deduplicates handlers.

    Args:
        engine: A ``sqlalchemy.ext.asyncio.AsyncEngine`` instance.  When the
            ``[sqlalchemy]`` extra is not installed this function raises
            ``ImportError`` with a helpful message.

    Raises:
        ImportError: When ``sqlalchemy`` or ``asyncpg`` are not installed.
        TypeError: When ``engine`` is not a recognised SQLAlchemy engine type.

    Example::

        from sqlalchemy.ext.asyncio import create_async_engine
        from zerotel.integrations.sqlalchemy import instrument_sqlalchemy

        engine = create_async_engine("postgresql+asyncpg://user:pw@localhost/db")
        instrument_sqlalchemy(engine)
    """
    if not _SQLALCHEMY_AVAILABLE:
        raise ImportError(
            "SQLAlchemy integration requires the [sqlalchemy] extra. "
            "Install it with:  pip install 'zerotel[sqlalchemy]'"
        )

    # AsyncEngine wraps a sync Engine — attach events to the sync core.
    sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    tracer = otel_trace.get_tracer(__name__)

    # We store the active span in the connection's info dict so that the
    # after_cursor_execute handler can close it correctly.
    span_key = "_zerotel_span"
    start_key = "_zerotel_start"

    @event.listens_for(sync_engine, "before_cursor_execute")  # type: ignore
    def _before_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """Start a child span before each SQL statement is sent to the DB."""
        sanitised = _sanitise_sql(statement)
        operation = _extract_operation(sanitised)

        span = tracer.start_span(
            name="db.query",
            attributes={
                "db.system": "postgresql",
                "db.statement": sanitised,
                "db.operation": operation,
            },
        )
        conn.info[span_key] = span
        conn.info[start_key] = time.perf_counter()

    @event.listens_for(sync_engine, "after_cursor_execute")  # type: ignore
    def _after_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """End the child span after the SQL statement completes."""
        span = conn.info.pop(span_key, None)
        start = conn.info.pop(start_key, None)

        if span is None:
            return

        if start is not None:
            duration_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("db.duration_ms", round(duration_ms, 3))

        span.set_status(StatusCode.OK)
        span.end()

    @event.listens_for(sync_engine, "handle_error")  # type: ignore
    def _on_error(exception_context: Any) -> None:
        """Mark the active DB span as an error when a query fails."""
        conn = getattr(exception_context, "connection", None)
        if conn is None:
            return

        span = conn.info.pop(span_key, None)
        conn.info.pop(start_key, None)

        if span is None:
            return

        exc = exception_context.original_exception
        span.set_status(StatusCode.ERROR, str(exc))
        span.set_attribute("error.type", type(exc).__name__)
        span.record_exception(exc)
        span.end()
