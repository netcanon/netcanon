"""
Unit tests for the Juniper Junos codec.

v1 — set-form parse-only (shipped Phase 13).
v2a — flat set-form render added (GAP 2 commit); apply-groups
      optimisation deferred to v2b.

Real-capture parse is exercised separately by
``test_real_captures.py`` against
``tests/fixtures/real/junos/buraglio_netlab_junos184.set``.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
    CanonicalLocalUser,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
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

    def test_render_rejects_non_canonical_tree(self):
        """Render is strict: anything other than a CanonicalIntent is a
        programming error, fail loud."""
        with pytest.raises(TypeError, match="CanonicalIntent"):
            JunosCodec().render({"hostname": "oops"})


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


# ---------------------------------------------------------------------------
# Render (v2a — flat set-form, no apply-groups)
# ---------------------------------------------------------------------------


class TestRenderBasic:
    def test_render_empty_tree(self):
        """Rendering an empty intent yields an empty string (no noise
        lines).  Operator pasting an empty output gets silent no-op."""
        out = JunosCodec().render(CanonicalIntent())
        assert out == ""

    def test_render_hostname_only(self):
        intent = CanonicalIntent(hostname="sw1")
        out = JunosCodec().render(intent)
        assert out == "set system host-name sw1\n"

    def test_render_fqdn_hostname(self):
        intent = CanonicalIntent(hostname="sw-edge-01.example.com")
        out = JunosCodec().render(intent)
        assert "set system host-name sw-edge-01.example.com" in out

    def test_render_deterministic(self):
        """Repeated renders of the same tree must produce identical
        output — load-bearing for diff-based deploy + snapshot compare."""
        intent = CanonicalIntent(
            hostname="deterministic-host",
            vlans=[
                CanonicalVlan(id=10, name="USERS"),
                CanonicalVlan(id=20, name="VOICE"),
            ],
        )
        codec = JunosCodec()
        first = codec.render(intent)
        second = codec.render(intent)
        assert first == second


class TestRenderInterfaces:
    def test_render_simple_interface(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0",
                    description="uplink to core",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.0.1", prefix_length=31),
                    ],
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert 'set interfaces ge-0/0/0 description "uplink to core"' in out
        assert (
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31"
            in out
        )

    def test_render_disabled_interface(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/5", enabled=False),
            ],
        )
        out = JunosCodec().render(intent)
        assert "set interfaces ge-0/0/5 disable" in out

    def test_render_loopback_with_ip(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="lo0",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="172.16.0.1", prefix_length=32),
                    ],
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert (
            "set interfaces lo0 unit 0 family inet address 172.16.0.1/32"
            in out
        )

    def test_render_description_quoting(self):
        """Descriptions with special chars get escaped in the double-
        quoted wrapper — operator should paste the render output back
        and have it parse identically."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/1",
                    description='uplink with "quoted" words',
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert 'description "uplink with \\"quoted\\" words"' in out

    def test_render_multiple_ipv4_addresses(self):
        """Junos allows multiple `family inet address` entries per unit;
        render each on its own line preserving order."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
                        CanonicalIPv4Address(ip="10.0.1.1", prefix_length=24),
                    ],
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert "10.0.0.1/24" in out
        assert "10.0.1.1/24" in out
        assert out.index("10.0.0.1/24") < out.index("10.0.1.1/24")


class TestRenderVlans:
    def test_render_named_vlan(self):
        intent = CanonicalIntent(vlans=[CanonicalVlan(id=10, name="USERS")])
        out = JunosCodec().render(intent)
        assert "set vlans USERS vlan-id 10" in out

    def test_render_unnamed_vlan_uses_synthetic_key(self):
        """VLANs without a name fall back to ``VLAN-<id>`` so Junos
        grammar stays valid — ``set vlans <key> vlan-id N`` requires a
        non-empty key."""
        intent = CanonicalIntent(vlans=[CanonicalVlan(id=42)])
        out = JunosCodec().render(intent)
        assert "set vlans VLAN-42 vlan-id 42" in out

    def test_render_vlan_name_with_space_quoted(self):
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=100, name="GUEST WIFI")],
        )
        out = JunosCodec().render(intent)
        assert 'set vlans "GUEST WIFI" vlan-id 100' in out


class TestRenderUsers:
    def test_render_super_user_from_privilege(self):
        """Privilege 15 with no explicit role → super-user on render."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="admin", privilege_level=15),
            ],
        )
        out = JunosCodec().render(intent)
        assert "set system login user admin class super-user" in out

    def test_render_read_only_from_privilege(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(name="auditor", privilege_level=1),
            ],
        )
        out = JunosCodec().render(intent)
        assert "set system login user auditor class read-only" in out

    def test_render_explicit_role_wins_over_privilege(self):
        """A role like ``super-user`` on the canonical user takes
        precedence over the privilege-to-role fallback."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    role="super-user",
                    privilege_level=1,  # nonsense, but role must win
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert "class super-user" in out

    def test_render_encrypted_password_strips_vendor_tag(self):
        """Hashes stored under ``junos:<hash>`` get the prefix stripped
        on render so parse(render(tree)) is a true round-trip."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    privilege_level=15,
                    hashed_password="junos:$6$abcd$fake",
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert 'authentication encrypted-password "$6$abcd$fake"' in out
        assert "junos:" not in out  # prefix must not leak

    def test_render_hash_from_other_vendor_preserved_verbatim(self):
        """If a hash lacks the junos: prefix (came from another
        codec's canonical layer), emit it verbatim inside the
        double-quoted wrapper — it's still a valid encrypted-password
        value."""
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    privilege_level=15,
                    hashed_password="$9$foreign$hash",
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert 'authentication encrypted-password "$9$foreign$hash"' in out


