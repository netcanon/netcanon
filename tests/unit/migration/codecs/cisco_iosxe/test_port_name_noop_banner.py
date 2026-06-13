"""
R-21 regression guard: CiscoIOSXECodec (NETCONF) declares "ports" in
unsupported_rename_categories, producing an up-front banner warning rather
than N per-port warnings when used as a migration target.
"""
from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe.codec import CiscoIOSXECodec
from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec
from netcanon.migration.canonical.port_names import (
    PortIdentity,
    translate_port_names,
)
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
)

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
        """Inherited no-op: classify_port_name returns kind='unknown'."""
        codec = CiscoIOSXECodec()
        ident = codec.classify_port_name("GigabitEthernet1/0/1")
        assert ident.kind == "unknown"
        assert ident.original == "GigabitEthernet1/0/1"

    def test_format_port_identity_returns_none(self):
        """Inherited no-op: format_port_identity returns None."""
        codec = CiscoIOSXECodec()
        ident = PortIdentity(kind="physical", port=1, original="Gi1/0/1")
        result = codec.format_port_identity(ident)
        assert result is None


class TestTranslatePortNamesBannerBehaviour:
    """Verify the up-front banner path fires for a cisco_iosxe target —
    one banner warning instead of N per-port warnings (Option 2)."""

    def _make_intent_with_interfaces(self, names: list[str]) -> CanonicalIntent:
        intent = CanonicalIntent(
            source_vendor="cisco_iosxe_cli",
            source_format="cli-ios",
        )
        for name in names:
            intent.interfaces.append(CanonicalInterface(name=name))
        return intent

    def test_single_warning_not_per_port(self):
        """With N interfaces, translate_port_names emits exactly 1 warning
        when the target declares 'ports' unsupported."""
        source = CiscoIOSXECLICodec()
        target = CiscoIOSXECodec()
        intent = self._make_intent_with_interfaces([
            "GigabitEthernet1/0/1",
            "GigabitEthernet1/0/2",
            "GigabitEthernet1/0/3",
            "Loopback0",
        ])
        result = translate_port_names(intent, source, target, rename_map={})
        # Single up-front banner, not 4 per-port warnings.
        assert len(result.warnings) == 1
        assert "not supported" in result.warnings[0].lower()

    def test_no_renames_applied(self):
        """No renames when target's port rename is a no-op."""
        source = CiscoIOSXECLICodec()
        target = CiscoIOSXECodec()
        intent = self._make_intent_with_interfaces(["GigabitEthernet1/0/1"])
        result = translate_port_names(intent, source, target, rename_map={})
        assert result.applied == {}

    def test_no_drops(self):
        """No drops when target's port rename is a no-op (interfaces survive verbatim)."""
        source = CiscoIOSXECLICodec()
        target = CiscoIOSXECodec()
        intent = self._make_intent_with_interfaces(["GigabitEthernet1/0/1"])
        result = translate_port_names(intent, source, target, rename_map={})
        assert result.dropped == []
        # Interface name is preserved verbatim.
        assert intent.interfaces[0].name == "GigabitEthernet1/0/1"

    def test_codecs_with_port_translation_unaffected(self):
        """Codecs that DO implement port translation are unaffected by the
        early-exit guard (they don't have 'ports' in unsupported_rename_categories)."""
        from netcanon.migration.codecs.opnsense.codec import OPNsenseCodec

        target = OPNsenseCodec()
        assert "ports" not in target.unsupported_rename_categories
