"""
zerotel._decorators
~~~~~~~~~~~~~~~~~~~

The ``@trace`` decorator — add a named child span to any function.

Works transparently on both ``async def`` and regular ``def`` functions.
The correct wrapper is chosen at decoration time (not at call time) so there
is zero runtime overhead from the async-detection branch.

Basic usage::

    from zerotel import trace

    @trace
    async def fetch_user(user_id: int) -> dict:
        ...  # this entire function becomes a child span

    @trace(name="compute-risk-score")
    def compute_score(data: list[float]) -> float:
        ...  # named span — overrides the default function-name label

The child span is automatically nested under the active parent span for the
current request (set by ``ZerotelMiddleware``).  If there is no active span
(e.g. called from a CLI script or test without a running server), a new root
span is created instead — the decorator never raises due to missing context.

Span attributes set automatically:

* ``code.function`` — fully qualified function name (``module.function``)
* ``code.filepath`` — source file path
* ``error.type`` — exception class name (only on exception)
* ``error.message`` — exception message (only on exception)

Additional attributes can be attached to the active span at any point inside
the decorated function::

    from opentelemetry import trace

    @trace(name="send-email")
    async def send_email(user_id: int) -> None:
        span = trace.get_current_span()
        span.set_attribute("email.user_id", user_id)
        ...
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, overload

from opentelemetry import trace as otel_trace
from opentelemetry.trace import StatusCode

# Generic callable type — preserves the wrapped function's signature in IDEs
_F = TypeVar("_F", bound=Callable[..., Any])


def _make_span_name(fn: Callable[..., Any], override: str | None) -> str:
    """Build the span name from the function or an explicit override.

    Args:
        fn: The function being decorated.
        override: Caller-supplied span name, or ``None`` to derive from ``fn``.

    Returns:
        A dot-separated ``"module.qualname"`` string, or just the override.
    """
    if override:
        return override
    module = getattr(fn, "__module__", "") or ""
    qualname = getattr(fn, "__qualname__", fn.__name__)
    return f"{module}.{qualname}" if module else qualname


def _build_base_attributes(fn: Callable[..., Any]) -> dict[str, str]:
    """Return span attributes describing the decorated function's source.

    Args:
        fn: The function being decorated.

    Returns:
        Dict with ``code.function`` and ``code.filepath`` attributes.
    """
    try:
        filepath = inspect.getfile(fn)
    except (TypeError, OSError):
        filepath = "<unknown>"

    return {
        "code.function": getattr(fn, "__qualname__", fn.__name__),
        "code.filepath": filepath,
    }


def _wrap_async(fn: _F, span_name: str, attributes: dict[str, str]) -> _F:
    """Return an async wrapper that runs ``fn`` inside a child span.

    The tracer is resolved lazily at call time (not at decoration time) so
    that test fixtures can swap the global ``TracerProvider`` after decorating.

    Args:
        fn: The original async coroutine function.
        span_name: Name used for the OpenTelemetry span.
        attributes: Base span attributes (code.function, code.filepath).

    Returns:
        A new coroutine function with identical signature.
    """

    @functools.wraps(fn)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        # Resolve the tracer lazily so tests can swap providers after decoration
        tracer = otel_trace.get_tracer(__name__)
        with tracer.start_as_current_span(span_name, attributes=attributes) as span:
            try:
                result = await fn(*args, **kwargs)
                span.set_status(StatusCode.OK)
                return result
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                span.record_exception(exc)
                raise

    return async_wrapper  # type: ignore[return-value]


def _wrap_sync(fn: _F, span_name: str, attributes: dict[str, str]) -> _F:
    """Return a sync wrapper that runs ``fn`` inside a child span.

    The tracer is resolved lazily at call time (not at decoration time) so
    that test fixtures can swap the global ``TracerProvider`` after decorating.

    Args:
        fn: The original synchronous callable.
        span_name: Name used for the OpenTelemetry span.
        attributes: Base span attributes (code.function, code.filepath).

    Returns:
        A new callable with identical signature.
    """

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        # Resolve the tracer lazily so tests can swap providers after decoration
        tracer = otel_trace.get_tracer(__name__)
        with tracer.start_as_current_span(span_name, attributes=attributes) as span:
            try:
                result = fn(*args, **kwargs)
                span.set_status(StatusCode.OK)
                return result
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("error.message", str(exc))
                span.record_exception(exc)
                raise

    return sync_wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public decorator — two call styles supported:
#
#   @trace                        → uses function name as span name
#   @trace(name="my-span")       → uses explicit span name
# ---------------------------------------------------------------------------


@overload
def trace(fn: _F) -> _F: ...  # @trace without parentheses


@overload
def trace(*, name: str | None = None) -> Callable[[_F], _F]: ...  # @trace(name=...)


def trace(
    fn: _F | None = None,
    *,
    name: str | None = None,
) -> _F | Callable[[_F], _F]:
    """Decorator that wraps a function in an OpenTelemetry child span.

    Can be used with or without parentheses:

    .. code-block:: python

        @trace
        async def my_func(): ...          # span name = "module.my_func"

        @trace(name="custom-span-name")
        def my_func(): ...                # span name = "custom-span-name"

    Args:
        fn: The function to decorate (when used without parentheses).
        name: Optional explicit span name.  When omitted, the span is named
            after the decorated function (``"module.qualname"``).

    Returns:
        The decorated function, or a decorator when called with ``name=``.
    """

    def decorator(func: _F) -> _F:
        span_name = _make_span_name(func, name)
        attributes = _build_base_attributes(func)

        if asyncio.iscoroutinefunction(func):
            return _wrap_async(func, span_name, attributes)
        else:
            return _wrap_sync(func, span_name, attributes)

    # Called as @trace (no parentheses) — fn is the decorated function
    if fn is not None:
        return decorator(fn)

    # Called as @trace(...) — return the decorator
    return decorator
