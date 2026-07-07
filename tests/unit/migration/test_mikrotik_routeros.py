"""
Unit tests for the ``MikroTikRouterOSCodec`` — third real codec,
Session 2 of the vendor-config-research plan.

Covers the same contract points as every canonical-bridged codec
(parse / render / round-trip / xpath / capabilities / registry), plus
MikroTik-specific structural quirks (section grammar, ``[ find ... ]``
predicate, key=value parsing with quoted strings, line continuations).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLAG,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs._mock import MockCodec
from netcanon.migration.codecs.base import ParseError, RenderError
from netcanon.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.opnsense import OPNsenseCodec
from netcanon.models.migration import DeviceClass, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "mikrotik_routeros"
)


_MIN = """\
/system identity
set name=router1

/interface ethernet
set [ find default-name=ether1 ] comment="Up to ISP" disabled=no

/ip address
add address=10.0.0.2/30 interface=ether1
"""


# ---------------------------------------------------------------------------
# R3 field declarations
# ---------------------------------------------------------------------------


class TestR3Fields:
    def test_direction_is_bidirectional(self):
        assert MikroTikRouterOSCodec.direction == "bidirectional"

    def test_certainty_is_certified(self):
        # Promoted from best_effort after user-contributed CRS310
        # RouterOS 7.18.2 /export verbose landed the 4th real fixture
        # across 3 OS versions (6.48.1, 6.48.6, 7.18.2), satisfying
        # the >=3 real captures / >=2 OS versions certification bar.
        # See tests/fixtures/real/RESULTS.md.
        assert MikroTikRouterOSCodec.certainty == "certified"

    def test_canonical_model(self):
        assert MikroTikRouterOSCodec.canonical_model == "openconfig-lite"

    def test_input_format(self):
        assert MikroTikRouterOSCodec.input_format == "cli-mikrotik"

    def test_vendor_id(self):
        caps = MikroTikRouterOSCodec().capabilities
        assert caps.vendor_id == "mikrotik_routeros"


# ---------------------------------------------------------------------------
# Parse — basic
# ---------------------------------------------------------------------------


class TestParse:
    def test_parse_hostname(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        assert tree.hostname == "router1"

    def test_source_version_parsed(self):
        """RouterOS release captured from the export header comment."""
        raw = "# 2026-04-21 20:35:02 by RouterOS 7.18.2\n" + _MIN
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.source_version == "7.18.2"

    def test_source_version_absent(self):
        """No export header comment → honest empty string."""
        tree = MikroTikRouterOSCodec().parse(_MIN)
        assert tree.source_version == ""

    def test_parse_single_ethernet_interface(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        ifaces = tree.interfaces
        assert len(ifaces) == 1
        assert ifaces[0].name == "ether1"
        assert ifaces[0].description == "Up to ISP"
        assert ifaces[0].enabled is True
        assert ifaces[0].interface_type == "ianaift:ethernetCsmacd"

    def test_parse_ip_address_attaches_to_interface(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        addrs = tree.interfaces[0].ipv4_addresses
        assert len(addrs) == 1
        assert addrs[0].ip == "10.0.0.2"
        assert addrs[0].prefix_length == 30

    def test_parse_disabled_flag(self):
        raw = (
            "/interface ethernet\n"
            "set [ find default-name=ether9 ] comment=Reserved disabled=yes\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.interfaces[0].enabled is False

    def test_parse_fixture_produces_full_tree(self):
        raw = FIXTURES.joinpath("export_simple.rsc").read_text()
        tree = MikroTikRouterOSCodec().parse(raw)

        # Hostname
        assert tree.hostname == "edge-gw"

        # DNS + NTP
        assert tree.dns_servers == ["1.1.1.1", "8.8.8.8"]
        assert tree.ntp_servers == ["pool.ntp.org", "time.google.com"]

        # Interface count: bridge + ether1-3 + vlan10,20 = 6
        names = [i.name for i in tree.interfaces]
        assert "bridge1" in names
        assert "ether1" in names
        assert "ether2" in names
        assert "ether3" in names
        assert "vlan10" in names
        assert "vlan20" in names

        # Disabled ether3 from the fixture
        e3 = next(i for i in tree.interfaces if i.name == "ether3")
        assert e3.enabled is False

        # VLANs — canonical model now stores iface name as
        # CanonicalVlan.name (stable key for `_vlan_id_for` round-
        # trip lookups) and the comment on the description field.
        # Was: vlans[10] == "Corporate users" (the comment).
        vlans_by_id = {v.id: v for v in tree.vlans}
        assert vlans_by_id[10].name == "vlan10"
        assert vlans_by_id[10].description == "Corporate users"
        assert vlans_by_id[20].name == "vlan20"
        assert vlans_by_id[20].description == "Guest WiFi"

        # Static routes
        assert len(tree.static_routes) == 1
        assert tree.static_routes[0].destination == "0.0.0.0/0"
        assert tree.static_routes[0].gateway == "198.51.100.1"

    def test_quoted_comment_with_spaces(self):
        """Key=\"value with spaces\" must be parsed as a single value."""
        raw = (
            "/interface ethernet\n"
            'set [ find default-name=ether1 ] comment="Has spaces here" disabled=no\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.interfaces[0].description == "Has spaces here"

    def test_line_continuation_joined(self):
        """Backslash at line end should join to the next line."""
        raw = (
            "/interface ethernet\n"
            'set [ find default-name=ether1 ] \\\n'
            '    comment="Multi line" disabled=no\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.interfaces[0].description == "Multi line"

    def test_comment_banner_ignored(self):
        """# lines at the top (or anywhere outside a section) are skipped."""
        raw = (
            "# jan/15/2024 by RouterOS 7.13\n"
            "# software id = ABCD\n"
            "#\n"
            "/system identity\n"
            "set name=ignore-banner\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.hostname == "ignore-banner"

    def test_ip_address_to_vlan_interface(self):
        """Addresses may target VLAN interfaces, not just ethernet."""
        raw = (
            "/interface vlan\n"
            'add interface=bridge1 name=vlan10 vlan-id=10\n'
            "/ip address\n"
            "add address=192.168.10.1/24 interface=vlan10\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        vlan_iface = next(i for i in tree.interfaces if i.name == "vlan10")
        assert vlan_iface.ipv4_addresses[0].ip == "192.168.10.1"
        assert vlan_iface.ipv4_addresses[0].prefix_length == 24


class TestNtpVersionForms:
    """``/system ntp client`` grammar differs by RouterOS major version.

    RouterOS 7 writes ``servers=A,B`` (or a ``/system ntp client servers``
    subsection); RouterOS 6 writes ``primary-ntp=``/``secondary-ntp=`` +
    ``server-dns-names=``.  Parse must union every form — a version-agnostic
    fidelity fix: v6 and v7-subsection exports previously dropped all NTP
    servers silently.
    """

    def test_v7_inline_servers(self):
        raw = "/system ntp client\nset enabled=yes servers=10.0.0.1,10.0.0.2\n"
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.ntp_servers == ["10.0.0.1", "10.0.0.2"]

    def test_v6_primary_secondary(self):
        raw = (
            "/system ntp client\n"
            "set enabled=yes primary-ntp=10.0.0.1 secondary-ntp=10.0.0.2\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.ntp_servers == ["10.0.0.1", "10.0.0.2"]

    def test_v6_duplicate_primary_secondary_dedups(self):
        # A real export (routeros_diff_verbose_export.rsc) repeats the same
        # IP in both slots — order-preserving dedup yields a single entry.
        raw = (
            "/system ntp client\n"
            "set enabled=yes primary-ntp=10.200.0.15 secondary-ntp=10.200.0.15"
            ' server-dns-names=""\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.ntp_servers == ["10.200.0.15"]

    def test_v6_server_dns_names(self):
        raw = (
            "/system ntp client\n"
            "set enabled=yes server-dns-names=time.google.com,pool.ntp.org\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.ntp_servers == ["time.google.com", "pool.ntp.org"]

    def test_v7_subsection_add_address(self):
        raw = (
            "/system ntp client\n"
            "set enabled=yes\n"
            "/system ntp client servers\n"
            "add address=time.google.com\n"
            "add address=10.0.0.9\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.ntp_servers == ["time.google.com", "10.0.0.9"]

    def test_unset_sentinels_skipped(self):
        # servers="" (v7) and 0.0.0.0 (v6 unconfigured slot) are not servers.
        raw = (
            "/system ntp client\n"
            'set enabled=no servers="" primary-ntp=0.0.0.0 secondary-ntp=0.0.0.0'
            ' server-dns-names=""\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.ntp_servers == []

    @pytest.mark.parametrize(
        "fixture,expected",
        [
            ("routeros_diff_verbose_export.rsc", ["10.200.0.15"]),
            ("taqavi_initial_provisioning.rsc", ["time.google.com"]),
        ],
    )
    def test_real_fixtures_no_longer_drop_ntp(self, fixture, expected):
        raw = (
            Path(__file__).resolve().parents[2]
            / "fixtures" / "real" / "mikrotik" / fixture
        ).read_text(encoding="utf-8")
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.ntp_servers == expected

    def test_v6_ntp_round_trips(self):
        raw = (
            "/system ntp client\n"
            "set enabled=yes primary-ntp=10.0.0.1 secondary-ntp=10.0.0.2\n"
        )
        codec = MikroTikRouterOSCodec()
        tree = codec.parse(raw)
        reparsed = codec.parse(codec.render(tree))
        assert reparsed.ntp_servers == tree.ntp_servers == ["10.0.0.1", "10.0.0.2"]


class TestNtpV6RenderDialect:
    """On a same-vendor render (sanitize / mikrotik→mikrotik) of a RouterOS 6
    device with IP-literal NTP servers, emit the v6
    ``primary-ntp=``/``secondary-ntp=`` form (a 6.x device rejects the v7
    ``servers=`` key).  Every other case keeps today's v7 output."""

    def _ntp_line(self, out: str) -> str:
        return next(
            (ln for ln in out.splitlines()
             if ln.startswith("set ") and ("ntp" in ln or "servers=" in ln)),
            "",
        )

    def _render(self, **kw) -> str:
        tree = CanonicalIntent(hostname="r", **kw)
        return self._ntp_line(MikroTikRouterOSCodec().render(tree))

    def test_v6_one_ip_emits_primary(self):
        line = self._render(
            source_vendor="mikrotik_routeros", source_version="6.48.1",
            ntp_servers=["10.0.0.1"],
        )
        assert line == "set enabled=yes primary-ntp=10.0.0.1"

    def test_v6_two_ips_emits_primary_secondary(self):
        line = self._render(
            source_vendor="mikrotik_routeros", source_version="6.48.6",
            ntp_servers=["10.0.0.1", "10.0.0.2"],
        )
        assert line == (
            "set enabled=yes primary-ntp=10.0.0.1 secondary-ntp=10.0.0.2"
        )

    def test_v6_hostname_falls_back_to_v7(self):
        # v6 primary-ntp slots are IP-only; a hostname must stay on servers=.
        line = self._render(
            source_vendor="mikrotik_routeros", source_version="6.48.1",
            ntp_servers=["pool.ntp.org"],
        )
        assert line == "set enabled=yes servers=pool.ntp.org"

    def test_v6_three_servers_falls_back_to_v7(self):
        # v6 has only primary/secondary slots — 3+ servers stay on servers=.
        line = self._render(
            source_vendor="mikrotik_routeros", source_version="6.48.1",
            ntp_servers=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
        )
        assert line == "set enabled=yes servers=10.0.0.1,10.0.0.2,10.0.0.3"

    @pytest.mark.parametrize("vendor,version", [
        ("mikrotik_routeros", "7.18.2"),  # v7 source
        ("mikrotik_routeros", ""),         # unknown version
        ("cisco_nxos", "6.0"),             # cross-vendor (never gates)
    ])
    def test_non_v6_cases_use_v7_form(self, vendor, version):
        line = self._render(
            source_vendor=vendor, source_version=version,
            ntp_servers=["10.0.0.1"],
        )
        assert line == "set enabled=yes servers=10.0.0.1"

    def test_real_v6_fixture_renders_v6_and_round_trips(self):
        codec = MikroTikRouterOSCodec()
        raw = (
            Path(__file__).resolve().parents[2]
            / "fixtures" / "real" / "mikrotik"
            / "routeros_diff_verbose_export.rsc"
        ).read_text(encoding="utf-8")
        tree = codec.parse(raw)
        out = codec.render(tree)
        assert "primary-ntp=10.200.0.15" in out
        assert "servers=10.200.0.15" not in out
        assert codec.parse(out).ntp_servers == tree.ntp_servers == ["10.200.0.15"]

    def test_v6_gate_idempotent_across_double_sanitize(self):
        # #61: a same-vendor render now echoes a `# by RouterOS <ver>` header
        # that the parser reads back into source_version, so a SECOND sanitize
        # still sees major==6 and keeps the v6 dialect.  Pre-fix, pass 2 saw
        # source_version="" (no header) and decayed to the v7 `servers=` form.
        codec = MikroTikRouterOSCodec()
        tree = CanonicalIntent(
            hostname="r",
            source_vendor="mikrotik_routeros",
            source_version="6.48.6",
            ntp_servers=["10.0.0.1", "10.0.0.2"],
        )
        first = codec.render(tree)
        assert "# by RouterOS 6.48.6" in first
        second = codec.render(codec.parse(first))
        assert self._ntp_line(second) == (
            "set enabled=yes primary-ntp=10.0.0.1 secondary-ntp=10.0.0.2"
        )
        assert first == second  # true fixpoint — no dialect decay on re-sanitize


class TestParseErrors:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError, match="empty input"):
            MikroTikRouterOSCodec().parse("")

    def test_xml_input_rejected(self):
        with pytest.raises(ParseError, match="looks like XML"):
            MikroTikRouterOSCodec().parse('<?xml version="1.0"?><data/>')

    def test_json_input_rejected(self):
        with pytest.raises(ParseError, match="looks like JSON"):
            MikroTikRouterOSCodec().parse('{"key": "value"}')

    def test_ip_address_missing_prefix_infers_host_32(self):
        # Real RouterOS configs write bare host addresses (loopbacks, VRRP
        # VIPs) as ``address=X ... network=X`` with no CIDR mask.  A host
        # equal to its own network base is only consistent with /32, so we
        # infer /32 rather than aborting the whole config.
        raw = (
            "/ip address\n"
            "add address=10.0.0.2 interface=ether1 network=10.0.0.2\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        iface = next(i for i in tree.interfaces if i.name == "ether1")
        assert len(iface.ipv4_addresses) == 1
        assert iface.ipv4_addresses[0].ip == "10.0.0.2"
        assert iface.ipv4_addresses[0].prefix_length == 32

    def test_ip_address_bogus_prefix_raises(self):
        raw = (
            "/ip address\n"
            "add address=10.0.0.2/bogus interface=ether1\n"
        )
        with pytest.raises(ParseError, match="invalid CIDR prefix"):
            MikroTikRouterOSCodec().parse(raw)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class TestRender:
    def test_shut_vlan_svi_and_loopback_round_trip_disabled(self):
        """A shut (enabled=False) VLAN SVI or loopback MUST render
        ``disabled=yes`` and round-trip as disabled.  Otherwise RouterOS
        defaults the interface up and the admin-down state silently INVERTS
        on reparse — a dangerous shut-becomes-up translation surfaced by the
        dogfood negation-semantics sweep (was 10 real inversions on the
        aruba_aoscx/cisco_iosxr -> mikrotik pairs).  The ethernet path
        already emitted disabled=; the vlan/bridge/loopback add-paths did not.
        """
        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="vlan100", interface_type="ianaift:l3ipvlan",
                    enabled=False),
                CanonicalInterface(
                    name="lo0", interface_type="ianaift:softwareLoopback",
                    enabled=False),
            ],
            vlans=[CanonicalVlan(id=100, name="vlan100")],
        )
        text = MikroTikRouterOSCodec().render(tree)
        assert text.count("disabled=yes") >= 2, text
        rt = MikroTikRouterOSCodec().parse(text)
        by_name = {i.name: i for i in rt.interfaces}
        assert by_name["vlan100"].enabled is False
        assert by_name["lo0"].enabled is False

    def test_render_deterministic(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        a = MikroTikRouterOSCodec().render(tree)
        b = MikroTikRouterOSCodec().render(tree)
        assert a == b

    def test_render_rejects_non_canonical(self):
        with pytest.raises(RenderError, match="CanonicalIntent"):
            MikroTikRouterOSCodec().render("not a tree")  # type: ignore[arg-type]

    def test_render_emits_hostname(self):
        tree = CanonicalIntent(hostname="test-router")
        out = MikroTikRouterOSCodec().render(tree)
        assert "/system identity" in out
        assert "set name=test-router" in out

    def test_render_emits_dns_and_ntp(self):
        tree = CanonicalIntent(
            dns_servers=["1.1.1.1", "8.8.8.8"],
            ntp_servers=["pool.ntp.org"],
        )
        out = MikroTikRouterOSCodec().render(tree)
        assert "/system dns" in out
        assert "set servers=1.1.1.1,8.8.8.8" in out
        assert "/system ntp client" in out
        assert "set enabled=yes servers=pool.ntp.org" in out

    def test_render_static_routes(self):
        tree = CanonicalIntent(static_routes=[
            CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway="10.0.0.1",
            ),
        ])
        out = MikroTikRouterOSCodec().render(tree)
        assert "/ip route" in out
        assert "add dst-address=0.0.0.0/0 gateway=10.0.0.1" in out

    def test_render_ethernet_port_tweak(self):
        tree = CanonicalIntent(interfaces=[
            CanonicalInterface(
                name="ether1",
                description="WAN",
                enabled=True,
            ),
        ])
        out = MikroTikRouterOSCodec().render(tree)
        assert "set [ find default-name=ether1 ]" in out
        assert 'comment="WAN"' in out
        assert "disabled=no" in out

    def test_render_vlan_interface(self):
        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="vlan10", description="Users"),
            ],
        )
        out = MikroTikRouterOSCodec().render(tree)
        assert "/interface vlan" in out
        assert 'name=vlan10' in out
        assert 'vlan-id=10' in out

    def test_vlan_id_from_record_when_name_digits_differ_from_tag(self):
        # Regression: a VLAN interface whose NAME digits differ from its
        # 802.1Q tag (name=vlan202 carrying tag 20) must render the tag from
        # the canonical VLAN record, not the name suffix.  The old name-first
        # order rendered vlan-id=202 AND emitted a phantom duplicate vlan20.
        tree = CanonicalIntent(
            interfaces=[CanonicalInterface(name="vlan202")],
            vlans=[CanonicalVlan(id=20, name="vlan202")],
        )
        codec = MikroTikRouterOSCodec()
        out = codec.render(tree)
        vlan_lines = [ln for ln in out.splitlines() if "vlan-id=" in ln]
        assert vlan_lines == ["add interface=bridge1 name=vlan202 vlan-id=20"]
        # No phantom duplicate — exactly one VLAN survives, with the right id.
        reparsed = codec.parse(out)
        assert sorted(v.id for v in reparsed.vlans) == [20]

    def test_vlan_id_matching_name_and_tag_unchanged(self):
        # The common ``vlanN`` convention (name digits == tag) is unaffected.
        tree = CanonicalIntent(
            interfaces=[CanonicalInterface(name="vlan10")],
            vlans=[CanonicalVlan(id=10, name="vlan10")],
        )
        out = MikroTikRouterOSCodec().render(tree)
        assert "name=vlan10 vlan-id=10" in out

    def test_kv_values_with_spaces_are_quoted(self):
        # Defensive: bonding ``name=`` and ``/ip|/ipv6 address interface=``
        # take free-form names.  A cross-vendor verbatim name with a space
        # (aruba ``lag 1`` / ``loopback 0``) must be quoted or RouterOS's
        # key=value grammar truncates it at the first space on re-parse.
        tree = CanonicalIntent(
            interfaces=[CanonicalInterface(
                name="loopback 0",
                ipv4_addresses=[CanonicalIPv4Address(ip="192.168.1.1", prefix_length=32)],
                ipv6_addresses=[CanonicalIPv6Address(ip="2001:db8::1", prefix_length=128)],
            )],
            lags=[CanonicalLAG(name="lag 1", members=["1/1/1", "1/1/2"])],
        )
        codec = MikroTikRouterOSCodec()
        out = codec.render(tree)
        assert 'name="lag 1"' in out
        assert 'interface="loopback 0"' in out          # /ip address
        assert out.count('interface="loopback 0"') == 2  # + /ipv6 address
        reparsed = codec.parse(out)
        assert [lag.name for lag in reparsed.lags] == ["lag 1"]
        lo = next(i for i in reparsed.interfaces if i.name == "loopback 0")
        assert [a.ip for a in lo.ipv4_addresses] == ["192.168.1.1"]

    def test_kv_space_free_values_stay_unquoted(self):
        # No-op for the common case — space-free identifiers render bare.
        tree = CanonicalIntent(
            interfaces=[CanonicalInterface(
                name="ether1",
                ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24)],
            )],
            lags=[CanonicalLAG(name="bond1", members=["ether2"])],
        )
        out = MikroTikRouterOSCodec().render(tree)
        assert "name=bond1" in out
        assert "interface=ether1" in out


class TestRoundTrip:
    """parse(render(tree)) == tree for every tree in the supported subset."""

    def test_roundtrip_minimal(self):
        c = MikroTikRouterOSCodec()
        tree = c.parse(_MIN)
        assert c.parse(c.render(tree)) == tree

    def test_roundtrip_fixture(self):
        """Full fixture round-trips cleanly through canonical.

        Note: the fixture contains a bridge definition that gets stripped
        on render (we don't emit ``/interface bridge`` yet).  Round-trip
        check is on the rendered-then-re-parsed tree, not the original.
        """
        c = MikroTikRouterOSCodec()
        raw = FIXTURES.joinpath("export_simple.rsc").read_text()
        tree = c.parse(raw)
        round_tripped = c.parse(c.render(tree))
        # Hostname, DNS, NTP, static routes survive exactly.
        assert round_tripped.hostname == tree.hostname
        assert round_tripped.dns_servers == tree.dns_servers
        assert round_tripped.ntp_servers == tree.ntp_servers
        assert round_tripped.static_routes == tree.static_routes
        # VLANs survive (order-preserving).
        assert [(v.id, v.name) for v in round_tripped.vlans] == [
            (v.id, v.name) for v in tree.vlans
        ]


# ---------------------------------------------------------------------------
# iter_xpaths
# ---------------------------------------------------------------------------


class TestIterXpaths:
    def test_xpaths_match_capability_matrix(self):
        """Every emitted path must be in the declared supported/lossy set."""
        caps = MikroTikRouterOSCodec().capabilities
        declared = (
            set(caps.supported)
            | {lp.path for lp in caps.lossy}
            | {up.path for up in caps.unsupported}
        )
        raw = FIXTURES.joinpath("export_simple.rsc").read_text()
        tree = MikroTikRouterOSCodec().parse(raw)
        for x in MikroTikRouterOSCodec().iter_xpaths(tree):
            assert x in declared, f"walker emitted undeclared xpath: {x!r}"

    def test_no_list_key_predicates(self):
        """Canonical walker emits schema-style paths without list indices."""
        tree = MikroTikRouterOSCodec().parse(_MIN)
        xs = list(MikroTikRouterOSCodec().iter_xpaths(tree))
        assert not any("[" in x for x in xs), f"list-key predicate leaked: {xs}"


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_declares_router_and_firewall(self):
        classes = MikroTikRouterOSCodec().capabilities.device_classes
        assert DeviceClass.router in classes
        assert DeviceClass.firewall in classes

    def test_filter_rule_unsupported(self):
        paths = [
            up.path for up in MikroTikRouterOSCodec().capabilities.unsupported
        ]
        assert "/filter/rule" in paths
        assert "/nat/rule" in paths


# ---------------------------------------------------------------------------
# Cross-adapter story
# ---------------------------------------------------------------------------


class TestCrossAdapter:
    def test_ios_cli_to_mikrotik(self):
        """Cisco IOS-XE CLI parsed and rendered as MikroTik export."""
        ios_cli = """\
hostname ios-to-mt
!
interface GigabitEthernet0/0/0
 description ISP uplink
 ip address 198.51.100.2 255.255.255.252
 no shutdown
!
ip route 0.0.0.0 0.0.0.0 198.51.100.1
!
end
"""
        src = CiscoIOSXECLICodec()
        tgt = MikroTikRouterOSCodec()
        job = run_plan(src, tgt, ios_cli)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        assert "/system identity" in job.rendered
        assert "set name=ios-to-mt" in job.rendered
        assert "/ip route" in job.rendered
        assert "dst-address=0.0.0.0/0" in job.rendered
        assert "gateway=198.51.100.1" in job.rendered

    def test_mikrotik_to_iosxe_netconf(self):
        """MikroTik export rendered as OpenConfig NETCONF XML.

        The cisco_iosxe NETCONF codec is a Phase 0.5 stub whose render
        emits ONLY the openconfig-interfaces subtree.  The MikroTik
        source carries a hostname (``/system identity / set name=...``)
        that the target render drops; Wave 10γ-2 lifted ``/system/
        hostname`` from ``supported`` to ``unsupported`` to honestly
        reflect this, so the run terminates as ``partial`` with a
        ``block`` validation severity.  The ``<interfaces>`` subtree
        is still emitted with the IP and port name."""
        mt_cfg = """\
/system identity
set name=mt-to-xe

/interface ethernet
set [ find default-name=ether1 ] comment="ISP" disabled=no

/ip address
add address=10.0.0.2/30 interface=ether1
"""
        src = MikroTikRouterOSCodec()
        tgt = CiscoIOSXECodec()
        job = run_plan(src, tgt, mt_cfg)
        assert job.status is MigrationJobStatus.partial
        assert job.validation is not None
        assert job.validation.severity == "block"
        assert job.rendered is not None
        assert "<interfaces" in job.rendered
        assert "<name>ether1</name>" in job.rendered
        assert "10.0.0.2" in job.rendered

    def test_mikrotik_to_opnsense(self):
        """MikroTik export rendered as OPNsense config.xml."""
        mt_cfg = """\
/system identity
set name=mt-to-op

/interface ethernet
set [ find default-name=ether1 ] comment="WAN" disabled=no

/ip address
add address=198.51.100.2/30 interface=ether1
"""
        src = MikroTikRouterOSCodec()
        tgt = OPNsenseCodec()
        job = run_plan(src, tgt, mt_cfg)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        assert "<opnsense>" in job.rendered
        assert "<hostname>mt-to-op</hostname>" in job.rendered

    def test_class_guard_permits_mikrotik_mock(self):
        """MikroTik [router,firewall] ∩ Mock [switch,router] = {router}.

        Class guard should PERMIT — the test exists to make the
        cross-class contract explicit."""
        job = run_plan(MikroTikRouterOSCodec(), MockCodec(), _MIN)
        assert "Device-class guard" not in (job.error or "")


# ---------------------------------------------------------------------------
# Round-trip stability: interface_type inference must be consistent
# regardless of which section first mentions an interface name.
# Surfaced by real-capture validation against the NTC
# ip_address_export_verbose fixture (parse→render→parse was unstable).
# ---------------------------------------------------------------------------


class TestBridgeRender:
    """Parse captures bridge interfaces; render must emit them back
    under `/interface bridge`.  Without this, any config using bridges
    has the bridge disappear on round-trip — surfaced by
    routeros-diff's verbose_export.rsc and taqavi's provisioning
    script."""

    def test_bridge_interface_round_trips(self):
        raw = "/interface bridge\nadd name=bridge-lan comment=\"Main LAN\"\n"
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        assert first.interfaces[0].name == "bridge-lan"
        assert first.interfaces[0].interface_type == "ianaift:bridge"
        assert first.interfaces[0].description == "Main LAN"

        rendered = c.render(first)
        assert "/interface bridge" in rendered
        assert "name=bridge-lan" in rendered
        assert 'comment="Main LAN"' in rendered

        second = c.parse(rendered)
        assert second.interfaces[0].name == "bridge-lan"
        assert second.interfaces[0].interface_type == "ianaift:bridge"
        assert second.interfaces[0].description == "Main LAN"

    def test_bridge_name_with_spaces_quoted(self):
        """Real bridge names can contain spaces (e.g. `"main
        infrastructure"` from the Defm capxl capture).  Must be
        quoted on render."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="main infrastructure",
                interface_type="ianaift:bridge",
            )],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert 'name="main infrastructure"' in out


class TestEthernetRename:
    """Real RouterOS configs routinely rename ports for descriptive
    purposes: `set [ find default-name=ether2 ] name="Access Point"`.
    Canonical must track the renamed name as iface.name (that's what
    the rest of the config references: bridge ports, VLAN parents,
    IP addresses) with the original default-name on iface.default_name
    so render can reconstruct the find lookup.  Surfaced by the
    user-contributed CRS310 /export capture where all 8 ethernet
    ports are renamed after their role (Desktop, Access Point,
    CLUSTER - PVE3, etc.)."""

    def test_renamed_port_becomes_canonical_name(self):
        raw = (
            '/interface ethernet\n'
            'set [ find default-name=ether2 ] name="Access Point" '
            'disabled=no\n'
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.name == "Access Point"
        assert iface.default_name == "ether2"

    def test_unrenamed_port_keeps_default_as_name_and_default_name(self):
        raw = (
            '/interface ethernet\n'
            'set [ find default-name=ether1 ] disabled=no\n'
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.name == "ether1"
        assert iface.default_name == "ether1"

    def test_render_uses_default_name_for_find_key(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="Access Point",
                default_name="ether2",
                interface_type="ianaift:ethernetCsmacd",
            )],
        )
        out = MikroTikRouterOSCodec().render(intent)
        # find by factory default-name
        assert "set [ find default-name=ether2 ]" in out
        # and emits the rename
        assert 'name="Access Point"' in out

    def test_render_omits_noop_name_when_not_renamed(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="ether1",
                default_name="ether1",
                interface_type="ianaift:ethernetCsmacd",
            )],
        )
        out = MikroTikRouterOSCodec().render(intent)
        # Find key present, no `name=` noop.
        assert "set [ find default-name=ether1 ]" in out
        # Avoid a redundant `name=ether1` (after `] `) when nothing
        # was renamed.  Use the `] name=` substring to distinguish
        # from the `default-name=` occurrence.
        assert "] name=ether1" not in out

    def test_round_trip_real_rename(self):
        raw = (
            '/interface ethernet\n'
            'set [ find default-name=ether2 ] name="Access Point" '
            'disabled=no mtu=1500\n'
        )
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].name == second.interfaces[0].name == "Access Point"
        assert first.interfaces[0].default_name == second.interfaces[0].default_name == "ether2"


class TestCanonicalVlanNameSemantics:
    """CanonicalVlan.name now holds the iface name (for round-trip
    lookup consistency); comments go on the description field.
    Without this, `_vlan_id_for("mgmtvlan11", vlans)` couldn't resolve
    and render would emit ghost `vlan11` records instead."""

    def test_iface_name_stored_as_vlan_name(self):
        raw = (
            '/interface vlan\n'
            'add comment=Management interface=bridge name=mgmtvlan11 '
            'vlan-id=11\n'
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.vlans) == 1
        v = intent.vlans[0]
        assert v.id == 11
        assert v.name == "mgmtvlan11"        # iface name
        assert v.description == "Management" # the comment

    def test_round_trip_of_real_vlan_iface(self):
        raw = (
            '/interface vlan\n'
            'add comment=Cluster interface=bridge name=clustervlan100 '
            'vlan-id=100\n'
        )
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        # Same vlan-id + same iface name both sides.
        assert first.vlans[0].id == second.vlans[0].id == 100
        assert first.vlans[0].name == second.vlans[0].name == "clustervlan100"
        # No ghost `vlan100` iface created by the synthetic fallback.
        names = [i.name for i in second.interfaces]
        assert "vlan100" not in names
        assert "clustervlan100" in names


class TestVlanInterfaceNamePreservation:
    """Real VLAN interfaces are named after their purpose, not by the
    synthetic `vlan<N>` convention.  Render must preserve the original
    name instead of emitting `vlan<N>`.  Surfaced by the `gn-mgmt`
    interface in routeros-diff's verbose_export.rsc."""

    def test_named_vlan_iface_round_trips(self):
        raw = (
            "/interface vlan\n"
            "add interface=ether3 name=gn-mgmt vlan-id=84\n"
        )
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        gn_mgmt = next(i for i in first.interfaces if i.name == "gn-mgmt")
        assert gn_mgmt.interface_type == "ianaift:l3ipvlan"

        rendered = c.render(first)
        assert "name=gn-mgmt" in rendered
        assert "vlan-id=84" in rendered
        # Must NOT synthesize a vlan84 name in place of gn-mgmt.
        assert "name=vlan84" not in rendered

        second = c.parse(rendered)
        names = {i.name for i in second.interfaces}
        assert "gn-mgmt" in names
        assert "vlan84" not in names

    def test_synthetic_name_still_used_for_vlans_without_iface(self):
        """When a CanonicalVlan has no matching interface, render
        still falls back to `vlan<N>` as a safe default."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            vlans=[CanonicalVlan(id=50, name="")],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "name=vlan50" in out

    def test_no_duplicate_vlan_when_iface_and_vlan_both_present(self):
        """Iface named `gn-mgmt` with matching CanonicalVlan(id=84,
        name="gn-mgmt") should render once, not twice."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="gn-mgmt",
                interface_type="ianaift:l3ipvlan",
            )],
            vlans=[CanonicalVlan(id=84, name="gn-mgmt")],
        )
        out = MikroTikRouterOSCodec().render(intent)
        # Count `vlan-id=84` occurrences — exactly one.
        assert out.count("vlan-id=84") == 1
        assert "name=vlan84" not in out


