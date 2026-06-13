"""
R-21 regression guard: CiscoIOSXECodec (NETCONF) declares "ports" in
``unsupported_rename_categories``, so migrating TO it surfaces ONE amber
pane-compat banner in the migrate UI instead of N per-port "no native
representation" warning rows on the ports pane.

This is the same *declarative* mechanism the codec already uses for
"snmpv3" — a UI hint, NOT a pipeline gate.  ``translate_port_names``
still runs normally: explicit operator rename maps are applied, and the
per-port auto-translate warnings still populate ``job.warnings`` (the UI
just shows the single banner rather than the noisy rows).  Collapsing
those warnings at the pipeline/API level too was evaluated and
deliberately deferred — it entangles with explicit-rename precedence and
``strip_unmappable`` semantics, beyond this P3's scope.
"""
from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe.codec import CiscoIOSXECodec
from netcanon.migration.canonical.port_names import PortIdentity

pytestmark = pytest.mark.unit


class TestCiscoIOSXEUnsupportedRenameCategories:
    def test_ports_declared_unsupported(self):
        """cisco_iosxe (NETCONF) must declare 'ports' in unsupported_rename_categories."""
        codec = CiscoIOSXECodec()
        assert "ports" in codec.unsupported_rename_categories

    def test_snmpv3_still_declared_unsupported(self):
        """Regression: 'snmpv3' must remain in unsupported_rename_categories."""
        codec = CiscoIOSXECodec()
        assert "snmpv3" in codec.unsupported_rename_categories

    def test_classify_port_name_returns_unknown(self):
        """Inherited no-op: classify_port_name returns kind='unknown' (but
        still populates .original per the PortIdentity contract — R-17)."""
        codec = CiscoIOSXECodec()
        ident = codec.classify_port_name("GigabitEthernet1/0/1")
        assert ident.kind == "unknown"
        assert ident.original == "GigabitEthernet1/0/1"

    def test_format_port_identity_returns_none(self):
        """Inherited no-op: format_port_identity returns None — exactly why
        'ports' is declared unsupported as a rename target."""
        codec = CiscoIOSXECodec()
        ident = PortIdentity(kind="physical", port=1, original="Gi1/0/1")
        assert codec.format_port_identity(ident) is None
