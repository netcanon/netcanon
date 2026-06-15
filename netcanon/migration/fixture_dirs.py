"""Canonical map from real-capture *fixture directory label* to *codec
registry name* — the single source of truth shared by the offline
audit harness (``tools/run_full_mesh.py`` /
``tools/run_phase4_reconciliation.py``) and the real-capture test
(``tests/unit/migration/test_real_captures.py``).

The two layouts speak different vocabularies: the fixture tree under
``tests/fixtures/real/`` uses human-short vendor labels (``fortigate``
/ ``mikrotik`` / ``junos``) while the codec registry uses
format-qualified names (``fortigate_cli`` / ``mikrotik_routeros`` /
``juniper_junos``).  This table bridges the two.

Historically this dict was hand-replicated in both the audit script and
the test module with no equality assertion; the copies drifted at least
once (see project memory).  Extracting it here makes that class of drift
impossible — both consumers import the same object.  It lives in the
``netcanon`` package (not under ``tests/``) so the audit *scripts* can
import it without pulling the pytest harness into scope.

When adding a fixture directory: add one row here.  The
``test_every_fixture_dir_has_codec_mapping`` guard in the real-capture
test fails loud if a directory on disk has no mapping.
"""

from __future__ import annotations

#: Fixture-directory label -> codec registry name.
DIR_TO_CODEC_NAME: dict[str, str] = {
    "cisco_iosxe":  "cisco_iosxe_cli",
    "cisco_iosxr":  "cisco_iosxr",
    "cisco_nxos":   "cisco_nxos",
    "aruba_aoscx":  "aruba_aoscx",
    "aruba_aoss":   "aruba_aoss",
    "fortigate":    "fortigate_cli",
    "opnsense":     "opnsense",
    "mikrotik":     "mikrotik_routeros",
    "arista_eos":   "arista_eos",
    "junos":        "juniper_junos",
    "vyos":         "vyos",
}
