"""Netcanon command-line interface.

Subcommands:

* ``netcanon sanitize`` — redact PII from a network config for safe sharing.

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

    args = parser.parse_args(argv)

    if args.command == "sanitize":
        return _cmd_sanitize(args)
    return 1


def _cmd_sanitize(args: argparse.Namespace) -> int:
    """``netcanon sanitize`` subcommand handler."""
    # Lazy import — keeps `netcanon --help` fast and avoids loading
    # the migration codec graph for non-sanitize subcommands.
    from .tools.sanitize import sanitize_text
    from .migration.codecs.base import ParseError

    raw = Path(args.input).read_text(encoding="utf-8", errors="replace")

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


if __name__ == "__main__":
    sys.exit(main())
