"""
Translator / migration engine — Phase 0.

Scope (see ``translator-plans.txt`` §12):
    * CodecBase + CapabilityMatrix contract.
    * In-memory codec registry.
    * One reference codec (``_mock``) that round-trips a trivial
      dict-of-strings "tree" so the contract itself is testable
      without any real YANG tooling.
    * Capability-matrix-driven ``ValidationReport`` and a thin
      ``run_plan`` pipeline skeleton (``netconfig/services/``).

Out of scope for Phase 0 (queued for Phase 0.5+):
    * libyang-backed canonical tree (``canonical/loader.py`` is a stub).
    * Transforms, deploy, snapshot (Phase 2+).

Importing this package auto-discovers every codec sub-package under
``netconfig/migration/codecs/`` and imports it, firing its module-
level ``@register`` decorator.  Adding a new codec is therefore a
drop-in: create ``netconfig/migration/codecs/<vendor>/__init__.py``
that imports ``<vendor>.codec`` (so the ``@register`` call runs) and
the translator picks it up at next process start — no edit to this
file required.

Malformed codec packages are logged and skipped; one broken codec
does not take down the rest of the registry.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from . import codecs as _codecs_pkg

logger = logging.getLogger(__name__)


def _discover_and_register_codecs() -> None:
    """Walk ``netconfig/migration/codecs/`` and import every package.

    Side-effect: each codec module's module-level ``@register`` call
    fires, populating the registry.

    Packages whose name starts with an underscore are still loaded —
    the reference ``_mock`` codec uses that prefix as a "leading
    underscore = internal" convention, NOT an import filter.  Real
    private helper modules should live in ``codecs/`` as regular
    modules (not packages) or under a ``_private`` sub-package.
    """
    for mod_info in pkgutil.iter_modules(
        _codecs_pkg.__path__,
        prefix=_codecs_pkg.__name__ + ".",
    ):
        if not mod_info.ispkg:
            # Top-level ``base`` and ``registry`` modules aren't codecs.
            continue
        try:
            importlib.import_module(mod_info.name)
        except Exception:  # pragma: no cover — resilience test
            # A malformed codec package shouldn't crash the whole
            # application — the others should still register.
            logger.exception(
                "migration: failed to import codec package %s; "
                "skipping.", mod_info.name,
            )


_discover_and_register_codecs()


# Vendor declarations are loaded lazily via load_vendors() at app
# startup, NOT at import time — so tests can run without the YAML
# files.
from .vendors import load_vendors  # noqa: E402,F401 — re-export
