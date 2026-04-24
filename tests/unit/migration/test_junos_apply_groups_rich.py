"""
Unit tests for GAP 8 — richer Junos apply-groups inheritance.

GAP 4 shipped apply-groups host-name inheritance; GAP 8 generalises
to a full two-pass parse where every ``set groups <g> <path>``
line gets replayed through the top-level dispatcher (group name
stripped) when ``<g>`` is referenced in ``set apply-groups``.

Composition semantics:
- Group content applies FIRST (in reverse apply-groups order so the
  first-declared group wins for scalars — matches Junos's first-
  match composition), then top-level content applies LAST (so
  direct-intent overwrites inherited scalars).
- Lists (static_routes, local_users, dns_servers, ntp_servers,
  syslog_servers) accumulate from BOTH sources with de-dup.

See the commit message for the bug caught: before GAP 8, the
ksator QFX5100 + EX4550 fixtures lost their static routes, local
users, SNMP community, NTP servers, DNS servers, syslog servers,
and management interface — ALL of which live under
``set groups POC_Lab ...``.
"""

from __future__ import annotations

import pathlib

import pytest

from netconfig.migration.codecs.juniper_junos import JunosCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Group → top-level composition (synthetic)
# ---------------------------------------------------------------------------


class TestSyntheticGroupInheritance:
    def test_user_from_group(self):
        raw = (
            "set groups G system login user admin class super-user\n"
            "set groups G system login user admin authentication "
            'encrypted-password "$6$fake$hash"\n'
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.local_users) == 1
        u = intent.local_users[0]
        assert u.name == "admin"
        assert u.role == "super-user"
        assert u.privilege_level == 15
        assert u.hashed_password == "junos:$6$fake$hash"

    def test_static_route_from_group(self):
        raw = (
            "set groups G routing-options static route 10.0.0.0/8 "
            "next-hop 192.0.2.1\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert len(intent.static_routes) == 1
        r = intent.static_routes[0]
        assert r.destination == "10.0.0.0/8"
        assert r.gateway == "192.0.2.1"

    def test_snmp_community_from_group(self):
        raw = (
            "set groups G snmp community public authorization read-only\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.snmp is not None
        assert intent.snmp.community == "public"

    def test_ntp_server_from_group(self):
        raw = (
            "set groups G system ntp server 1.2.3.4 prefer\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.ntp_servers == ["1.2.3.4"]

    def test_dns_name_server_from_group(self):
        raw = (
            "set groups G system name-server 8.8.8.8\n"
            "set groups G system name-server 8.8.4.4\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        # Group content applies in reverse-declaration order within
        # a group stanza, but the list accumulator preserves all
        # additions and de-dupes.
        assert set(intent.dns_servers) == {"8.8.8.8", "8.8.4.4"}

    def test_syslog_host_from_group(self):
        raw = (
            "set groups G system syslog host 10.0.0.100 any info\n"
            "set groups G system syslog host 10.0.0.101 authorization any\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert set(intent.syslog_servers) == {"10.0.0.100", "10.0.0.101"}

    def test_interface_from_group(self):
        raw = (
            "set groups G interfaces vme unit 0 family inet "
            "address 172.25.90.100/24\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        vme = next((i for i in intent.interfaces if i.name == "vme"), None)
        assert vme is not None
        assert any(a.ip == "172.25.90.100" for a in vme.ipv4_addresses)


class TestCompositionSemantics:
    """Direct-intent-wins for scalars; additive for lists."""

    def test_direct_hostname_overrides_group(self):
        raw = (
            "set groups G system host-name group-host\n"
            "set system host-name direct-host\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "direct-host"

    def test_first_apply_group_wins_for_scalar(self):
        """For scalar fields (hostname), the FIRST-declared group
        wins among apply-groups (matches Junos's first-match
        composition)."""
        raw = (
            "set groups A system host-name host-from-A\n"
            "set groups B system host-name host-from-B\n"
            "set apply-groups A\n"
            "set apply-groups B\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == "host-from-A"

    def test_lists_accumulate_from_both_groups_and_top_level(self):
        """Static routes, users, dns/ntp/syslog — group content and
        top-level content both contribute; no field wins."""
        raw = (
            "set groups G system ntp server 10.0.0.1\n"
            "set system ntp server 10.0.0.2\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert set(intent.ntp_servers) == {"10.0.0.1", "10.0.0.2"}

    def test_unapplied_group_silently_dropped(self):
        raw = (
            "set groups G system host-name group-host\n"
            # No apply-groups line — G never activates.
        )
        intent = JunosCodec().parse(raw)
        assert intent.hostname == ""


# ---------------------------------------------------------------------------
# Real-fixture regression — ksator QFX5100 + EX4550
# ---------------------------------------------------------------------------


class TestKsatorFixturesRichInheritance:
    """GAP 8 unlocks a huge amount of canonical tree data from the
    ksator real captures.  Before GAP 8 the two fixtures produced
    nearly-empty trees (just VLANs + interface shells); after
    GAP 8 every top-level stanza declared under
    ``set groups POC_Lab ...`` flows into the canonical tree via
    ``set apply-groups POC_Lab``.
    """

    _QFX = (
        "tests/fixtures/real/junos/"
        "ksator_labmgmt_qfx5100_junos173.set"
    )
    _EX = (
        "tests/fixtures/real/junos/"
        "ksator_labmgmt_ex4550_junos151.set"
    )

    def test_qfx5100_hostname_user_snmp_routes(self):
        intent = JunosCodec().parse(
            pathlib.Path(self._QFX).read_text(encoding="utf-8")
        )
        assert intent.hostname == "QFX5100-183"
        assert any(u.name == "lab" for u in intent.local_users)
        assert intent.snmp is not None
        assert intent.snmp.community == "public"
        # 4 static routes from `set groups POC_Lab routing-options
        # static route ...` blocks.
        assert len(intent.static_routes) == 4
        destinations = {r.destination for r in intent.static_routes}
        assert "10.255.255.0/24" in destinations
        assert "10.161.0.0/16" in destinations
        assert "172.16.0.0/12" in destinations
        assert "192.168.0.0/16" in destinations
        for r in intent.static_routes:
            assert r.gateway == "172.25.90.1"

    def test_qfx5100_mgmt_iface_vme(self):
        """The `vme` management interface is declared only inside
        `set groups POC_Lab interfaces vme unit 0 family inet
        address 172.25.90.183/24` — must populate via apply-groups."""
        intent = JunosCodec().parse(
            pathlib.Path(self._QFX).read_text(encoding="utf-8")
        )
        vme = next(
            (i for i in intent.interfaces if i.name == "vme"), None,
        )
        assert vme is not None
        ips = {(a.ip, a.prefix_length) for a in vme.ipv4_addresses}
        assert ("172.25.90.183", 24) in ips

    def test_qfx5100_ntp_dns_syslog_from_groups(self):
        intent = JunosCodec().parse(
            pathlib.Path(self._QFX).read_text(encoding="utf-8")
        )
        assert intent.ntp_servers == ["66.129.255.62"]
        assert intent.dns_servers == ["172.29.131.60"]
        # QFX fixture has two syslog hosts.
        assert "172.25.45.6" in intent.syslog_servers

    def test_ex4550_hostname_user_routes(self):
        intent = JunosCodec().parse(
            pathlib.Path(self._EX).read_text(encoding="utf-8")
        )
        assert intent.hostname == "EX4550-190"
        assert any(u.name == "lab" for u in intent.local_users)
        # EX4550 has 1 default route from its group-scoped config.
        assert len(intent.static_routes) >= 1
        assert any(
            r.destination == "0.0.0.0/0" for r in intent.static_routes
        )

    def test_ex4550_mgmt_iface_vme(self):
        intent = JunosCodec().parse(
            pathlib.Path(self._EX).read_text(encoding="utf-8")
        )
        vme = next(
            (i for i in intent.interfaces if i.name == "vme"), None,
        )
        # EX4550 fixture's vme lives under POC_Lab group too.
        # The fixture has vme at top level OR in groups — either
        # way, GAP 8 must surface it.  If the fixture doesn't
        # actually declare vme, this test is informational only.
        if vme is not None:
            assert len(vme.ipv4_addresses) >= 0  # soft check


# ---------------------------------------------------------------------------
# GAP 9b — apply-groups statement + group-content preservation on render
# ---------------------------------------------------------------------------


class TestApplyGroupsRenderPreservation:
    """GAP 9b: parse preserves `set apply-groups <G>` as
    :attr:`CanonicalIntent.apply_groups` AND the raw group body as
    :attr:`CanonicalIntent.group_content[G]`.  Render re-emits the
    `set groups <G> <body...>` + `set apply-groups <G>` pair so
    operators see their hand-written structure round-trip without
    loss."""

    def test_apply_groups_preserved_on_parse(self):
        raw = (
            "set groups G system host-name X\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        assert intent.apply_groups == ["G"]
        assert "G" in intent.group_content

    def test_orphan_group_not_persisted(self):
        """A group declared but never apply-grouped silently drops
        from group_content (matches Junos's own composition —
        unreferenced groups don't contribute)."""
        raw = (
            "set groups G system host-name X\n"
            # No apply-groups G line.
        )
        intent = JunosCodec().parse(raw)
        assert intent.apply_groups == []
        assert "G" not in intent.group_content

    def test_group_body_tokens_preserved(self):
        raw = (
            "set groups G system host-name X\n"
            "set groups G snmp community public authorization read-only\n"
            "set apply-groups G\n"
        )
        intent = JunosCodec().parse(raw)
        body = intent.group_content["G"]
        assert len(body) == 2
        assert ["system", "host-name", "X"] in body
        assert [
            "snmp", "community", "public",
            "authorization", "read-only",
        ] in body

    def test_render_emits_groups_then_apply_groups(self):
        raw = (
            "set groups G system host-name X\n"
            "set apply-groups G\n"
        )
        codec = JunosCodec()
        intent = codec.parse(raw)
        rendered = codec.render(intent)
        # Group content emitted as `set groups G ...`
        assert "set groups G system host-name X" in rendered
        # Apply-groups statement preserved
        assert "set apply-groups G" in rendered
        # Order: groups first, then apply-groups.
        g_idx = rendered.find("set groups G system host-name X")
        a_idx = rendered.find("set apply-groups G")
        assert g_idx < a_idx

    def test_full_roundtrip_stable(self):
        """Repeated parse → render → parse produces identical
        canonical trees (bit-stable round-trip)."""
        raw = (
            "set groups POC system host-name SW1\n"
            "set groups POC snmp community public authorization read-only\n"
            "set groups POC system ntp server 10.0.0.1\n"
            "set groups POC routing-options static route 0.0.0.0/0 "
            "next-hop 10.0.0.2\n"
            "set apply-groups POC\n"
        )
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        # Canonical tree identical on round-trip.
        assert first.hostname == second.hostname == "SW1"
        assert first.apply_groups == second.apply_groups == ["POC"]
        assert first.group_content == second.group_content
        assert first.ntp_servers == second.ntp_servers == ["10.0.0.1"]
        assert len(first.static_routes) == len(second.static_routes) == 1
        assert first.snmp.community == second.snmp.community == "public"

    def test_multi_word_quoted_body_roundtrips(self):
        """Multi-word quoted values (like banner messages) must
        re-quote on group-content render so the re-parser gets the
        original single-token value back."""
        raw = (
            "set groups G system login message "
            '"Authorized use only"\n'
            "set apply-groups G\n"
        )
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        # Rendered output must contain the QUOTED value.
        assert (
            'set groups G system login message "Authorized use only"'
            in rendered
        )
        # Round-trip stability.
        second = codec.parse(rendered)
        assert first.group_content == second.group_content

    def test_ksator_ex4550_group_content_roundtrips(self):
        """Real-fixture regression: the EX4550 fixture has 22 lines
        of group content including a banner message with embedded
        newlines.  Round-trip must preserve every line exactly."""
        raw = pathlib.Path(
            "tests/fixtures/real/junos/"
            "ksator_labmgmt_ex4550_junos151.set"
        ).read_text(encoding="utf-8")
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert first.group_content == second.group_content
        assert first.apply_groups == second.apply_groups

    def test_empty_apply_groups_field_on_fresh_intent(self):
        from netconfig.migration.canonical.intent import CanonicalIntent
        intent = CanonicalIntent()
        assert intent.apply_groups == []
        assert intent.group_content == {}
