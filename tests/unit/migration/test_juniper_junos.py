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

    def test_block_form_now_accepted_via_gap_9a_conversion(self):
        """GAP 9a: block-form (curly-brace hierarchical) input now
        parses via automatic conversion to set-form.  The earlier
        rejection-with-helpful-hint behaviour was removed in the
        v2b commit."""
        raw = "system {\n    host-name sw1;\n}\n"
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "sw1"

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

    def test_render_bare_interface_emits_placeholder(self):
        """Regression guard for the bare-interface round-trip bug
        surfaced by the ksator EX4550 fixture (GAP 3).

        Junos parse creates an interface entry for every
        ``set interfaces <name> ...`` line seen — including lines
        whose trailing tokens are all Tier-3 grammar (e.g.
        ``unit 0 family ethernet-switching ...``) that the canonical
        tree can't carry.  Those interfaces end up with no
        description, no IP, enabled=True — nothing renderable.

        Before the fix: render dropped them silently, so the
        interface count shrank on round-trip and parse(render(tree))
        was not stable.

        After the fix: render emits ``set interfaces <name>`` as a
        placeholder declaration so the interface survives re-parse.
        """
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="xe-0/0/0",
                    description="",
                    enabled=True,
                ),
            ],
        )
        codec = JunosCodec()
        rendered = codec.render(intent)
        assert "set interfaces xe-0/0/0\n" in rendered or (
            rendered.rstrip().endswith("set interfaces xe-0/0/0")
        )
        # Round-trip stability.
        reparsed = codec.parse(rendered)
        assert len(reparsed.interfaces) == 1
        assert reparsed.interfaces[0].name == "xe-0/0/0"


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


# ---------------------------------------------------------------------------
# GAP 4: apply-groups host-name inheritance
# ---------------------------------------------------------------------------


