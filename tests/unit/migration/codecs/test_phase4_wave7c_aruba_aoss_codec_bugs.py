"""
Wave 7c Agent A regression tests — aruba_aoss source CODEC_BUG cells.

Reproduction tests for the 13 CODEC_BUG cells the post-Wave-9 matrix
flagged with ``source_codec=aruba_aoss``.  All cells fall into four
root causes:

1. Arista EOS render did not project VLAN-centric memberships into
   per-port switchport state - VLANs round-tripped with empty
   ``tagged_ports`` / ``untagged_ports``.  Fix: call
   ``project_vlan_to_switchport`` at the top of ``arista_eos.render``.

2. Arista EOS parse did not fold ``interface Vlan<N>`` SVI L3 onto
   the matching ``CanonicalVlan.ipv4_addresses`` - SVI IPs lived only
   on the sibling interface and were invisible to VLAN-centric
   renderers.  Fix: extract Cisco-IOS-XE's ``_synthesize_vlans_from_svis``
   into a shared ``project_svi_to_vlan`` transform and call it from
   the Arista parser.

3. Junos parser materialised ``intent.interfaces`` in lexicographic
   key order, so VLAN port lists came back as
   ``['1/1', '1/10', '1/11', ..., '1/2', '1/20', ...]``.  Fix: sort
   the iface_state keys with ``_natural_port_sort_key``.

4. Aruba parser collected overlapping VLAN memberships (port appears
   in multiple ``vlans[].untagged_ports`` lists when source has
   ``vlan 1 / untagged 1/1-1/24`` followed by ``vlan 20 / untagged
   1/1-1/12``).  Aruba semantics: the second stanza *moves* those
   ports from VLAN 1 to VLAN 20.  Fix: drop reassigned ports from
   earlier VLAN stanzas as new VLAN stanzas claim them.

5. Arista EOS render had no path for ``radius-server host`` lines -
   ``CanonicalIntent.radius_servers`` round-tripped to an empty list.
   Fix: emit Cisco-derived ``radius-server host <ip> [auth-port N]
   [acct-port N] [key SECRET]`` form + symmetric parser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.arista_eos.parse import (
    parse_intent as arista_parse,
)
from netcanon.migration.codecs.arista_eos.render import (
    render_intent as arista_render,
)
from netcanon.migration.codecs.aruba_aoss.parse import (
    parse_intent as aruba_parse,
)
from netcanon.migration.codecs.juniper_junos.parse import (
    parse_intent as junos_parse,
)
from netcanon.migration.codecs.juniper_junos.render import (
    render_intent as junos_render,
)

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# aruba_aoss -> arista_eos: VLAN-centric -> port-centric projection
# ---------------------------------------------------------------------------


def test_aruba_to_arista_preserves_vlan_untagged_ports() -> None:
    """The 5-member-stack Aruba fixture carries ``vlan 1 / untagged
    1/1-1/24``; after the VLAN reassignment override fix, those
    ports belong to VLANs 20 + 30 (not VLAN 1).  Arista round-trip
    must surface them on the right VLAN's untagged_ports list."""
    src = _load(
        "tests/fixtures/real/aruba_aoss/"
        "aruba_central_5memberstack_rendered.cfg"
    )
    intent_src = aruba_parse(src)
    rendered = arista_render(intent_src)
    intent_rt = arista_parse(rendered)

    vlans_by_id = {v.id: v for v in intent_rt.vlans}
    # VLAN 20 USERS - source claims ``untagged 1/1-1/12`` + tagged 1/25-1/26.
    v20 = vlans_by_id[20]
    assert "1/1" in v20.untagged_ports, (
        f"VLAN 20 should have 1/1 untagged after round-trip; got "
        f"{v20.untagged_ports!r}"
    )
    assert "1/12" in v20.untagged_ports
    assert "1/25" in v20.tagged_ports
    assert "1/26" in v20.tagged_ports
    # VLAN 30 VOICE - source claims ``untagged 1/13-1/24``.
    v30 = vlans_by_id[30]
    assert "1/13" in v30.untagged_ports
    assert "1/24" in v30.untagged_ports


def test_aruba_to_arista_preserves_svi_ipv4_on_vlan_record() -> None:
    """``vlan 1 / ip address 192.168.176.35/24`` (Aruba SVI shape)
    rounds through Arista's ``interface Vlan1 / ip address ...``
    grammar and must fold back onto ``vlans[0].ipv4_addresses``."""
    src = _load(
        "tests/fixtures/real/aruba_aoss/"
        "hpe_community_2920_wb1608_dhcp_snooping.cfg"
    )
    intent_src = aruba_parse(src)
    rendered = arista_render(intent_src)
    intent_rt = arista_parse(rendered)

    v1 = next(v for v in intent_rt.vlans if v.id == 1)
    assert any(
        a.ip == "192.168.176.35" and a.prefix_length == 24
        for a in v1.ipv4_addresses
    ), (
        f"VLAN 1 SVI IP must round-trip onto vlan.ipv4_addresses; "
        f"got {v1.ipv4_addresses!r}"
    )


