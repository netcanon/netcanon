"""
FortiGate CLI parse-side regression for the ``set domain`` asymmetry
flagged by the Phase 4b sweep (3 independent agents: arista_eos
source = 1 cell, opnsense source = 5 of 10 cells, cisco_iosxe_cli
source = 2 cells).

The render emits ``set domain "<value>"`` inside ``config system dns``
correctly (``fortigate_cli/render.py`` ~line 450).  But
``_apply_system_dns`` previously only read ``primary`` / ``secondary``,
so ``CanonicalIntent.domain`` round-tripped to ``""`` after
``parse(render(tree))`` -- causing every ``domain -> ''`` drift cell in
the comparator matrix.

The DHCP-pool ``set domain`` handler at ``parse.py`` ~line 707 targets a
different field (``CanonicalDHCPPool.domain_name``, the per-pool
search-domain) and is unaffected.  Regression guard included below.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec

pytestmark = pytest.mark.unit


class TestParseSystemDnsDomain:
    """``config system dns`` / ``set domain`` is now lifted into
    ``CanonicalIntent.domain`` on parse, mirroring the render emit."""

    def test_fortigate_parse_set_domain_in_system_dns(self) -> None:
        """Synthetic minimal FortiOS config: ``set domain`` inside
        ``config system dns`` lands on ``intent.domain``."""
        raw = """\
config system dns
    set domain "example.test"
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert intent.domain == "example.test"

    def test_fortigate_parse_domain_alongside_resolvers(self) -> None:
        """Domain coexists with the existing primary/secondary
        resolver reads -- both populated from the same block."""
        raw = """\
config system dns
    set primary 1.1.1.1
    set secondary 8.8.8.8
    set domain "example.test"
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert intent.domain == "example.test"
        assert intent.dns_servers == ["1.1.1.1", "8.8.8.8"]

    def test_fortigate_parse_no_domain_leaves_intent_default(self) -> None:
        """Negative case: ``config system dns`` without ``set domain``
        leaves ``intent.domain`` at its CanonicalIntent default."""
        raw = """\
config system dns
    set primary 1.1.1.1
end
"""
        intent = FortiGateCLICodec().parse(raw)
        # Domain unset -> default (empty string per CanonicalIntent).
        assert intent.domain == ""
        assert intent.dns_servers == ["1.1.1.1"]


class TestRoundTripDomainPreserved:
    """Full ``parse(render(tree))`` round-trip: ``intent.domain``
    survives both legs."""

    def test_fortigate_round_trip_domain_preserved(self) -> None:
        tree = CanonicalIntent(
            source_vendor="test",
            source_format="test",
            hostname="fg",
            domain="example.test",
        )
        codec = FortiGateCLICodec()
        rendered = codec.render(tree)
        # Sanity: the render leg actually emitted the line we expect
        # the parse leg to read back.
        assert 'set domain "example.test"' in rendered
        parsed = codec.parse(rendered)
        assert parsed.domain == "example.test"

    def test_fortigate_round_trip_domain_with_resolvers(self) -> None:
        """Domain + resolvers round-trip together (both fields share
        the same ``config system dns`` block on the wire)."""
        tree = CanonicalIntent(
            source_vendor="test",
            source_format="test",
            hostname="fg",
            domain="corp.local",
            dns_servers=["1.1.1.1", "8.8.8.8"],
        )
        codec = FortiGateCLICodec()
        parsed = codec.parse(codec.render(tree))
        assert parsed.domain == "corp.local"
        assert parsed.dns_servers == ["1.1.1.1", "8.8.8.8"]


class TestDhcpPoolSetDomainUnchanged:
    """Regression guard: the pre-existing DHCP-pool ``set domain``
    handler in ``_apply_system_dhcp_server`` (~``parse.py`` line 707)
    targets ``CanonicalDHCPPool.domain_name`` -- a different field in
    a different scope.  Adding the system-DNS domain read must not
    perturb it."""

    def test_fortigate_parse_dhcp_set_domain_unchanged(self) -> None:
        raw = """\
config system dhcp server
    edit 1
        set lease-time 3600
        set default-gateway 192.168.10.1
        set netmask 255.255.255.0
        set interface "port1"
        set dns-server1 1.1.1.1
        set domain "pool.example"
        config ip-range
            edit 1
                set start-ip 192.168.10.100
                set end-ip 192.168.10.199
            next
        end
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        # Pool-level field populated as before.
        assert len(intent.dhcp_servers) == 1
        assert intent.dhcp_servers[0].domain_name == "pool.example"
        # System-level domain stays at default -- the pool's
        # ``set domain`` belongs to the pool, not the system.
        assert intent.domain == ""

    def test_fortigate_parse_both_scopes_independently(self) -> None:
        """Both ``config system dns`` ``set domain`` AND a pool's
        ``set domain`` populate their respective targets without
        cross-contamination."""
        raw = """\
config system dns
    set domain "system.example"
end
config system dhcp server
    edit 1
        set default-gateway 192.168.10.1
        set netmask 255.255.255.0
        set interface "port1"
        set domain "pool.example"
        config ip-range
            edit 1
                set start-ip 192.168.10.100
                set end-ip 192.168.10.199
            next
        end
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert intent.domain == "system.example"
        assert intent.dhcp_servers[0].domain_name == "pool.example"
