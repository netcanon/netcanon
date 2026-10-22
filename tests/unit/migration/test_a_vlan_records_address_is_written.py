"""A VLAN record's address is written, on an interface of the VLAN, once.

Four targets state a VLAN's address only on an interface of the VLAN:
EOS, IOS-XE CLI and NX-OS on `interface Vlan<N>`, AOS-CX on `interface
vlan <N>`.  A tree can hold the address on the VLAN record with no such
interface -- the Junos parser folds the address of an `irb.<N>` that a
VLAN binds with `l3-interface` onto the VLAN, and keeps no interface for
the unit -- and for that tree the renderer has to write one
(`synthesize_svis_from_vlan_l3`).  EOS and IOS-XE did.  NX-OS and AOS-CX
wrote nothing and declared the path lossy, so the gateway of the one
committed capture with such a VLAN was missing from their output.

The other half is to write it ONCE.  The synthesiser looked for an
interface of the VLAN by the name `Vlan<N>` only, so an AOS-CX tree,
whose interface of VLAN 101 is `vlan 101`, got a `Vlan101` beside it on
EOS and IOS-XE: one address on two interfaces, the second without the
first's description or shutdown.  An interface of the VLAN is recognised
however a codec spells it.

The output is read twice: as text, by a reader written here for each
target's grammar (the header the target writes, and the address lines
under it), and with the target's own parser.  Each check is handed the
defect it is for and has to fail.  Not reached: the targets that state a
VLAN's address some other way, or declare the path lossy; and the
address's virtual gateway, which the interface written for it does not
carry (declared lossy on all four).
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pytest

import netcanon.migration.canonical.transforms as transforms
import netcanon.migration.codecs.aruba_aoscx.render as aoscx_render
import netcanon.migration.codecs.cisco_nxos.render as nxos_render
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_JUNOS_IRB = _REPO / "tests/fixtures/real/junos/saidvandeklundert_snmpv3_junos172.set"

#: The header each target writes for the interface of VLAN <N>.
_HEADER = {
    "arista_eos": "interface Vlan{}",
    "cisco_iosxe_cli": "interface Vlan{}",
    "cisco_nxos": "interface Vlan{}",
    "aruba_aoscx": "interface vlan {}",
}
_TARGETS = sorted(_HEADER)


def _address_line(target: str, address: str, secondary: bool = False) -> str:
    """The line ``target`` writes for ``address`` (``ip/len``), by hand."""
    iface = ipaddress.ip_interface(address)
    if target == "cisco_iosxe_cli":
        line = f"ip address {iface.ip} {iface.netmask}"
    else:
        line = f"ip address {address}"
    return f"{line} secondary" if secondary else line


def _stanzas(text: str) -> list[tuple[str, list[str]]]:
    """Each ``interface`` line in column 0, with the indented lines under
    it; any other line in column 0 ends the stanza, a blank one does not."""
    out: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in text.splitlines():
        if line.startswith("interface "):
            current = (line.rstrip(), [])
            out.append(current)
        elif not line.strip():
            continue
        elif current is not None and line[:1] in (" ", "\t"):
            current[1].append(line.strip())
        else:
            current = None
    return out


def _holding(text: str, line: str) -> list[str]:
    """The headers of the interfaces whose stanza has ``line``."""
    return [h for h, body in _stanzas(text) if line in body]


def _vlan_tree(*addresses: str, interface: str | None = None) -> CanonicalIntent:
    """VLAN 11 holding ``addresses``; with ``interface``, an interface of
    that name holding them too, as a parser that folds them makes it."""
    addrs = [
        CanonicalIPv4Address(
            ip=a.split("/")[0], prefix_length=int(a.split("/")[1]), is_secondary=k > 0,
        )
        for k, a in enumerate(addresses)
    ]
    interfaces = []
    if interface is not None:
        interfaces = [CanonicalInterface(
            name=interface, description="users", enabled=False, ipv4_addresses=addrs,
        )]
    return CanonicalIntent(
        hostname="r",
        vlans=[CanonicalVlan(id=11, name="BLUE", ipv4_addresses=addrs)],
        interfaces=interfaces,
    )


# ---------------------------------------------------------------------------
# The checks.  Each returns what it found wrong; a test asserts none, and a
# test at the foot hands it the defect it is for.
# ---------------------------------------------------------------------------


def _not_written(target: str) -> list[str]:
    """A VLAN record's address, with no interface of the VLAN in the tree,
    is on the target's interface of VLAN 11 and on no other, and the
    target's parser reads it back."""
    rendered = get_codec(target).render(_vlan_tree("10.11.0.1/24"))
    header = _HEADER[target].format(11)
    problems = []
    holders = _holding(rendered, _address_line(target, "10.11.0.1/24"))
    if holders != [header]:
        problems.append(f"the address is on {holders}, not on [{header!r}]")
    back = get_codec(target).parse(rendered)
    on_vlan = [a.ip for v in back.vlans if v.id == 11 for a in v.ipv4_addresses]
    on_iface = [a.ip for i in back.interfaces for a in i.ipv4_addresses]
    if "10.11.0.1" not in on_vlan + on_iface:
        problems.append("the target's parser reads the address nowhere")
    return problems


