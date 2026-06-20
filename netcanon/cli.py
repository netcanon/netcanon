"""Netcanon command-line interface.

Subcommands:

* ``netcanon sanitize`` — redact PII from a network config for safe sharing.
* ``netcanon demo`` — run a self-contained cross-vendor translation demo.

Run via the entry point declared in ``pyproject.toml`` ``[project.scripts]``::

    netcanon sanitize -i my-config.txt -o sanitised.txt \\
        --source-vendor cisco_iosxe_cli

Direct module invocation also works::

    python -m netcanon.cli sanitize ...

The CLI is the recommended invocation path for operators who haven't
deployed the FastAPI server (one-shot ``pip install netcanon`` users,
CI / scripting paths).  Operators running the server (Docker, embedded
desktop, etc.) should use the equivalent ``POST /api/v1/sanitize`` HTTP
endpoint — both invocations call the same shared library, so behaviour
is identical.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Entry point — invoked by ``netcanon`` console script."""
    parser = argparse.ArgumentParser(
        prog="netcanon",
        description="Netcanon — multi-vendor network config translator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    s = subparsers.add_parser(
        "sanitize",
        help="Redact PII from a network config for safe sharing",
        description=(
            "Parse a network config, apply field-typed PII redactions "
            "to the canonical model, then re-render in the same vendor's "
            "format.  See netcanon.tools.sanitize for the full rules."
        ),
    )
    s.add_argument(
        "-i", "--input",
        required=True,
        help="Path to input config file",
    )
    s.add_argument(
        "-o", "--output",
        help="Output path; omit to write sanitized config to stdout",
    )
    s.add_argument(
        "-s", "--source-vendor",
        required=True,
        help=(
            "Source codec name (e.g. cisco_iosxe_cli, fortigate_cli, "
            "juniper_junos, arista_eos, aruba_aoss, mikrotik_routeros, "
            "opnsense, cisco_iosxe)"
        ),
    )
    s.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the substitution table without writing output.  "
            "Use this to preview redactions before committing — "
            "operators running on real network captures should always "
            "do a dry-run first."
        ),
    )

    # ``netcanon demo`` — the scenarios live in netcanon.tools.demo (the
    # single source of truth, shared with the repo-root tools/demo.py shim);
    # validation of --pair is delegated there to keep `netcanon --help` from
    # importing the codec registry.
    demo_parser = subparsers.add_parser(
        "demo",
        help="Run a self-contained cross-vendor translation demo (no setup)",
        description=(
            "Translate a small embedded synthetic config between two vendors "
            "using the same pipeline + codec registry as the API.  Pass "
            "--list to see every available scenario."
        ),
    )
    demo_parser.add_argument(
        "--pair",
        default="cisco__junos",
        help="Source__target codec pair (default: cisco__junos); --list to see all",
    )
    demo_parser.add_argument(
        "--list",
        action="store_true",
        help="List all available demo scenarios and exit",
    )

    subparsers.add_parser(
        "serve",
        help="Run the Netcanon web server (host/port/auth from NETCANON_* env)",
        description=(
            "Start the FastAPI app via uvicorn, binding Settings.host:port "
            "(NETCANON_HOST / NETCANON_PORT, default 0.0.0.0:8000).  Refuses "
            "to start on a non-loopback bind unless NETCANON_API_KEY is set "
            "or NETCANON_ALLOW_INSECURE_BIND=1 (SEC-01 fail-closed)."
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "sanitize":
        return _cmd_sanitize(args)
    if args.command == "demo":
        # Lazy import — keeps `netcanon --help` and `netcanon sanitize`
        # from loading the codec registry / pipeline graph the demo pulls in.
        from .tools.demo import main as _demo_main

        demo_argv = ["--list"] if args.list else ["--pair", args.pair]
        return _demo_main(demo_argv)
    if args.command == "serve":
        return _cmd_serve(args)
    return 1


def _cmd_sanitize(args: argparse.Namespace) -> int:
    """``netcanon sanitize`` subcommand handler."""
    # Lazy import — keeps `netcanon --help` fast and avoids loading
    # the migration codec graph for non-sanitize subcommands.
    from .migration.codecs.base import ParseError
    from .tools.sanitize import sanitize_text

    try:
        raw = Path(args.input).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"error: cannot read {args.input!r}: {e}", file=sys.stderr)
        return 2

    try:
        result = sanitize_text(
            raw,
            args.source_vendor,
            dry_run=args.dry_run,
        )
    except ValueError as e:
        # Unknown source_vendor
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ParseError as e:
        print(
            f"error: failed to parse {args.input!r} as "
            f"{args.source_vendor!r}: {e}",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(f"=== Substitution audit ({len(result.substitutions)} entries) ===")
        for sub in result.substitutions:
            # Truncate long values for readability in the dry-run table
            orig = sub.original if len(sub.original) <= 50 else sub.original[:47] + "..."
            redact = sub.redacted if len(sub.redacted) <= 50 else sub.redacted[:47] + "..."
            print(f"  [{sub.category}] {sub.field}")
            print(f"    {orig!r}")
            print(f"    -> {redact!r}")
        print(f"\n{len(result.substitutions)} substitutions identified.")
        print("Run again without --dry-run to write the sanitized output.")
        return 0

    if args.output:
        Path(args.output).write_text(result.sanitized_text, encoding="utf-8")
        print(
            f"Sanitized output written to {args.output} "
            f"({len(result.substitutions)} substitutions applied).",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(result.sanitized_text)
        print(
            f"\n{len(result.substitutions)} substitutions applied.",
            file=sys.stderr,
        )

    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """``netcanon serve`` — boot the web server with a fail-closed bind guard.

    Refuses to start on a non-loopback bind with no API key and no
    explicit opt-out (SEC-01), so accidental public exposure is a
    conscious choice rather than the zero-config default.
    """
    from .api.auth import bind_refusal_reason
    from .config import Settings

    settings = Settings()
    reason = bind_refusal_reason(
        settings.host, settings.api_key, settings.allow_insecure_bind
    )
    if reason:
        print(f"error: {reason}", file=sys.stderr)
        return 2

    # Lazy import — keeps `netcanon --help` / sanitize fast and avoids
    # building the app on the refusal path.
    import uvicorn

    uvicorn.run(
        "netcanon.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
