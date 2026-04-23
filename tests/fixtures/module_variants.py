"""
Canonical allowlist of shipped target profiles that have opted in
to the module-variant schema.

Previously duplicated as two identical literal sets — one in
``tests/unit/migration/test_target_profile_shipped.py`` and one in
``tests/integration/test_migration_target_profiles_api.py`` — with
a "kept in sync manually" comment on each.  Both files now import
this single source; a new module-variant profile requires exactly
one update, here.

The allowlist is used two ways:

1. **Regression guard (unit + integration):** profiles outside the
   set must still serialise ``modules == {}`` so pre-milestone-2
   clients see a stable shape.  Profiles inside must actually
   declare ``modules:`` in their YAML.
2. **Sync invariant (trivial now):** once both tests import from
   here the two tiers can't disagree on which profiles are
   module-variant.

When migrating a profile to the module-variant schema:

* Add its ``{vendor}/{model}`` key below.
* Update the YAML to declare ``modules:`` with one entry per
  swappable SKU.
* Both test files pick up the change automatically.

Keep the set literal-only (no generated values) so a `git diff`
of this file is human-readable.
"""

from __future__ import annotations


MODULE_VARIANT_PROFILES: frozenset[str] = frozenset({
    "cisco_iosxe/C9300-24P",
    "cisco_iosxe/C9300-24U",
    "cisco_iosxe/C9300-24UX",
    "cisco_iosxe/C9300-48P",
    "cisco_iosxe/C9300-48U",
    "cisco_iosxe/C9300-48UXM",
    "aruba_aoss/3810M-24G-PoEP",
    "aruba_aoss/3810M-48G-PoEP",
})
"""Target-profile keys (``{vendor}/{model}``) that have opted in
to the module-variant schema.  Every entry here MUST have a
non-empty ``modules:`` block in its YAML; every profile OUTSIDE
this set MUST keep ``modules: {}`` (default)."""
