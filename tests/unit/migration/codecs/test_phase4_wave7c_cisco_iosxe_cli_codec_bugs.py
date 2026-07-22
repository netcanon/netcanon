"""
Wave 7c Agent C regression tests — cisco_iosxe_cli source CODEC_BUG cells.

Reproduction tests for the 7 CODEC_BUG cells the post-Wave-9 matrix
flagged with ``source_codec=cisco_iosxe_cli``.  All cells fall into
two root causes:

1. Arista EOS render did not emit ``switchport trunk native vlan <N>``
   and the parser did not recognise it.  A Cisco source carrying
   ``switchport trunk native vlan 10`` round-tripped through Arista
   with the native-VLAN signal silently dropped — so
   ``project_switchport_to_vlan`` projected the trunk member as
   TAGGED on VLAN 10 rather than UNTAGGED (native rides untagged),
   corrupting every cell's VLAN-centric port lists.  Fix: symmetric
   render+parse of ``switchport trunk native vlan <N>`` (mirrors
   Cisco IOS-XE / EOS User Manual "Switchport Configuration").

2. Arista EOS and Juniper Junos parsers apply the same phantom-VLAN
   guard around ``project_switchport_to_vlan`` as cisco_iosxe_cli, so a
   cross-vendor round-trip re-derives the SAME canonical VLAN set the
   source produced (no ``vlans`` count drift in Phase 4).  The guard
   keeps every VLAN a port is bound to as an ``access`` or trunk
   ``native`` member — single, operator-declared VIDs (e.g. a
   ``switchport access vlan 20`` whose VLAN lives in ``vlan.dat`` with
   no ``vlan 20`` stanza and no SVI) — and prunes only a VID appearing
   SOLELY in a wide ``switchport trunk allowed`` range as a possible
   phantom.  (The blanket "keep only explicit stanzas + SVIs" prune
   this file originally pinned silently dropped those real access
   VLANs — the exact user-reported ``user_contrib_cat9300`` symptom;
   see ``transforms.access_and_native_vlan_ids``.)  The tests below
   verify the round-trip stays stable at that corrected full set.
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
from netcanon.migration.codecs.aruba_aoss.render import (
    render_intent as aruba_render,
)
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    parse_intent as cisco_parse,
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
# cisco_iosxe_cli -> arista_eos: phantom-VLAN guard + trunk native vlan
# ---------------------------------------------------------------------------


def test_cisco_to_arista_no_phantom_vlan_inflation_real() -> None:
    """``user_contrib_cat9300`` declares ``vlan 1`` + ``vlan 11`` via
    SVIs; VIDs 10/20/100/150 have no ``vlan N`` stanza but ARE bound to
    ports as access / trunk-native VLANs, so they are real and must
    survive.  The arista round-trip must reproduce the SAME full VLAN
    set the cisco source parsed — stable, no drift and no phantom
    inflation of any wide trunk range."""
    src = _load(
        "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
    )
    intent_src = cisco_parse(src)
    rendered = arista_render(intent_src)
    intent_rt = arista_parse(rendered)
    src_ids = sorted(v.id for v in intent_src.vlans)
    rt_ids = sorted(v.id for v in intent_rt.vlans)
    assert src_ids == rt_ids == [1, 10, 11, 20, 100, 150], (
        f"Arista round-trip must preserve the cisco source's real VLAN "
        f"id set (access/native VLANs included); "
        f"got src={src_ids!r}, rt={rt_ids!r}"
    )


def test_cisco_to_arista_preserves_trunk_native_vlan() -> None:
    """``kitchen_sink`` Port-channel1 carries ``switchport trunk native
    vlan 10``; on round-trip through Arista the iface must still
    appear as untagged (not tagged) on VLAN 10's port list."""
    src = _load("tests/fixtures/synthetic/cisco_iosxe_cli/kitchen_sink.txt")
    intent_src = cisco_parse(src)
    rendered = arista_render(intent_src)
    # The render output must carry ``switchport trunk native vlan
    # 10`` so the parse-back reconstitutes the native-VLAN binding.
    assert "switchport trunk native vlan 10" in rendered, (
        "Arista render must emit native-vlan declaration for "
        "trunk interfaces with trunk_native_vlan set"
    )
    intent_rt = arista_parse(rendered)
    v10 = next(v for v in intent_rt.vlans if v.id == 10)
    # Native-vlan trunks land in untagged_ports, not tagged_ports.
    # ``project_switchport_to_vlan`` purges the tagged_ports entry
    # whenever the same iface appears on the native VID's untagged.
    assert "Port-channel1" in v10.untagged_ports, (
        f"Port-channel1 (native vlan 10) must surface as untagged "
        f"on VLAN 10 after round-trip; got {v10.untagged_ports!r} "
        f"tagged={v10.tagged_ports!r}"
    )
    assert "Port-channel1" not in v10.tagged_ports


def test_cisco_to_arista_kitchen_sink_vlan_set_stable() -> None:
    """``kitchen_sink`` declares vlans 10/20/30/40 and trunk-allowed
    references stay within that set.  The arista round-trip must
    produce exactly those four VLAN ids."""
    src = _load("tests/fixtures/synthetic/cisco_iosxe_cli/kitchen_sink.txt")
    intent_src = cisco_parse(src)
    rendered = arista_render(intent_src)
    intent_rt = arista_parse(rendered)
    src_ids = sorted(v.id for v in intent_src.vlans)
    rt_ids = sorted(v.id for v in intent_rt.vlans)
    assert src_ids == rt_ids == [10, 20, 30, 40]


# ---------------------------------------------------------------------------
# cisco_iosxe_cli -> juniper_junos: phantom-VLAN guard
# ---------------------------------------------------------------------------


