"""
zerotel._context
~~~~~~~~~~~~~~~~

Per-request context storage using Python's ``contextvars``.

Each incoming request gets its own ``RequestContext`` stored in a
``ContextVar``.  Any code running within that request — middleware,
route handlers, background tasks spawned by the same task — can read the
current trace ID and span ID without having to thread them through function
arguments.

Usage::

    from zerotel._context import get_request_context, request_context_var

    ctx = get_request_context()
    if ctx:
        print(ctx.trace_id)   # "4bf92f3577b34da6a3ce929d0e0e4736"
        print(ctx.span_id)    # "00f067aa0ba902b7"

The context is set by ``ZerotelMiddleware`` at the start of every request
and automatically cleaned up when the request finishes (context vars are
per-task, so no explicit cleanup is required for async code).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RequestContext:
    """Immutable snapshot of observability identifiers for one request.

    Attributes:
        trace_id: 32-character hex string identifying the distributed trace.
            Matches the W3C ``traceparent`` trace-id field.
        span_id: 16-character hex string identifying the current span within
            the trace.
        service_name: Name of the service that owns this request, taken from
            ``ZerotelConfig.service_name``.
        request_id: Optional application-level request ID.  Populated from the
            ``X-Request-ID`` header when present; otherwise identical to
            ``trace_id``.
    """

    trace_id: str
    span_id: str
    service_name: str
    request_id: str = field(default="")

    def __post_init__(self) -> None:
        # Fall back to trace_id when no explicit request-id header was sent
        if not self.request_id:
            self.request_id = self.trace_id


# Module-level ContextVar — one slot per async task / thread.
# The default is None so callers can detect "no active request context".
request_context_var: ContextVar[RequestContext | None] = ContextVar(
    "zerotel_request_context", default=None
)


def get_request_context() -> RequestContext | None:
    """Return the ``RequestContext`` for the currently executing request.

    Returns ``None`` when called outside of a request (e.g. during startup,
    in a background thread, or in tests that do not set up context).

    Example::

        from zerotel._context import get_request_context

        def my_helper():
            ctx = get_request_context()
            trace_id = ctx.trace_id if ctx else "n/a"
    """
    return request_context_var.get()


def get_trace_id() -> str:
    """Return the current trace ID or ``"0000000000000000"`` if unavailable.

    Convenience wrapper so callers never have to handle ``None``.
    """
    ctx = get_request_context()
    return ctx.trace_id if ctx else "0" * 32


def get_span_id() -> str:
    """Return the current span ID or ``"0000000000000000"`` if unavailable."""
    ctx = get_request_context()
    return ctx.span_id if ctx else "0" * 16
