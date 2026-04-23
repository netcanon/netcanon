"""
Unit tests for the Juniper Junos codec (v1 — set-form parse-only).

Real-capture parse is exercised separately by
``test_real_captures.py`` against
``tests/fixtures/real/junos/buraglio_netlab_junos184.set``.
"""

from __future__ import annotations

import pytest

from netconfig.migration.codecs.base import ParseError
from netconfig.migration.codecs.juniper_junos import JunosCodec
from netconfig.migration.codecs.juniper_junos.port_names import (
    classify_port_name,
    format_port_identity,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parse — top-level scalars
# ---------------------------------------------------------------------------


class TestParseScalars:
    def test_hostname(self):
        intent = JunosCodec().parse("set system host-name sw-edge-01\n")
        assert intent.hostname == "sw-edge-01"

    def test_hostname_with_dots(self):
        """Real-world: FQDN hostnames are common on service-provider
        edge devices."""
        intent = JunosCodec().parse(
            "set system host-name sw-edge-01.example.com\n"
        )
        assert intent.hostname == "sw-edge-01.example.com"

    def test_set_version_not_stored_as_hostname(self):
        """``set version 18.4R1`` must not leak into hostname."""
        raw = (
            "set version 18.4R1\n"
            "set system host-name real-host\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "real-host"


# ---------------------------------------------------------------------------
# Parse — interfaces
# ---------------------------------------------------------------------------


class TestParseInterfaces:
    def test_interface_with_ipv4_on_unit_0(self):
        raw = (
            "set system host-name sw1\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31\n"
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.interfaces) == 1
        iface = intent.interfaces[0]
        assert iface.name == "ge-0/0/0"
        assert iface.ipv4_addresses[0].ip == "10.0.0.1"
        assert iface.ipv4_addresses[0].prefix_length == 31

    def test_interface_description_top_level(self):
        """Junos allows description at interface OR unit level.  v1
        captures both into ``iface.description``."""
        raw = (
            "set system host-name sw1\n"
            'set interfaces ge-0/0/0 description "uplink to core"\n'
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31\n"
        )
        intent = JunosCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.description == "uplink to core"

    def test_interface_description_on_unit(self):
        """``unit 0 description`` also captured as the iface description."""
        raw = (
            "set system host-name sw1\n"
            'set interfaces ge-0/0/0 unit 0 description "Unit desc"\n'
        )
        intent = JunosCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.description == "Unit desc"

    def test_interface_disable(self):
        raw = (
            "set system host-name sw1\n"
            "set interfaces ge-0/0/5 disable\n"
        )
        intent = JunosCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.enabled is False

    def test_multiple_interfaces_different_media(self):
        raw = (
            "set system host-name sw1\n"
            "set interfaces em0 unit 0 family inet address 172.22.0.253/24\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31\n"
            "set interfaces xe-0/0/48 unit 0 family inet address 10.1.1.1/30\n"
            "set interfaces lo0 unit 0 family inet address 172.16.0.1/32\n"
        )
        intent = JunosCodec().parse(raw)
        names = [i.name for i in intent.interfaces]
        assert names == ["em0", "ge-0/0/0", "lo0", "xe-0/0/48"]

    def test_unit_nonzero_not_materialised_in_v1(self):
        """Sub-units 1+ on non-physical interfaces not modelled in v1."""
        raw = (
            "set system host-name sw1\n"
            "set interfaces ge-0/0/0 unit 10 family inet address 10.1.1.1/24\n"
        )
        intent = JunosCodec().parse(raw)
        # Interface exists but no IPv4 (unit 10 ignored).
        ifaces = [i for i in intent.interfaces if i.name == "ge-0/0/0"]
        assert len(ifaces) == 1
        assert len(ifaces[0].ipv4_addresses) == 0


# ---------------------------------------------------------------------------
# Parse — VLANs
# ---------------------------------------------------------------------------


class TestParseVlans:
    def test_vlan_with_id(self):
        raw = (
            "set system host-name sw1\n"
            "set vlans USERS vlan-id 10\n"
            "set vlans VOICE vlan-id 20\n"
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.vlans) == 2
        vlan_map = {v.id: v.name for v in intent.vlans}
        assert vlan_map == {10: "USERS", 20: "VOICE"}


# ---------------------------------------------------------------------------
# Parse — local users
# ---------------------------------------------------------------------------


class TestParseUsers:
    def test_user_with_class_and_password(self):
        raw = (
            "set system host-name sw1\n"
            "set system login user netadmin class super-user\n"
            "set system login user netadmin authentication "
            'encrypted-password "$6$abcdef$hash"\n'
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.local_users) == 1
        u = intent.local_users[0]
        assert u.name == "netadmin"
        assert u.role == "super-user"
        assert u.privilege_level == 15  # super-user → 15
        assert u.hashed_password == "junos:$6$abcdef$hash"

    def test_user_read_only_class_gets_privilege_1(self):
        raw = (
            "set system host-name sw1\n"
            "set system login user operator class read-only\n"
        )
        intent = JunosCodec().parse(raw)
        u = intent.local_users[0]
        assert u.role == "read-only"
        assert u.privilege_level == 1

    def test_root_authentication_ignored(self):
        """``set system root-authentication encrypted-password`` is
        NOT a user declaration — it configures the root account's
        auth.  v1 ignores it (Tier-3)."""
        raw = (
            "set system host-name sw1\n"
            "set system root-authentication encrypted-password "
            '"$6$abcd$foo"\n'
        )
        intent = JunosCodec().parse(raw)
        assert intent.local_users == []


# ---------------------------------------------------------------------------
# Parse — static routes
# ---------------------------------------------------------------------------


class TestParseStaticRoutes:
    def test_default_route(self):
        raw = (
            "set system host-name sw1\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2\n"
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.static_routes) == 1
        r = intent.static_routes[0]
        assert r.destination == "0.0.0.0/0"
        assert r.gateway == "10.0.0.2"

    def test_multiple_routes(self):
        raw = (
            "set system host-name sw1\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2\n"
            "set routing-options static route 192.168.0.0/16 next-hop 10.0.0.3\n"
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.static_routes) == 2


# ---------------------------------------------------------------------------
# Parse — SNMP
# ---------------------------------------------------------------------------


class TestParseSnmp:
    def test_community_read_only(self):
        raw = (
            "set system host-name sw1\n"
            "set snmp community public authorization read-only\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.snmp is not None
        assert intent.snmp.community == "public"

    def test_location_and_contact(self):
        raw = (
            "set system host-name sw1\n"
            "set snmp community public authorization read-only\n"
            'set snmp location "Rack 4 DC1"\n'
            "set snmp contact netops@example.com\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.snmp.location == "Rack 4 DC1"
        assert intent.snmp.contact == "netops@example.com"


# ---------------------------------------------------------------------------
# Parse — validation
# ---------------------------------------------------------------------------


class TestParseValidation:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError, match="empty"):
            JunosCodec().parse("")

    def test_xml_input_rejected(self):
        with pytest.raises(ParseError, match="XML"):
            JunosCodec().parse("<config/>")

    def test_block_form_rejected_with_helpful_hint(self):
        """v1 doesn't parse block-form.  Rejection message must tell
        the operator to run `| display set` on their device."""
        raw = "{\n    system {\n        host-name sw1;\n    }\n}\n"
        with pytest.raises(ParseError, match="display set"):
            JunosCodec().parse(raw)

    def test_render_not_implemented(self):
        with pytest.raises(NotImplementedError, match="parse-only"):
            JunosCodec().render(None)


# ---------------------------------------------------------------------------
# Parse tolerance — unknown stanzas silently ignored
# ---------------------------------------------------------------------------


class TestParseTolerance:
    def test_bgp_stanza_ignored(self):
        raw = (
            "set system host-name sw1\n"
            "set protocols bgp group bgp-te type internal\n"
            "set protocols bgp group bgp-te local-address 10.0.0.1\n"
            "set protocols bgp group bgp-te neighbor 10.0.0.2\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "sw1"
        # BGP doesn't populate any canonical fields in v1.

    def test_isis_stanza_ignored(self):
        raw = (
            "set system host-name sw1\n"
            "set protocols isis interface ge-0/0/0.0 level 2 metric 100\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "sw1"

    def test_firewall_filter_ignored(self):
        raw = (
            "set system host-name sw1\n"
            "set firewall family inet filter cull term c1 "
            "from source-port 179\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "sw1"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_set_version_banner_signal(self):
        raw = "set version 23.2R1.14\nset system host-name sw1\n"
        result = JunosCodec.probe(raw)
        assert result is not None
        score, reason = result
        assert score >= 85
        assert "version" in reason.lower()

    def test_multiple_markers_signal(self):
        raw = (
            "set system host-name sw1\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2\n"
            "set vlans USERS vlan-id 10\n"
        )
        result = JunosCodec.probe(raw)
        assert result is not None
        score, _ = result
        assert score >= 85  # 4 markers → strong signal

    def test_non_junos_returns_none(self):
        """Cisco IOS-like text must NOT probe as Junos."""
        raw = (
            "hostname router1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
        )
        result = JunosCodec.probe(raw)
        # No set-form lines — must not claim a match.
        assert result is None or result[0] < 60

    def test_block_form_returns_none(self):
        """Block-form curly-brace input isn't parseable in v1; probe
        must not claim it."""
        assert JunosCodec.probe("{ system { host-name sw1; } }") is None


# ---------------------------------------------------------------------------
# port_names identity bridge
# ---------------------------------------------------------------------------


class TestPortNames:
    def test_classify_ge_3part(self):
        ident = classify_port_name("ge-0/0/24")
        assert ident.kind == "physical"
        assert ident.stack == 0
        assert ident.module == 0
        assert ident.port == 24
        assert ident.name_speed_hint == "gig"

    def test_classify_xe_speed_hint(self):
        ident = classify_port_name("xe-1/0/47")
        assert ident.kind == "physical"
        assert ident.name_speed_hint == "10gig"

    def test_classify_et_speed_hint(self):
        ident = classify_port_name("et-0/0/0")
        assert ident.name_speed_hint == "100gig"

    def test_classify_em0_mgmt(self):
        ident = classify_port_name("em0")
        assert ident.kind == "mgmt"
        assert ident.port == 0

    def test_classify_lo0_loopback(self):
        ident = classify_port_name("lo0")
        assert ident.kind == "loopback"
        assert ident.index == 0

    def test_classify_ae0_lag(self):
        ident = classify_port_name("ae0")
        assert ident.kind == "lag"
        assert ident.index == 0

    def test_classify_irb_svi(self):
        ident = classify_port_name("irb.10")
        assert ident.kind == "svi"
        assert ident.index == 10

    def test_classify_unknown_returns_unknown(self):
        ident = classify_port_name("SomeWeirdPort")
        assert ident.kind == "unknown"

    def test_format_ge_roundtrip(self):
        ident = classify_port_name("ge-0/0/24")
        assert format_port_identity(ident) == "ge-0/0/24"

    def test_format_xe_roundtrip(self):
        ident = classify_port_name("xe-1/0/47")
        assert format_port_identity(ident) == "xe-1/0/47"

    def test_format_cross_vendor_cisco_to_junos(self):
        """Cisco GigabitEthernet1/0/24 (stack=1, module=0, port=24)
        → Junos ge-1/0/24."""
        from netconfig.migration.codecs.cisco_iosxe_cli.port_names import (
            classify_port_name as cisco_classify,
        )
        cisco_ident = cisco_classify("GigabitEthernet1/0/24")
        junos_name = format_port_identity(cisco_ident)
        assert junos_name == "ge-1/0/24"

    def test_format_cross_vendor_tengig(self):
        """Cisco TenGigabitEthernet1/0/48 → Junos xe-1/0/48
        (speed hint drives media prefix choice)."""
        from netconfig.migration.codecs.cisco_iosxe_cli.port_names import (
            classify_port_name as cisco_classify,
        )
        cisco_ident = cisco_classify("TenGigabitEthernet1/0/48")
        junos_name = format_port_identity(cisco_ident)
        assert junos_name == "xe-1/0/48"