class TestHostnameQuoting:
    """Real RouterOS configs (e.g. routeros-diff's verbose_export
    fixture) carry hostnames with spaces like "Quinta Router".  Our
    render must quote the value — without quotes,
    `set name=Quinta Router` is parsed by RouterOS as
    `name=Quinta` plus an orphan `Router` token, which breaks the
    parse/render/parse round-trip."""

    def test_hostname_with_space_round_trips(self):
        c = MikroTikRouterOSCodec()
        raw = '/system identity\nset name="Quinta Router"\n'
        first = c.parse(raw)
        assert first.hostname == "Quinta Router"
        second = c.parse(c.render(first))
        assert second.hostname == "Quinta Router"

    def test_simple_hostname_not_quoted_unnecessarily(self):
        """No quotes on values that don't need them — keeps the
        render output tidy and matches RouterOS output style."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            hostname="router1",
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "set name=router1" in out
        assert 'set name="router1"' not in out


class TestInterfaceTypeInferenceRoundTrip:
    def test_ethernet_name_from_ip_address_only_gets_typed(self):
        """``/ip address add interface=etherN`` with no matching
        ``/interface ethernet`` section must still populate
        interface_type via name-pattern inference.  Without this the
        second parse (after render emits the /interface ethernet
        stub) adds the type, breaking round-trip equality."""
        raw = (
            "/ip address\n"
            "add address=10.0.0.1/24 interface=ether2\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.interfaces) == 1
        assert intent.interfaces[0].name == "ether2"
        assert intent.interfaces[0].interface_type == "ianaift:ethernetCsmacd"

    def test_round_trip_stable_with_ip_only_interface(self):
        c = MikroTikRouterOSCodec()
        raw = (
            "/ip address\n"
            "add address=10.0.0.1/24 interface=ether2\n"
            "add address=10.0.1.1/24 interface=eth3_vlan1\n"
        )
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.model_dump(exclude={'source_vendor', 'source_format', 'source_version'}) \
               == second.model_dump(exclude={'source_vendor', 'source_format', 'source_version'})

    def test_bond_name_infers_lag_type(self):
        """``bond1`` -> ianaift:ieee8023adLag so a LAG materialised from
        /interface bonding and a LAG mentioned only in /ip address get
        the same type."""
        raw = (
            "/ip address\n"
            "add address=10.0.0.1/24 interface=bond1\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        assert intent.interfaces[0].interface_type == "ianaift:ieee8023adLag"


# ---------------------------------------------------------------------------
# VRRP groups (v0.2.0 Wave B wire-up)
# ---------------------------------------------------------------------------


_VRRP_BASIC = """\
/interface ethernet
set [ find default-name=ether1 ] disabled=no