class TestRenderRouting:
    def test_render_static_route(self):
        intent = CanonicalIntent(
            static_routes=[
                CanonicalStaticRoute(
                    destination="0.0.0.0/0",
                    gateway="10.0.0.2",
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert (
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2"
            in out
        )

    def test_render_connected_route_skipped(self):
        """Junos static routes require a next-hop; connected/blackhole
        routes (empty gateway) have no representation in the flat
        set-form grammar we emit, so skip them rather than produce
        invalid input."""
        intent = CanonicalIntent(
            static_routes=[
                CanonicalStaticRoute(destination="10.1.0.0/24", gateway=""),
            ],
        )
        out = JunosCodec().render(intent)
        assert "10.1.0.0/24" not in out


class TestRenderSnmp:
    def test_render_community_read_only(self):
        intent = CanonicalIntent(snmp=CanonicalSNMP(community="public"))
        out = JunosCodec().render(intent)
        assert (
            "set snmp community public authorization read-only" in out
        )

    def test_render_location_contact_quoted(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                location="Rack 4 DC1",
                contact="neteng@example.com",
            ),
        )
        out = JunosCodec().render(intent)
        assert 'set snmp location "Rack 4 DC1"' in out
        assert 'set snmp contact "neteng@example.com"' in out

    def test_render_trap_hosts(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                trap_hosts=["10.1.1.100", "10.1.1.101"],
            ),
        )
        out = JunosCodec().render(intent)
        assert "set snmp trap-group targets targets 10.1.1.100" in out
        assert "set snmp trap-group targets targets 10.1.1.101" in out


class TestRenderRoundTrip:
    """parse(render(tree)) == tree for every feature v2a emits."""

    def _assert_roundtrip(self, intent: CanonicalIntent) -> None:
        codec = JunosCodec()
        rendered = codec.render(intent)
        reparsed = codec.parse(rendered) if rendered.strip() else CanonicalIntent()
        # Normalise source-vendor metadata (added by parse, not by
        # caller-supplied intent).
        reparsed.source_vendor = intent.source_vendor
        reparsed.source_format = intent.source_format
        assert reparsed.hostname == intent.hostname
        assert len(reparsed.interfaces) == len(intent.interfaces)
        assert len(reparsed.vlans) == len(intent.vlans)
        assert len(reparsed.static_routes) == len(intent.static_routes)
        assert len(reparsed.local_users) == len(intent.local_users)

    def test_roundtrip_hostname_only(self):
        self._assert_roundtrip(CanonicalIntent(hostname="sw1"))

    def test_roundtrip_sample_input(self):
        """The codec's sample_input round-trips via parse → render →
        parse without data loss on any field v2a emits."""
        codec = JunosCodec()
        first = codec.parse(codec.sample_input)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert second.hostname == first.hostname
        assert len(second.interfaces) == len(first.interfaces)
        assert len(second.vlans) == len(first.vlans)
        assert len(second.static_routes) == len(first.static_routes)
        assert len(second.local_users) == len(first.local_users)
        # SNMP field-by-field.
        assert (second.snmp is None) == (first.snmp is None)
        if first.snmp is not None:
            assert second.snmp.community == first.snmp.community
            assert second.snmp.location == first.snmp.location

    def test_roundtrip_user_with_hash(self):
        intent = CanonicalIntent(
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    privilege_level=15,
                    role="super-user",
                    hashed_password="junos:$6$abcd$fake",
                ),
            ],
        )
        codec = JunosCodec()
        rendered = codec.render(intent)
        reparsed = codec.parse(rendered)
        assert len(reparsed.local_users) == 1
        user = reparsed.local_users[0]
        assert user.name == "admin"
        assert user.role == "super-user"
        assert user.privilege_level == 15
        assert user.hashed_password == "junos:$6$abcd$fake"

    def test_roundtrip_interface_with_special_chars_in_description(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/1",
                    description="long haul link $to $us",
                ),
            ],
        )
        codec = JunosCodec()
        rendered = codec.render(intent)
        reparsed = codec.parse(rendered)
        assert len(reparsed.interfaces) == 1
        assert reparsed.interfaces[0].description == "long haul link $to $us"


class TestRenderCodecMetadata:
    def test_direction_promoted_to_bidirectional(self):
        assert JunosCodec.direction == "bidirectional"

    def test_render_idempotent_via_double_parse(self):
        """Trees produced by re-parsing rendered output render
        identically — proves render is deterministic on the parsed
        form's ordering."""
        codec = JunosCodec()
        first = codec.parse(codec.sample_input)
        rendered_a = codec.render(first)
        second = codec.parse(rendered_a)
        rendered_b = codec.render(second)
        assert rendered_a == rendered_b