def _written_twice(target: str, spelling: str) -> list[str]:
    """An interface of the VLAN the tree has, in any spelling, is the only
    one that holds the address."""
    rendered = get_codec(target).render(_vlan_tree("10.11.0.1/24", interface=spelling))
    holders = _holding(rendered, _address_line(target, "10.11.0.1/24"))
    if len(holders) != 1:
        return [f"{spelling!r}: the address is on {holders}"]
    return []


def _not_secondary(target: str) -> list[str]:
    """A VLAN record's second address is written `secondary`, under the
    first, and read back so."""
    rendered = get_codec(target).render(_vlan_tree("10.11.0.1/24", "10.11.1.1/24"))
    header = _HEADER[target].format(11)
    body = dict(_stanzas(rendered)).get(header, [])
    want = [
        _address_line(target, "10.11.0.1/24"),
        _address_line(target, "10.11.1.1/24", secondary=True),
    ]
    problems = []
    if [ln for ln in body if ln.startswith("ip address")] != want:
        problems.append(f"{header!r} has {body}, not {want}")
    back = get_codec(target).parse(rendered)
    read = [
        [(a.ip, a.is_secondary) for a in i.ipv4_addresses]
        for i in back.interfaces
        if any(a.ip == "10.11.0.1" for a in i.ipv4_addresses)
    ]
    if read != [[("10.11.0.1", False), ("10.11.1.1", True)]]:
        problems.append(f"the target's parser reads {read}")
    return problems


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", _TARGETS)
def test_a_vlan_records_address_is_written(target: str) -> None:
    assert _not_written(target) == []


def test_nxos_turns_the_feature_on() -> None:
    """The NX-OS render derives its `feature` lines from the tree, and the
    interface it writes for a VLAN record is the only VLAN interface here."""
    rendered = get_codec("cisco_nxos").render(_vlan_tree("10.11.0.1/24"))
    assert "feature interface-vlan" in rendered.splitlines()


@pytest.mark.parametrize("spelling", ["Vlan11", "vlan11", "vlan 11"])
@pytest.mark.parametrize("target", _TARGETS)
def test_an_interface_of_the_vlan_is_not_written_twice(target: str, spelling: str) -> None:
    assert _written_twice(target, spelling) == []


@pytest.mark.parametrize("target", _TARGETS)
def test_a_second_address_is_secondary(target: str) -> None:
    assert _not_secondary(target) == []


@pytest.mark.parametrize("target", _TARGETS)
def test_the_junos_irb_reaches_the_target(target: str) -> None:
    """The committed capture whose VLAN holds the address of its `irb`
    unit, through the path the API takes (port names translated)."""
    source = get_codec("juniper_junos")
    raw = _JUNOS_IRB.read_text(encoding="utf-8")
    tree = source.parse(raw)
    assert [v.id for v in tree.vlans if v.ipv4_addresses] == [698]
    assert not [i.name for i in tree.interfaces if i.name.startswith("irb.")]
    job = run_plan_with_checked_names(
        source, get_codec(target), raw, port_rename_map={},
    )
    holders = _holding(job.rendered, _address_line(target, "10.200.1.1/22"))
    assert holders == [_HEADER[target].format(698)], holders


# ---------------------------------------------------------------------------
# Each check, handed the defect it is for.
# ---------------------------------------------------------------------------


def _patch_synth(monkeypatch: pytest.MonkeyPatch, fn) -> None:
    """Replace the synthesiser where each renderer looks it up: EOS and
    IOS-XE import it when they render, NX-OS and AOS-CX when loaded."""
    for module in (transforms, nxos_render, aoscx_render):
        monkeypatch.setattr(module, "synthesize_svis_from_vlan_l3", fn)


@pytest.mark.parametrize("target", _TARGETS)
def test_the_check_sees_an_address_not_written(
    target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_synth(monkeypatch, lambda intent, name=None: [])
    assert _not_written(target)


@pytest.mark.parametrize("target", _TARGETS)
def test_the_check_sees_an_interface_written_twice(
    target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The synthesiser as it was: it knew `Vlan<N>` alone."""
    monkeypatch.setattr(
        transforms, "_AN_SVI_OF_ANY_SPELLING", re.compile(r"^Vlan(\d+)$"),
    )
    assert _written_twice(target, "vlan 11")


#: The renderers that write `secondary` from the address's own flag.
#: IOS-XE writes it for every address after the first, by position.
_READS_THE_FLAG = ["arista_eos", "aruba_aoscx", "cisco_nxos"]


def _addresses_changed(monkeypatch: pytest.MonkeyPatch, change) -> None:
    original = transforms.synthesize_svis_from_vlan_l3

    def changed(intent, name=None):
        return [
            iface.model_copy(update={"ipv4_addresses": change(iface.ipv4_addresses)})
            for iface in original(intent, name)
        ]

    _patch_synth(monkeypatch, changed)


@pytest.mark.parametrize("target", _TARGETS)
def test_the_check_sees_a_second_address_not_secondary(
    target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No address marked: every target that reads the flag fails, and
    IOS-XE, which does not, passes -- which is what that list says."""
    _addresses_changed(monkeypatch, lambda addrs: [
        a.model_copy(update={"is_secondary": False}) for a in addrs
    ])
    assert bool(_not_secondary(target)) == (target in _READS_THE_FLAG)


@pytest.mark.parametrize("target", _TARGETS)
def test_the_check_sees_a_second_address_lost(
    target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _addresses_changed(monkeypatch, lambda addrs: addrs[:1])
    assert _not_secondary(target)
