"""
zerotel._cli
~~~~~~~~~~~~

Command-line interface for zerotel.

Provides the ``zerotel`` command that is installed as a script entry-point
when you ``pip install zerotel``.  It does not start a server — zerotel is a
library, not a daemon.  The CLI is a quick-reference tool so developers can:

  - confirm the package is installed and find its version
  - print the full configuration reference without opening a browser
  - print a copy-pasteable quickstart snippet

Usage::

    zerotel --help
    zerotel --version
    zerotel info
    zerotel config
    zerotel quickstart
"""

from __future__ import annotations

import argparse
import sys
import textwrap

from zerotel import __version__

# ──────────────────────────────────────────────────────────────────────────────
# Colour helpers (degrades gracefully on non-TTY / Windows)
# ──────────────────────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"


def _c(text: str, *codes: str) -> str:
    """Wrap *text* in ANSI escape codes only when stdout is a real TTY."""
    if not sys.stdout.isatty():
        return text
    return "".join(codes) + text + _RESET


# ──────────────────────────────────────────────────────────────────────────────
# Sub-command handlers
# ──────────────────────────────────────────────────────────────────────────────


def _cmd_info(_args: argparse.Namespace) -> None:
    """Print a short summary of what zerotel is and where to find docs."""
    print(
        textwrap.dedent(
            f"""\

            {_c("zerotel", _BOLD, _CYAN)}  {_c(f"v{__version__}", _DIM)}

            Zero-config observability SDK for Python services.
            Instruments FastAPI apps with:
              {_c("→", _GREEN)} OpenTelemetry distributed traces  (OTLP gRPC)
              {_c("→", _GREEN)} Prometheus metrics                (/metrics)
              {_c("→", _GREEN)} Structured JSON logs              (structlog)

            {_c("Docs:", _BOLD)}      https://github.com/Kamalesh-Kavin/zerotel/tree/main/docs
            {_c("PyPI:", _BOLD)}      https://pypi.org/project/zerotel/
            {_c("Issues:", _BOLD)}    https://github.com/Kamalesh-Kavin/zerotel/issues

            Run  {_c("zerotel quickstart", _YELLOW)}  to see a copy-pasteable example.
            Run  {_c("zerotel config", _YELLOW)}      to see all configuration options.
            """
        )
    )


def _cmd_quickstart(_args: argparse.Namespace) -> None:
    """Print a minimal working FastAPI example."""
    snippet = textwrap.dedent(
        """\
        # ── install ───────────────────────────────────────────────────────────
        # pip install zerotel uvicorn

        # ── main.py ───────────────────────────────────────────────────────────
        from fastapi import FastAPI
        from zerotel import Zerotel, trace

        app = FastAPI()

        # One line — traces + metrics + structured logs, all wired up.
        Zerotel(app, service_name="my-api")


        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}


        @app.get("/users/{user_id}")
        async def get_user(user_id: int) -> dict[str, int]:
            score = compute_score(user_id)
            return {"user_id": user_id, "score": score}


        # @trace creates a child span — works on both sync and async functions.
        @trace(name="compute-score")
        def compute_score(user_id: int) -> int:
            return user_id * 42


        # ── run ───────────────────────────────────────────────────────────────
        # uvicorn main:app --reload
        #
        # Then:
        #   curl http://localhost:8000/health
        #   curl http://localhost:8000/users/1
        #   curl http://localhost:8000/metrics
        """
    )
    print(_c("── Quickstart ──────────────────────────────────────────────────────", _DIM))
    print()
    # Print with syntax highlighting if pygments is available (optional dep)
    try:
        from pygments import highlight  # type: ignore
        from pygments.formatters import TerminalFormatter  # type: ignore
        from pygments.lexers import PythonLexer  # type: ignore

        print(highlight(snippet, PythonLexer(), TerminalFormatter()))
    except ImportError:
        # pygments not installed — just print plain text
        print(snippet)
    print(_c("────────────────────────────────────────────────────────────────────", _DIM))


def _cmd_config(_args: argparse.Namespace) -> None:
    """Print every ZerotelConfig field with its type, default, and description."""
    print(
        textwrap.dedent(
            f"""\

            {_c("ZerotelConfig — all fields", _BOLD, _CYAN)}

            Pass a ZerotelConfig instance for full control:

              from zerotel import Zerotel, ZerotelConfig
              Zerotel(app, config=ZerotelConfig(
                  service_name      = "my-api",
                  otlp_endpoint     = "http://localhost:4317",
                  enable_traces     = True,
                  enable_metrics    = True,
                  enable_logging    = True,
                  exclude_paths     = ["/health", "/metrics"],
                  log_request_body  = False,
                  trace_sample_rate = 1.0,
                  service_version   = "0.0.0",
                  metrics_endpoint  = "/metrics",
              ))

            {_c("Field reference:", _BOLD)}

              {_c("service_name", _YELLOW)}       str          required
                  Identifies this service in traces, metrics labels, and log lines.

              {_c("otlp_endpoint", _YELLOW)}      str          "http://localhost:4317"
                  gRPC endpoint of your OpenTelemetry Collector.

              {_c("enable_traces", _YELLOW)}      bool         True
                  Export spans via OTLP.  Set False to use no-op tracer.

              {_c("enable_metrics", _YELLOW)}     bool         True
                  Mount a Prometheus /metrics endpoint on the app.

              {_c("enable_logging", _YELLOW)}     bool         True
                  Configure structlog JSON output with trace context injected.

              {_c("exclude_paths", _YELLOW)}      list[str]    ["/health", "/metrics"]
                  Paths that generate no spans and are excluded from metric labels.

              {_c("log_request_body", _YELLOW)}   bool         False
                  Log raw request bodies (careful — may leak PII).

              {_c("trace_sample_rate", _YELLOW)}  float        1.0
                  Fraction of requests to sample.  0.1 = 10 %, 1.0 = 100 %.

              {_c("service_version", _YELLOW)}    str          "0.0.0"
                  Appears as a resource attribute in Grafana Tempo.

              {_c("metrics_endpoint", _YELLOW)}   str          "/metrics"
                  Path where Prometheus scrapes metrics.
            """
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# Parser
# ──────────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zerotel",
        description=(
            "zerotel — zero-config observability SDK for Python services.\n"
            "Instruments FastAPI apps with traces, metrics, and structured logs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            commands:
              info        Show version, links, and a short description
              quickstart  Print a copy-pasteable FastAPI example
              config      Print all ZerotelConfig fields and their defaults

            examples:
              zerotel info
              zerotel quickstart
              zerotel config
            """
        ),
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"zerotel {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    subparsers.add_parser("info", help="Show version, links, and a short description")
    subparsers.add_parser("quickstart", help="Print a copy-pasteable FastAPI example")
    subparsers.add_parser("config", help="Print all ZerotelConfig fields and their defaults")

    return parser


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point registered in pyproject.toml as ``zerotel = zerotel._cli:main``."""
    parser = _build_parser()
    args = parser.parse_args()

    dispatch = {
        "info": _cmd_info,
        "quickstart": _cmd_quickstart,
        "config": _cmd_config,
    }

    if args.command is None:
        # No sub-command given — show the full help (mirrors `--help` behaviour)
        parser.print_help()
        sys.exit(0)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
