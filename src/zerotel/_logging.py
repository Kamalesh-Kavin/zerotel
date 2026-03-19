"""
zerotel._logging
~~~~~~~~~~~~~~~~

Structured JSON logging configuration for Zerotel.

Calling ``configure_logging()`` replaces the default Python ``logging``
configuration with a structlog pipeline that:

1. Adds a timestamp in ISO-8601 format to every log event.
2. Adds the log level as a string (``"info"``, ``"error"``, etc.).
3. Auto-injects the current ``trace_id`` and ``span_id`` from the active
   request context — so every log line is automatically correlated to its
   trace in Grafana without any manual effort.
4. Serialises the final event dict to a single JSON object per line.

Example output::

    {
      "timestamp": "2024-01-15T10:23:45.123456Z",
      "level": "info",
      "event": "user fetched",
      "service": "my-api",
      "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
      "span_id": "00f067aa0ba902b7",
      "user_id": 42
    }

Usage::

    import structlog
    from zerotel._logging import configure_logging

    configure_logging(service_name="my-api", level="INFO")
    log = structlog.get_logger()
    log.info("user fetched", user_id=42)

The logger is a drop-in replacement for the standard ``logging`` module in
terms of API (``log.info``, ``log.warning``, ``log.error``, ``log.debug``).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from zerotel._context import get_span_id, get_trace_id


def _inject_trace_context(
    logger: Any,
    method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor: inject trace_id and span_id into every log record.

    This processor is inserted into the structlog chain so that every log
    call automatically includes the W3C-compatible trace and span IDs of
    the currently active request.  When there is no active request context
    (e.g. startup logs), both values fall back to all-zero strings.

    Args:
        logger: The bound structlog logger (unused — required by processor API).
        method: The log method name (``"info"``, ``"error"``, etc.).
        event_dict: The mutable event dictionary being built up by the chain.

    Returns:
        The event dictionary with ``trace_id`` and ``span_id`` added.
    """
    event_dict["trace_id"] = get_trace_id()
    event_dict["span_id"] = get_span_id()
    return event_dict


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Configure structlog for structured JSON output.

    This function should be called **once** at application startup, before
    any log calls are made.  ``Zerotel.__init__`` calls it automatically
    when ``ZerotelConfig.enable_logging`` is ``True``.

    Calling it multiple times is safe — subsequent calls overwrite the
    previous configuration.

    Args:
        service_name: Injected into every log line as the ``"service"`` field.
            Use the same value as ``ZerotelConfig.service_name`` for consistent
            correlation across traces, metrics, and logs.
        level: Minimum log level to emit.  Must be a valid Python logging level
            string: ``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ``"ERROR"``,
            ``"CRITICAL"``.  Defaults to ``"INFO"``.

    Example::

        from zerotel._logging import configure_logging
        configure_logging(service_name="payments-api", level="DEBUG")
    """
    # -----------------------------------------------------------------------
    # 1.  Configure the stdlib root logger to route everything to stdout
    #     at the requested level.  structlog will take over formatting.
    # -----------------------------------------------------------------------
    logging.basicConfig(
        format="%(message)s",  # structlog writes the full JSON line here
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    # -----------------------------------------------------------------------
    # 2.  Build the shared processor chain.
    #     Each processor receives (logger, method, event_dict) and must return
    #     the (possibly mutated) event_dict — or raise DropEvent to suppress.
    # -----------------------------------------------------------------------
    shared_processors: list[Any] = [
        # Add log level string ("info", "error", ...)
        structlog.stdlib.add_log_level,
        # Add ISO-8601 UTC timestamp
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Inject trace_id + span_id from the active request context
        _inject_trace_context,
        # Always add the service name
        structlog.stdlib.ExtraAdder(),
    ]

    # -----------------------------------------------------------------------
    # 3.  Wire structlog into the stdlib logging pipeline so that third-party
    #     libraries that use ``logging.getLogger(__name__)`` also emit JSON.
    # -----------------------------------------------------------------------
    structlog.configure(
        processors=[
            *shared_processors,
            # Render the final dict as a compact JSON string
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bind the service name globally so it appears on every log line without
    # the caller having to pass it each time.
    structlog.contextvars.bind_contextvars(service=service_name)