def test_cisco_to_junos_no_phantom_vlan_inflation_real() -> None:
    """``user_contrib_cat9300`` round-trips through Junos must reproduce
    the same full VLAN set — VIDs 10/20/100/150 are real access/native
    VLANs bound to ports (not phantoms), so they survive and the
    round-trip stays stable."""
    src = _load(
        "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
    )
    intent_src = cisco_parse(src)
    rendered = junos_render(intent_src)
    intent_rt = junos_parse(rendered)
    src_ids = sorted(v.id for v in intent_src.vlans)
    rt_ids = sorted(v.id for v in intent_rt.vlans)
    assert src_ids == rt_ids == [1, 10, 11, 20, 100, 150], (
        f"Junos round-trip must preserve the cisco source's real VLAN "
        f"id set (access/native VLANs included); "
        f"got src={src_ids!r}, rt={rt_ids!r}"
    )


def test_cisco_to_junos_native_vlan_preserved() -> None:
    """``batfish_cisco_interface`` declares vlan ids 1, 2, 3, 111,
    1005, 1006, 1234, 4094.  An interface carries ``switchport trunk
    native vlan 6`` for VID 6 which has no ``vlan 6`` stanza.  A
    native-VLAN binding is a real VLAN (it must exist for the trunk to
    pass untagged traffic), so VID 6 is kept and the Junos round-trip
    stays stable at the full set."""
    src = _load(
        "tests/fixtures/real/cisco_iosxe/batfish_cisco_interface.txt"
    )
    intent_src = cisco_parse(src)
    rendered = junos_render(intent_src)
    intent_rt = junos_parse(rendered)
    src_ids = sorted(v.id for v in intent_src.vlans)
    rt_ids = sorted(v.id for v in intent_rt.vlans)
    assert src_ids == rt_ids, (
        f"Junos round-trip must preserve the source's VLAN ids; "
        f"got src={src_ids!r}, rt={rt_ids!r}"
    )
    assert 6 in rt_ids, (
        "Native VLAN 6 (bound via ``switchport trunk native vlan 6``) "
        "is a real VLAN and must survive round-trip"
    )


# ---------------------------------------------------------------------------
# cisco_iosxe_cli -> aruba_aoss: phantom-VLAN guard (no trunk-native fix needed)
# ---------------------------------------------------------------------------


def test_cisco_to_aruba_kitchen_sink_vlan_set_stable() -> None:
    """``kitchen_sink`` round-trips through Aruba AOS-S must preserve
    the explicit four VLAN ids without inflation or loss."""
    src = _load("tests/fixtures/synthetic/cisco_iosxe_cli/kitchen_sink.txt")
    intent_src = cisco_parse(src)
    rendered = aruba_render(intent_src)
    intent_rt = aruba_parse(rendered)
    src_ids = sorted(v.id for v in intent_src.vlans)
    rt_ids = sorted(v.id for v in intent_rt.vlans)
    assert src_ids == rt_ids == [10, 20, 30, 40]


# ---------------------------------------------------------------------------
# Pinned unit tests for the underlying transforms / parsers
# ---------------------------------------------------------------------------


def test_arista_render_emits_trunk_native_vlan() -> None:
    """A bare CanonicalIntent with one trunk interface carrying
    ``trunk_native_vlan=10`` must render to text containing the
    ``switchport trunk native vlan 10`` directive."""
    from netcanon.migration.canonical.intent import (
        CanonicalIntent,
        CanonicalInterface,
        CanonicalVlan,
    )
    intent = CanonicalIntent(
        hostname="sw1",
        vlans=[CanonicalVlan(id=10, name="USERS")],
        interfaces=[CanonicalInterface(
            name="Ethernet1",
            switchport_mode="trunk",
            trunk_allowed_vlans=[10, 20],
            trunk_native_vlan=10,
        )],
    )
    rendered = arista_render(intent)
    assert "switchport trunk native vlan 10" in rendered
    assert "switchport mode trunk" in rendered
    assert "switchport trunk allowed vlan 10,20" in rendered


def test_junos_phantom_vlan_guard_drops_undeclared_vid() -> None:
    """Synthetic Junos config: declare ``vlans v10 vlan-id 10``, then
    a port with ``vlan members v99`` (no v99 stanza).  The Junos
    parser must not surface VLAN 99 in ``intent.vlans``."""
    cfg = (
        "set system host-name sw1\n"
        "set vlans v10 vlan-id 10\n"
        "set interfaces Ethernet1 unit 0 family ethernet-switching "
        "interface-mode trunk\n"
        "set interfaces Ethernet1 unit 0 family ethernet-switching "
        "vlan members 99\n"
    )
    intent = junos_parse(cfg)
    ids = sorted(v.id for v in intent.vlans)
    assert ids == [10], (
        f"Phantom VLAN 99 must be pruned (no ``vlans v99`` stanza); "
        f"got {ids!r}"
    )


def test_arista_parse_recognises_trunk_native_vlan() -> None:
    """Arista parse symmetry: a config with ``switchport trunk native
    vlan 10`` must populate ``CanonicalInterface.trunk_native_vlan``
    so the projection helper places the iface on the native VID's
    ``untagged_ports`` list (not ``tagged_ports``)."""
    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        "   name USERS\n"
        "interface Ethernet1\n"
        "   switchport mode trunk\n"
        "   switchport trunk native vlan 10\n"
        "   switchport trunk allowed vlan 10,20\n"
    )
    intent = arista_parse(cfg)
    iface = next(i for i in intent.interfaces if i.name == "Ethernet1")
    assert iface.trunk_native_vlan == 10
    by_id = {v.id: v for v in intent.vlans}
    assert "Ethernet1" in by_id[10].untagged_ports
    assert "Ethernet1" not in by_id[10].tagged_ports
