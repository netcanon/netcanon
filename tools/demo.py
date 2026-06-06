"""Compatibility shim — the demo now lives in the ``netcanon`` package.

`python tools/demo.py ...` continues to work from a source checkout (it
re-exports :func:`netcanon.tools.demo.main`).  Operators who installed
via ``pip install netcanon`` — or who run the Docker image — should use
the shipped CLI instead, since this repo-root script is NOT packaged
into the wheel/image::

    netcanon demo --pair cisco__junos
    docker run --rm --entrypoint netcanon \\
        ghcr.io/netcanon/netcanon:latest demo --pair cisco__junos

The scenario definitions live in ``netcanon/tools/demo.py`` (the single
source of truth, shared by this shim and the ``netcanon demo`` CLI
subcommand).
"""

from __future__ import annotations

import sys

from netcanon.tools.demo import main

if __name__ == "__main__":
    sys.exit(main())
