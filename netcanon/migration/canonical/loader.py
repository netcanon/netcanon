"""
libyang context + schema loader — STUB.

Phase 0 does not require libyang to be installed.  This module exists
so future Phase-0.5 code has a stable import path and tests that
import ``netcanon.migration.canonical.loader`` don't need to be
rewritten when the real implementation lands.

All public surfaces raise :class:`NotImplementedError` with a clear
pointer to the roadmap.  Calling any of them early is a loud error
rather than a silent misbehaviour.
"""

from __future__ import annotations

from typing import Any

#: Pinned path(s) inside the schema directory that the real loader will
#: pull in.  Kept here so contributors can see the planned inventory
#: without opening ``translator-plans.txt``.
PLANNED_MODULES: tuple[str, ...] = (
    "openconfig-interfaces",
    "openconfig-vlan",
    "openconfig-network-instance",
    "openconfig-bgp",
    "openconfig-ospf",
    "openconfig-access-control-list",
    "openconfig-if-ethernet",
    "openconfig-if-ip",
    "netcanon-ext",  # in-repo extensions
)


def get_libyang_context() -> Any:
    """Return a cached libyang context with all canonical modules loaded.

    Raises:
        NotImplementedError: Always, until Phase 0.5 lands.  The real
            implementation will lazily ``import libyang``, build a
            context from ``netcanon/migration/canonical/schema/`` on
            first call, and cache it at module level.
    """
    raise NotImplementedError(
        "libyang context loader is a Phase 0.5 deliverable; "
        "see translator-plans.txt §12. Phase 0 adapters must treat the "
        "tree as adapter-internal and not attempt to validate it here."
    )


def validate_against_canonical(tree: Any) -> None:
    """Validate *tree* against the canonical YANG schemas.

    Raises:
        NotImplementedError: Always, until Phase 0.5 lands.  Adapters
            in Phase 0 must perform any internal consistency checks
            themselves and document what they validate.
    """
    raise NotImplementedError(
        "Canonical validation requires the libyang context — see "
        "get_libyang_context().  Phase 0.5 deliverable."
    )