def test_aruba_to_arista_preserves_radius_servers() -> None:
    """The kitchen_sink synthetic fixture carries two RADIUS servers
    (10.0.20.10 / 10.0.20.11) with shared keys.  Arista render +
    parse round-trip must preserve both records and the keys."""
    src = _load("tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg")
    intent_src = aruba_parse(src)
    assert len(intent_src.radius_servers) == 2

    rendered = arista_render(intent_src)
    intent_rt = arista_parse(rendered)
    assert len(intent_rt.radius_servers) == 2, (
        f"expected 2 RADIUS servers after round-trip, got "
        f"{len(intent_rt.radius_servers)}: {intent_rt.radius_servers!r}"
    )
    hosts = {s.host for s in intent_rt.radius_servers}
    assert hosts == {"10.0.20.10", "10.0.20.11"}
    keys = {s.key for s in intent_rt.radius_servers}
    assert "fakeRadiusSecret-A" in keys
    assert "fakeRadiusSecret-B" in keys


# ---------------------------------------------------------------------------
# aruba_aoss -> juniper_junos: natural port ordering + override semantic
# ---------------------------------------------------------------------------


def test_aruba_to_junos_preserves_natural_port_order() -> None:
    """Junos-rendered + reparsed VLAN port lists must be in
    operator-natural order (``1/1, 1/2, ..., 1/24``) not lexical
    (``1/1, 1/10, 1/11, ..., 1/2, 1/20, ...``)."""
    src = _load(
        "tests/fixtures/real/aruba_aoss/"
        "user_contrib_2930m_wc1611.cfg"
    )
    intent_src = aruba_parse(src)
    rendered = junos_render(intent_src)
    intent_rt = junos_parse(rendered)

    v1 = next(v for v in intent_rt.vlans if v.id == 1)
    untagged = v1.untagged_ports
    # Must contain at least 1/1, 1/2, ..., 1/9, 1/10 in natural order.
    sub = [p for p in untagged if p.startswith("1/") and not any(c.isalpha() for c in p[2:])]
    # Verify natural-sort property: each numeric port name comes
    # before the next-higher one.
    nums = []
    for p in sub:
        try:
            nums.append(int(p.split("/")[1]))
        except ValueError:
            continue
    assert nums == sorted(nums), (
        f"VLAN 1 untagged_ports must be in natural numeric order; "
        f"got {sub!r}"
    )


def test_aruba_to_junos_vlan_reassignment_override() -> None:
    """``vlan 1 / untagged 1/1-1/24`` followed by ``vlan 20 /
    untagged 1/1-1/12`` should reassign 1/1-1/12 from VLAN 1 to
    VLAN 20 in the canonical (Aruba semantics)."""
    src = _load(
        "tests/fixtures/real/aruba_aoss/"
        "aruba_central_5memberstack_rendered.cfg"
    )
    intent_src = aruba_parse(src)
    v1 = next(v for v in intent_src.vlans if v.id == 1)
    v20 = next(v for v in intent_src.vlans if v.id == 20)
    v30 = next(v for v in intent_src.vlans if v.id == 30)
    # 1/1-1/12 belong to VLAN 20 only (after reassignment).
    for p in [f"1/{n}" for n in range(1, 13)]:
        assert p in v20.untagged_ports
        assert p not in v1.untagged_ports
    # 1/13-1/24 belong to VLAN 30 only (after reassignment).
    for p in [f"1/{n}" for n in range(13, 25)]:
        assert p in v30.untagged_ports
        assert p not in v1.untagged_ports


def test_aruba_to_junos_preserves_vlan_untagged_ports() -> None:
    """Full aruba->junos->aruba canonical round-trip must preserve
    the per-VLAN untagged_ports lists end-to-end."""
    src = _load(
        "tests/fixtures/real/aruba_aoss/"
        "hpe_community_2930f_wc1610_dhcp_server.cfg"
    )
    intent_src = aruba_parse(src)
    rendered = junos_render(intent_src)
    intent_rt = junos_parse(rendered)

    src_by_id = {v.id: v for v in intent_src.vlans}
    rt_by_id = {v.id: v for v in intent_rt.vlans}
    for vid, src_v in src_by_id.items():
        rt_v = rt_by_id.get(vid)
        assert rt_v is not None, f"VLAN {vid} disappeared on round-trip"
        # Compare as sets (order may legitimately differ across
        # canonicalisation passes; natural-sort is checked separately).
        assert set(rt_v.untagged_ports) == set(src_v.untagged_ports), (
            f"VLAN {vid} untagged_ports drifted: "
            f"src={src_v.untagged_ports!r} rt={rt_v.untagged_ports!r}"
        )


# ---------------------------------------------------------------------------
# Pinned unit tests for the underlying transforms / parsers
# ---------------------------------------------------------------------------


