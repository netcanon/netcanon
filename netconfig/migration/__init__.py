"""
Translator / migration engine — Phase 0.

Scope (see ``translator-plans.txt`` §12):
    * CodecBase + CapabilityMatrix contract.
    * In-memory adapter registry.
    * One reference adapter (``_mock``) that round-trips a trivial
      dict-of-strings "tree" so the contract itself is testable
      without any real YANG tooling.
    * Capability-matrix-driven ``ValidationReport`` and a thin
      ``run_plan`` pipeline skeleton (``netconfig/services/``).

Out of scope for Phase 0 (queued for Phase 0.5+):
    * libyang-backed canonical tree (``canonical/loader.py`` is a stub).
    * Real vendor adapters — Cisco IOS-XE is the first concrete
      adapter in Phase 0.5; FortiGate / OPNsense / MikroTik arrive
      through Phase 1.
    * Transforms, deploy, snapshot, and UI routes (Phase 2+).

Importing this package auto-registers the built-in adapters via their
own module-level ``@register`` decorators.
"""

# Import built-in codecs so their @register decorators fire.
# New codecs should add themselves here when they land.
from .codecs import _mock  # noqa: F401 — side-effect import (register)
from .codecs import cisco_iosxe  # noqa: F401 — side-effect import (register)
from .codecs import cisco_iosxe_cli  # noqa: F401 — side-effect import (register)
from .codecs import mikrotik_routeros  # noqa: F401 — side-effect import (register)
from .codecs import opnsense  # noqa: F401 — side-effect import (register)

# Vendor declarations are loaded lazily via load_vendors() at app startup,
# NOT at import time — so tests can run without the YAML files.
from .vendors import load_vendors  # noqa: F401 — re-exported for convenience