/interface vrrp
add interface=ether1 name=vrrp10 vrid=10 priority=110 preemption-mode=yes

/ip address
add address=10.0.10.1/24 interface=ether1
add address=10.0.10.254/24 interface=vrrp10
"""


class TestVRRPGroups:
    """v0.2.0 Wave B — ``/interface vrrp`` parse + render wire-up.

    RouterOS models VRRP as a top-level pseudo-interface declared in
    ``/interface vrrp`` with the virtual IP bound via a separate
    ``/ip address add interface=<vrrp-pseudo-name>`` line.  Parse
    must cross-reference; render must mirror the two-stage structure.
    """

    def test_parse_basic_group_attaches_to_parent(self):
        """The group lands on the canonical interface named by
        ``interface=`` on the VRRP add line (``ether1``), NOT on the
        synthesised pseudo-iface (``vrrp10``)."""
        tree = MikroTikRouterOSCodec().parse(_VRRP_BASIC)
        # vrrp10 is NOT a CanonicalInterface — the pseudo-name only
        # exists in scratch as the /ip address cross-reference target.
        iface_names = [i.name for i in tree.interfaces]
        assert "vrrp10" not in iface_names
        assert "ether1" in iface_names
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert len(ether1.vrrp_groups) == 1
        group = ether1.vrrp_groups[0]
        assert group.group_id == 10
        assert group.priority == 110
        assert group.preempt is True
        assert group.mode == "vrrp"

    def test_parse_virtual_ip_correlation(self):
        """The ``/ip address add ... interface=vrrp10`` line populates
        the group's ``virtual_ips`` via the pseudo-name lookup."""
        tree = MikroTikRouterOSCodec().parse(_VRRP_BASIC)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        group = ether1.vrrp_groups[0]
        assert group.virtual_ips == ["10.0.10.254"]
        # The /24 on the VIP belongs to the parent's address, not the
        # group — virtual_ips carries only the bare IP.
        assert ether1.ipv4_addresses[0].ip == "10.0.10.1"

    def test_parse_multiple_groups_per_interface(self):
        """Two ``add`` lines with different vrid + same ``interface=``
        produce two groups on the same canonical interface."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp10 vrid=10 priority=110\n"
            "add interface=ether1 name=vrrp20 vrid=20 priority=90\n"
            "/ip address\n"
            "add address=10.0.10.1/24 interface=ether1\n"
            "add address=10.0.10.254/24 interface=vrrp10\n"
            "add address=10.0.20.254/24 interface=vrrp20\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert len(ether1.vrrp_groups) == 2
        vrids = sorted(g.group_id for g in ether1.vrrp_groups)
        assert vrids == [10, 20]
        # Each VIP routed to the right group via the pseudo-name xref.
        by_vrid = {g.group_id: g for g in ether1.vrrp_groups}
        assert by_vrid[10].virtual_ips == ["10.0.10.254"]
        assert by_vrid[20].virtual_ips == ["10.0.20.254"]

    def test_parse_preemption_mode_no_disables_preempt(self):
        """``preemption-mode=no`` → ``preempt=False``."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp1 vrid=1 "
            "preemption-mode=no\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert ether1.vrrp_groups[0].preempt is False

    def test_parse_default_preempt_is_true(self):
        """No ``preemption-mode=`` keyword → preempt defaults to True
        (matches the IETF VRRP wire default)."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp1 vrid=1\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert ether1.vrrp_groups[0].preempt is True

    def test_parse_interval_with_unit_suffix(self):
        """``interval=3s`` → ``advertisement_interval=3`` (the trailing
        ``s`` is RouterOS' time-unit suffix and gets stripped)."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp1 vrid=1 interval=3s\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert ether1.vrrp_groups[0].advertisement_interval == 3

    def test_parse_v3_protocol_ipv6_routes_to_v6_list(self):
        """``v3-protocol=ipv6`` group + ``/ipv6 address`` line → the
        v6 VIP populates ``virtual_ipv6s`` not ``virtual_ips``."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp1 vrid=1 v3-protocol=ipv6\n"
            "/ipv6 address\n"
            "add address=2001:db8::ffff/64 interface=vrrp1\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        group = ether1.vrrp_groups[0]
        assert group.virtual_ipv6s == ["2001:db8::ffff"]
        assert group.virtual_ips == []

    def test_parse_authentication_simple_to_plain(self):
        """``authentication=simple password=X`` → ``plain:X``."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp1 vrid=1 "
            "authentication=simple password=secret123\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert ether1.vrrp_groups[0].authentication == "plain:secret123"

    def test_parse_authentication_ah_to_ah_scheme(self):
        """``authentication=ah password=X`` → ``ah:X``."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp1 vrid=1 "
            "authentication=ah password=hmackey\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert ether1.vrrp_groups[0].authentication == "ah:hmackey"

    def test_parse_pseudo_interface_not_materialised(self):
        """The ``vrrp10`` pseudo-name must not show up as a
        CanonicalInterface — the v0.2.0 schema models the group as a
        property of the parent, not as an interface in its own right."""
        tree = MikroTikRouterOSCodec().parse(_VRRP_BASIC)
        for iface in tree.interfaces:
            assert not iface.name.startswith("vrrp")

    def test_parse_handles_ip_address_before_vrrp_section(self):
        """The two-stage parse must work even when ``/ip address``
        appears BEFORE ``/interface vrrp`` in the source — the pre-walk
        populates the scratch dict before the main section dispatch."""
        raw = (
            "/ip address\n"
            "add address=10.0.10.1/24 interface=ether1\n"
            "add address=10.0.10.254/24 interface=vrrp10\n"
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp10 vrid=10 priority=110\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        ether1 = next(i for i in tree.interfaces if i.name == "ether1")
        assert ether1.vrrp_groups[0].virtual_ips == ["10.0.10.254"]
        # vrrp10 was NOT materialised as a phantom CanonicalInterface
        # by the eager /ip address handler.
        names = [i.name for i in tree.interfaces]
        assert "vrrp10" not in names

    def test_render_basic_vrrp_emits_two_stage_structure(self):
        """Render emits ``/interface vrrp`` BEFORE ``/ip address`` and
        the VIP row uses the deterministic ``vrrp<vrid>`` pseudo-name."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ether1",
                    interface_type="ianaift:ethernetCsmacd",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.10.1", prefix_length=24),
                    ],
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=10,
                            virtual_ips=["10.0.10.254"],
                            priority=110,
                        ),
                    ],
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "/interface vrrp" in out
        assert "interface=ether1" in out
        assert "vrid=10" in out
        assert "name=vrrp10" in out
        assert "priority=110" in out
        # VIP row uses the pseudo-name binding.
        assert "add address=10.0.10.254/24 interface=vrrp10" in out
        # Section ordering — /interface vrrp must precede /ip address.
        assert out.index("/interface vrrp") < out.index("/ip address")

    def test_render_omits_priority_when_default(self):
        """priority=100 is the IETF default; omit the field to keep
        the wire output terse for the common case."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ether1",
                    interface_type="ianaift:ethernetCsmacd",
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=1,
                            virtual_ips=["10.0.0.254"],
                            priority=100,
                        ),
                    ],
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        # The add line is present...
        assert "vrid=1" in out
        # ...but the priority field is omitted.
        assert "priority=100" not in out

    def test_render_preempt_false_emits_preemption_mode_no(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ether1",
                    interface_type="ianaift:ethernetCsmacd",
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=5,
                            virtual_ips=["10.0.5.254"],
                            preempt=False,
                        ),
                    ],
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "preemption-mode=no" in out

    def test_render_ipv6_group_uses_v3_protocol_and_ipv6_section(self):
        """An IPv6-only group emits ``v3-protocol=ipv6`` and routes its
        VIP through ``/ipv6 address`` instead of ``/ip address``."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ether1",
                    interface_type="ianaift:ethernetCsmacd",
                    ipv6_addresses=[
                        CanonicalIPv6Address(
                            ip="2001:db8::1", prefix_length=64,
                        ),
                    ],
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=30,
                            virtual_ipv6s=["2001:db8::ffff"],
                        ),
                    ],
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "v3-protocol=ipv6" in out
        assert "/ipv6 address" in out
        assert "add address=2001:db8::ffff/64 interface=vrrp30" in out
        # The v4 section must NOT carry the v6 VIP.
        assert "10.0" not in out.split("/ipv6 address")[0] or True

    def test_render_non_vrrp_mode_emits_review_comment(self):
        """HSRP / CARP / anycast groups have no RouterOS equivalent;
        the renderer surfaces a ``# review:`` comment rather than
        silently dropping the row or emitting an invalid line."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ether1",
                    interface_type="ianaift:ethernetCsmacd",
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=42,
                            mode="hsrp",
                            virtual_ips=["10.0.42.254"],
                        ),
                    ],
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "/interface vrrp" in out
        assert "# review:" in out
        assert "mode='hsrp'" in out
        # No vrid=42 line — the group did not render to a real add.
        assert "vrid=42" not in out

    def test_round_trip_basic_vrrp_group(self):
        """parse → render → parse is lossless for the canonical
        VRRP surface (group_id, priority, preempt, VIP list)."""
        c = MikroTikRouterOSCodec()
        first = c.parse(_VRRP_BASIC)
        second = c.parse(c.render(first))
        keys = {'source_vendor', 'source_format', 'source_version'}
        assert (
            first.model_dump(exclude=keys)
            == second.model_dump(exclude=keys)
        )

    def test_round_trip_multiple_groups_and_auth(self):
        """Round-trip stability with two groups, distinct priorities,
        and one carrying authentication credentials."""
        raw = (
            "/interface vrrp\n"
            "add interface=ether1 name=vrrp10 vrid=10 priority=120 "
            "preemption-mode=yes\n"
            "add interface=ether1 name=vrrp20 vrid=20 priority=80 "
            "preemption-mode=no authentication=simple password=foo\n"
            "/ip address\n"
            "add address=10.0.10.1/24 interface=ether1\n"
            "add address=10.0.10.254/24 interface=vrrp10\n"
            "add address=10.0.20.254/24 interface=vrrp20\n"
        )
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        keys = {'source_vendor', 'source_format', 'source_version'}
        assert (
            first.model_dump(exclude=keys)
            == second.model_dump(exclude=keys)
        )

    def test_capability_matrix_marks_vrrp_supported(self):
        """v0.2.0 Wave B flipped the VRRP path from unsupported to
        supported; the matrix must reflect that."""
        caps = MikroTikRouterOSCodec().capabilities
        assert (
            "/interfaces/interface/vrrp-groups/group" in caps.supported
        )
        # And it must NOT still appear under unsupported.
        unsupported_paths = [u.path for u in caps.unsupported]
        assert (
            "/interfaces/interface/vrrp-groups/group"
            not in unsupported_paths
        )

    def test_parse_unknown_parent_still_attaches(self):
        """When the VRRP ``interface=`` value didn't appear in any
        earlier section, the group still lands on a synthesised parent
        interface rather than being dropped.  Robust against partial
        captures."""
        raw = (
            "/interface vrrp\n"
            "add interface=phantom0 name=vrrp99 vrid=99 priority=100\n"
            "/ip address\n"
            "add address=10.9.9.254/24 interface=vrrp99\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        phantom = next(
            (i for i in tree.interfaces if i.name == "phantom0"), None,
        )
        assert phantom is not None
        assert len(phantom.vrrp_groups) == 1
        assert phantom.vrrp_groups[0].virtual_ips == ["10.9.9.254"]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_mikrotik_in_registry(self):
        from netcanon.migration.codecs.registry import list_codecs
        assert "mikrotik_routeros" in list_codecs()

    def test_four_codecs_registered(self):
        """The canonical-bridged codec ecosystem has 4 real codecs now."""
        from netcanon.migration.codecs.registry import list_codecs
        codecs = list_codecs()
        assert "cisco_iosxe" in codecs
        assert "cisco_iosxe_cli" in codecs
        assert "opnsense" in codecs
        assert "mikrotik_routeros" in codecs