def test_arista_render_projects_vlan_to_switchport_on_bare_intent() -> None:
    """Render a CanonicalIntent whose only L2 surface is
    ``vlans[].untagged_ports`` (no per-iface switchport state).
    The output must contain ``switchport access vlan N`` lines on
    each port."""
    from netcanon.migration.canonical.intent import (
        CanonicalIntent, CanonicalInterface, CanonicalVlan,
    )

    intent = CanonicalIntent(
        hostname="sw1",
        vlans=[
            CanonicalVlan(id=10, name="USERS", untagged_ports=["Ethernet1"]),
        ],
        interfaces=[CanonicalInterface(name="Ethernet1")],
    )
    rendered = arista_render(intent)
    assert "switchport mode access" in rendered
    assert "switchport access vlan 10" in rendered


def test_arista_parse_radius_server_one_liner() -> None:
    """Symmetric parse: ingest the form arista_eos.render emits."""
    cfg = (
        "hostname sw1\n"
        "radius-server host 10.0.20.10 key fakeSecret\n"
        'radius-server host 10.0.20.11 auth-port 11812 acct-port 11813 key "ws sec"\n'
    )
    intent = arista_parse(cfg)
    assert len(intent.radius_servers) == 2
    s1 = intent.radius_servers[0]
    assert s1.host == "10.0.20.10"
    assert s1.key == "fakeSecret"
    assert s1.auth_port == 1812
    assert s1.acct_port == 1813
    s2 = intent.radius_servers[1]
    assert s2.host == "10.0.20.11"
    assert s2.key == "ws sec"
    assert s2.auth_port == 11812
    assert s2.acct_port == 11813


def test_arista_parse_folds_svi_ipv4_onto_vlan() -> None:
    """``interface Vlan10 / ip address 10.10.10.1/24`` must fold
    onto ``vlans[i].ipv4_addresses`` for VLAN 10 even when the
    explicit ``vlan 10`` stanza had no IP."""
    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        "   name USERS\n"
        "!\n"
        "interface Vlan10\n"
        "   ip address 10.10.10.1/24\n"
        "!\n"
    )
    intent = arista_parse(cfg)
    v10 = next(v for v in intent.vlans if v.id == 10)
    assert any(
        a.ip == "10.10.10.1" and a.prefix_length == 24
        for a in v10.ipv4_addresses
    ), f"SVI IP must fold onto VLAN.ipv4_addresses; got {v10.ipv4_addresses!r}"


def test_junos_parse_natural_port_order_synthetic() -> None:
    """Synthetic junos config with 12 access-mode ports (1/1..1/12)
    on the same VLAN must come back ordered ``1/1, 1/2, ..., 1/12``,
    not ``1/1, 1/10, 1/11, 1/12, 1/2, ...``."""
    lines = ["set system host-name sw1", "set vlans v10 vlan-id 10"]
    for n in range(1, 13):
        lines.append(
            f"set interfaces 1/{n} unit 0 family ethernet-switching "
            f"interface-mode access"
        )
        lines.append(
            f"set interfaces 1/{n} unit 0 family ethernet-switching "
            f"vlan members v10"
        )
    cfg = "\n".join(lines) + "\n"
    intent = junos_parse(cfg)

    iface_names = [i.name for i in intent.interfaces]
    expected = [f"1/{n}" for n in range(1, 13)]
    # All 12 must appear in natural order.
    indices = [iface_names.index(p) for p in expected]
    assert indices == sorted(indices), (
        f"interfaces must materialise in natural-port order; "
        f"got order {iface_names!r}"
    )

    v10 = next(v for v in intent.vlans if v.id == 10)
    assert v10.untagged_ports == expected, (
        f"VLAN 10 untagged_ports must be in natural order; "
        f"got {v10.untagged_ports!r}"
    )


def test_aruba_parse_vlan_reassignment_dropped_from_default() -> None:
    """Synthetic Aruba config: VLAN 1 claims 1/1-1/4, then VLAN 20
    claims 1/1-1/2.  After parse, VLAN 1 should retain only
    [1/3, 1/4]; VLAN 20 should hold [1/1, 1/2]."""
    cfg = (
        "hostname sw1\n"
        "vlan 1\n"
        '   name "DEFAULT_VLAN"\n'
        "   untagged 1/1-1/4\n"
        "   exit\n"
        "vlan 20\n"
        '   name "USERS"\n'
        "   untagged 1/1-1/2\n"
        "   exit\n"
    )
    intent = aruba_parse(cfg)
    v1 = next(v for v in intent.vlans if v.id == 1)
    v20 = next(v for v in intent.vlans if v.id == 20)
    assert v20.untagged_ports == ["1/1", "1/2"]
    assert v1.untagged_ports == ["1/3", "1/4"], (
        f"VLAN 1 must lose ports reassigned to VLAN 20; "
        f"got {v1.untagged_ports!r}"
    )