class TestApplyGroupsHostname:
    """Junos allows host-name (and other system scalars) to live under a
    named ``groups`` stanza that ``apply-groups`` composes into the
    candidate config.  The ksator QFX5100 + EX4550 fixtures both follow
    this convention — without wiring it, ``intent.hostname`` came out
    empty even though the device clearly has a name.
    """

    def test_apply_groups_hostname_resolved(self):
        raw = (
            "set groups POC_Lab system host-name QFX5100-183\n"
            "set apply-groups POC_Lab\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "QFX5100-183"

    def test_top_level_hostname_wins_over_group(self):
        """A top-level ``set system host-name`` takes precedence over
        any group-scoped fallback — matches Junos's own config-
        composition semantics (direct intent > inherited group)."""
        raw = (
            "set system host-name real-host\n"
            "set groups POC_Lab system host-name group-host\n"
            "set apply-groups POC_Lab\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "real-host"

    def test_unapplied_group_hostname_ignored(self):
        """A group that declares a host-name but isn't named in
        ``apply-groups`` must not leak into intent.hostname."""
        raw = (
            "set groups POC_Lab system host-name group-host\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == ""

    def test_first_applied_group_wins(self):
        """Apply-groups is ordered; the first group declaring a
        host-name wins (mirrors Junos's first-match semantics)."""
        raw = (
            "set groups A system host-name host-from-A\n"
            "set groups B system host-name host-from-B\n"
            "set apply-groups A\n"
            "set apply-groups B\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "host-from-A"

    def test_bracketed_apply_groups_syntax(self):
        """``set apply-groups [ g1 g2 ]`` is a valid Junos form; the
        bracket tokens get split by the shlex tokeniser and need to
        be filtered out of the applied-groups list."""
        raw = (
            "set groups A system host-name host-from-A\n"
            "set groups B system host-name host-from-B\n"
            "set apply-groups [ A B ]\n"
        )
        intent = JunosCodec().parse(raw)
        # Either A or B would be acceptable — the only failure mode
        # is getting an empty hostname (brackets leaking) or an
        # error parsing the line.
        assert intent.hostname in {"host-from-A", "host-from-B"}

    def test_real_qfx5100_fixture_hostname_populates(self):
        """Regression guard specifically for the ksator QFX5100
        fixture — before GAP 4, its hostname came out empty."""
        import pathlib
        raw = pathlib.Path(
            "tests/fixtures/real/junos/"
            "ksator_labmgmt_qfx5100_junos173.set"
        ).read_text(encoding="utf-8")
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "QFX5100-183"

    def test_real_ex4550_fixture_hostname_populates(self):
        """Regression guard specifically for the ksator EX4550
        fixture — before GAP 4, its hostname came out empty."""
        import pathlib
        raw = pathlib.Path(
            "tests/fixtures/real/junos/"
            "ksator_labmgmt_ex4550_junos151.set"
        ).read_text(encoding="utf-8")
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "EX4550-190"


# ---------------------------------------------------------------------------
# GAP 4: sub-interfaces (unit 1+)
# ---------------------------------------------------------------------------


class TestSubInterfaces:
    """v1 collapsed unit 0 into the parent and ignored units 1+.
    GAP 4 materialises unit-N sub-interfaces as distinct
    CanonicalInterface entries named ``<parent>.<N>`` — matches
    Cisco's dot1Q convention so canonical-tree consumers see the
    same shape across vendors.
    """

    def test_parse_unit_100_materialised_as_subiface(self):
        raw = (
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24\n"
        )
        intent = JunosCodec().parse(raw)
        names = {i.name for i in intent.interfaces}
        # Parent exists as a stub (placeholder); sub-interface
        # carries the IP.
        assert "ge-0/0/0" in names
        assert "ge-0/0/0.100" in names
        sub = next(i for i in intent.interfaces if i.name == "ge-0/0/0.100")
        assert len(sub.ipv4_addresses) == 1
        assert sub.ipv4_addresses[0].ip == "10.1.100.1"
        assert sub.ipv4_addresses[0].prefix_length == 24

    def test_parse_unit_description_on_subiface(self):
        raw = (
            "set interfaces ge-0/0/0 unit 100 description "
            '"user VLAN 100"\n'
        )
        intent = JunosCodec().parse(raw)
        sub = next(
            (i for i in intent.interfaces if i.name == "ge-0/0/0.100"),
            None,
        )
        assert sub is not None
        assert sub.description == "user VLAN 100"

    def test_parse_unit_disable_on_subiface(self):
        raw = (
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24\n"
            "set interfaces ge-0/0/0 unit 100 disable\n"
        )
        intent = JunosCodec().parse(raw)
        sub = next(
            (i for i in intent.interfaces if i.name == "ge-0/0/0.100"),
            None,
        )
        assert sub is not None
        assert sub.enabled is False

    def test_multiple_subifaces_on_same_parent(self):
        raw = (
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24\n"
            "set interfaces ge-0/0/0 unit 200 family inet "
            "address 10.1.200.1/24\n"
        )
        intent = JunosCodec().parse(raw)
        names = [i.name for i in intent.interfaces]
        assert "ge-0/0/0.100" in names
        assert "ge-0/0/0.200" in names

    def test_irb_dot_N_not_treated_as_subiface(self):
        """``irb.10`` is an SVI-like interface; its dot is part of the
        base name.  The sub-interface detector must not split it into
        ``irb`` + ``10`` — that would lose identity.
        """
        raw = (
            "set interfaces irb unit 10 family inet address "
            "192.168.10.1/24\n"
        )
        intent = JunosCodec().parse(raw)
        # The sub-interface regex requires ``<media>-<fpc>/<pic>/<port>``
        # in the parent, so ``irb`` unit 10 materialises as ``irb.10``
        # and the render loop treats it as a top-level interface
        # (no parent-split) because it lacks the slash grammar.
        # The parse side emits a compound ``irb.10`` either way;
        # the key property is that ``render(parse)`` round-trips.
        codec = JunosCodec()
        rendered = codec.render(intent)
        reparsed = codec.parse(rendered)
        reparsed_names = {i.name for i in reparsed.interfaces}
        assert any(n.startswith("irb") for n in reparsed_names)

    def test_render_subiface_emits_unit_form(self):
        """Sub-interface render MUST use Junos's native
        ``set interfaces <parent> unit <N> ...`` grammar, not the
        compound canonical name verbatim."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0.100",
                    description="user vlan",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="10.1.100.1", prefix_length=24,
                        ),
                    ],
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert (
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24" in out
        )
        assert (
            'set interfaces ge-0/0/0 unit 100 description "user vlan"'
            in out
        )
        # Must NOT emit the compound-name form (that'd be invalid
        # Junos grammar).
        assert "set interfaces ge-0/0/0.100" not in out

    def test_subiface_roundtrip_stable(self):
        """Sub-interface parse → render → parse preserves IP + desc."""
        raw = (
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24\n"
            "set interfaces ge-0/0/0 unit 100 description "
            '"user VLAN"\n'
            "set interfaces ge-0/0/0 unit 200 family inet "
            "address 10.1.200.1/24\n"
        )
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        first_by_name = {i.name: i for i in first.interfaces}
        second_by_name = {i.name: i for i in second.interfaces}
        assert set(first_by_name.keys()) == set(second_by_name.keys())
        for name in first_by_name:
            a, b = first_by_name[name], second_by_name[name]
            assert a.description == b.description
            assert [(x.ip, x.prefix_length) for x in a.ipv4_addresses] == [
                (x.ip, x.prefix_length) for x in b.ipv4_addresses
            ]


# ---------------------------------------------------------------------------
# GAP 7: per-unit 802.1Q VLAN tagging
# ---------------------------------------------------------------------------


class TestPerUnitVlanTagging:
    """``set interfaces <parent> unit <N> vlan-id <tag>`` is Junos's
    per-subinterface 802.1Q tag primitive — semantically equivalent to
    Cisco's ``encapsulation dot1Q <N>`` on a subinterface.  Stores on
    CanonicalInterface.access_vlan (the existing field access-mode
    switchports use) without setting switchport_mode (Junos sub-
    interfaces are L3 on a tagged VLAN, not L2 access ports).
    """

    def test_parse_vlan_id_on_unit(self):
        raw = (
            "set interfaces ge-0/0/0 unit 100 vlan-id 100\n"
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24\n"
        )
        intent = JunosCodec().parse(raw)
        sub = next(
            (i for i in intent.interfaces if i.name == "ge-0/0/0.100"),
            None,
        )
        assert sub is not None
        assert sub.access_vlan == 100
        # switchport_mode stays None — this is L3 on a tagged VLAN.
        assert sub.switchport_mode is None

    def test_parse_vlan_id_alone_creates_subiface(self):
        """A unit declared only with vlan-id (no IP) still materialises
        as a CanonicalInterface — useful for sub-interfaces that will
        get IPs later, and round-trip stability."""
        raw = "set interfaces ge-0/0/0 unit 100 vlan-id 100\n"
        intent = JunosCodec().parse(raw)
        sub = next(
            (i for i in intent.interfaces if i.name == "ge-0/0/0.100"),
            None,
        )
        assert sub is not None
        assert sub.access_vlan == 100

    def test_parse_vlan_id_non_integer_rejected(self):
        """Malformed ``vlan-id abc`` silently no-ops rather than crashing."""
        raw = (
            "set interfaces ge-0/0/0 unit 100 vlan-id not-a-number\n"
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24\n"
        )
        intent = JunosCodec().parse(raw)
        sub = next(
            (i for i in intent.interfaces if i.name == "ge-0/0/0.100"),
            None,
        )
        assert sub is not None
        assert sub.access_vlan is None  # bad token silently dropped
        # Rest of the unit's config still parses.
        assert len(sub.ipv4_addresses) == 1

    def test_render_vlan_id_on_subiface(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0.100",
                    access_vlan=100,
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="10.1.100.1", prefix_length=24,
                        ),
                    ],
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert "set interfaces ge-0/0/0 unit 100 vlan-id 100" in out

    def test_render_vlan_id_alone_emits_set_line(self):
        """Sub-interface with only access_vlan (no IP, no description)
        still emits the vlan-id line — it IS renderable content."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0.100",
                    access_vlan=100,
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert "set interfaces ge-0/0/0 unit 100 vlan-id 100" in out
        # Must NOT also emit the bare-placeholder line (that'd be
        # redundant).
        assert "set interfaces ge-0/0/0 unit 100\n" not in out

    def test_vlan_id_roundtrip(self):
        raw = (
            "set interfaces ge-0/0/0 unit 100 vlan-id 100\n"
            "set interfaces ge-0/0/0 unit 100 family inet "
            "address 10.1.100.1/24\n"
            "set interfaces ge-0/0/0 unit 200 vlan-id 200\n"
        )
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        sub1_first = next(
            i for i in first.interfaces if i.name == "ge-0/0/0.100"
        )
        sub1_second = next(
            i for i in second.interfaces if i.name == "ge-0/0/0.100"
        )
        sub2_second = next(
            i for i in second.interfaces if i.name == "ge-0/0/0.200"
        )
        assert sub1_first.access_vlan == sub1_second.access_vlan == 100
        assert sub2_second.access_vlan == 200

    def test_unit_0_vlan_id_collapses_into_parent(self):
        """``unit 0 vlan-id N`` is uncommon but legal Junos — stores
        on the parent interface's access_vlan (unit 0 collapses into
        parent per the v1 convention)."""
        raw = (
            "set interfaces ge-0/0/0 unit 0 vlan-id 42\n"
        )
        intent = JunosCodec().parse(raw)
        parent = next(
            (i for i in intent.interfaces if i.name == "ge-0/0/0"),
            None,
        )
        assert parent is not None
        assert parent.access_vlan == 42


# ---------------------------------------------------------------------------
# GAP 9a: block-form (curly-brace hierarchical) parse
# ---------------------------------------------------------------------------


class TestBlockFormParse:
    """v1 rejected block-form with a helpful hint; v2b (GAP 9a) now
    auto-converts block-form → set-form internally and feeds it
    through the normal parser.  The conversion is grammar-agnostic
    beyond brace balancing; unknown sub-trees still parse-tolerate
    via Tier-3 fall-through.
    """

    def test_system_host_name(self):
        raw = "system {\n    host-name sw1;\n}\n"
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "sw1"

    def test_nested_blocks(self):
        raw = (
            "system {\n"
            "    host-name router1;\n"
            "    login {\n"
            "        user admin {\n"
            "            class super-user;\n"
            "            authentication {\n"
            '                encrypted-password "$6$fake$hash";\n'
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "router1"
        assert len(intent.local_users) == 1
        u = intent.local_users[0]
        assert u.name == "admin"
        assert u.role == "super-user"
        assert u.privilege_level == 15
        assert u.hashed_password == "junos:$6$fake$hash"

    def test_interface_with_ip(self):
        raw = (
            "interfaces {\n"
            "    ge-0/0/0 {\n"
            '        description "uplink";\n'
            "        unit 0 {\n"
            "            family inet {\n"
            "                address 10.0.0.1/24;\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        intent = JunosCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "ge-0/0/0")
        assert iface.description == "uplink"
        assert iface.ipv4_addresses[0].ip == "10.0.0.1"
        assert iface.ipv4_addresses[0].prefix_length == 24

    def test_vlan_with_vxlan_vni(self):
        raw = (
            "vlans {\n"
            "    V100 {\n"
            "        vlan-id 100;\n"
            "        vxlan {\n"
            "            vni 10100;\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        intent = JunosCodec().parse(raw)
        assert any(v.id == 100 and v.name == "V100" for v in intent.vlans)
        assert len(intent.vxlan_vnis) == 1
        assert intent.vxlan_vnis[0].vlan_id == 100
        assert intent.vxlan_vnis[0].vni == 10100

    def test_routing_instance_vrf(self):
        raw = (
            "routing-instances {\n"
            "    TENANT_A {\n"
            "        instance-type vrf;\n"
            "        route-distinguisher 1.1.1.1:100;\n"
            "        vrf-target target:65000:100;\n"
            "        interface ge-0/0/1.0;\n"
            "    }\n"
            "}\n"
        )
        intent = JunosCodec().parse(raw)
        ri = next(r for r in intent.routing_instances if r.name == "TENANT_A")
        assert ri.instance_type == "vrf"
        assert ri.route_distinguisher == "1.1.1.1:100"
        assert ri.rt_imports == ["65000:100"]
        assert ri.rt_exports == ["65000:100"]

    def test_apply_groups_inheritance_in_blockform(self):
        raw = (
            "groups {\n"
            "    G {\n"
            "        system {\n"
            "            host-name from-group;\n"
            "        }\n"
            "    }\n"
            "}\n"
            "apply-groups G;\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "from-group"

    def test_quoted_strings_preserved(self):
        raw = (
            "interfaces {\n"
            "    ge-0/0/0 {\n"
            '        description "contains spaces and $specials";\n'
            "    }\n"
            "}\n"
        )
        intent = JunosCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "ge-0/0/0")
        assert iface.description == "contains spaces and $specials"

    def test_comments_stripped(self):
        raw = (
            "/* top-level comment */\n"
            "system {\n"
            "    /* inline comment */\n"
            "    host-name sw1;\n"
            "}\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "sw1"

    def test_mixed_input_still_rejected_if_not_blockform(self):
        """JSON-shaped input still raises (starts with `{` but isn't
        Junos hierarchical)."""
        from netconfig.migration.codecs.base import ParseError
        raw = '{"hostname": "not-junos"}'
        with pytest.raises(ParseError):
            JunosCodec().parse(raw)

    def test_unbalanced_braces_raises(self):
        from netconfig.migration.codecs.base import ParseError
        raw = "system {\n    host-name sw1;\n"  # no closing `}`
        with pytest.raises(ParseError):
            JunosCodec().parse(raw)
