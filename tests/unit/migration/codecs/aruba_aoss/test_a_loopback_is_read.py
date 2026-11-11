"""An AOS-S loopback, as the switch prints it, is read; and one is written so.

HPE gives the command as ``interface loopback <0-7>``, with a space (Aruba
Basic Operation Guide for AOS-S 16.10, "Managing loopback interfaces"; the
context's prompt is ``lo-<N>``), and an address on a loopback is given with
no mask: "when you configure an IP address for a loopback interface, you do
not specify a network mask" (HPE ProCurve Management and Configuration
Guide, "Configuring a loopback interface").  Configs the switch printed
have both::

    interface loopback 0
       ip address 10.0.0.9
       exit

The parser took one word after ``interface``, so it read nothing of such a
stanza: the loopback and its addresses were gone, with no row to say so, in
jobs that said ``completed``.  The renderer wrote ``interface loopback1``
and ``ip address 10.0.0.9/32``.  And the formatter wrote a source's
Loopback0 as ``loopback1``, on a claim that loopback 0 is reserved; HPE
gives up to 32 IPv4 addresses "on lo0 to lo7", and printed configs give
loopback 0 an address, so Loopback0 and Loopback1 were one loopback.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
)
from netcanon.migration.canonical.port_names import PortIdentity
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_AOSS = ArubaAOSSCodec()


def _config(*stanza: str, indent: str = "   ") -> str:
    """A small AOS-S config with *stanza* in it, every body line indented
    by *indent*."""
    body = [
        'hostname "sw"',
        *stanza,
        "vlan 1",
        '   name "DEFAULT_VLAN"',
        "   untagged 1-4",
        "   ip address 10.0.0.1 255.255.255.0",
        "   exit",
    ]
    return "\n".join(
        indent + line.strip() if line.startswith("   ") else line for line in body
    ) + "\n"


def _addresses(tree: CanonicalIntent, name: str) -> list[str]:
    iface = next(i for i in tree.interfaces if i.name == name)
    return [
        *(f"{a.ip}/{a.prefix_length}" for a in iface.ipv4_addresses),
        *(f"{a.ip}/{a.prefix_length}" for a in iface.ipv6_addresses),
    ]


class TestTheParserReadsALoopback:
    @pytest.mark.parametrize("header", [
        "interface loopback 1",
        "interface loopback1",
        "interface Loopback 1",
        "interface loopback  1  ",
    ])
    def test_each_form_of_the_header(self, header: str) -> None:
        tree = _AOSS.parse(_config(header, "   ip address 10.9.9.1", "   exit"))
        assert _addresses(tree, "loopback1") == ["10.9.9.1/32"]
        iface = next(i for i in tree.interfaces if i.name == "loopback1")
        assert iface.interface_type == "ianaift:softwareLoopback"

    @pytest.mark.parametrize(("line", "read"), [
        ("ip address 10.9.9.1", "10.9.9.1/32"),
        ("ip address 10.9.9.1/32", "10.9.9.1/32"),
        ("ip address 10.9.9.1 255.255.255.255", "10.9.9.1/32"),
        ("ip address 10.9.9.1/24", "10.9.9.1/24"),
        ("ipv6 address 2001:db8::9", "2001:db8::9/128"),
        ("ipv6 address 2001:db8::9/128", "2001:db8::9/128"),
    ])
    def test_each_form_of_an_address(self, line: str, read: str) -> None:
        tree = _AOSS.parse(_config("interface loopback 1", f"   {line}", "   exit"))
        assert _addresses(tree, "loopback1") == [read]

    def test_loopback_0_and_its_neighbours(self) -> None:
        """Loopback 0 takes an address of its own, and every address of a
        stanza is read: 32 of them are allowed."""
        tree = _AOSS.parse(_config(
            "interface loopback 0",
            "   ip address 10.9.9.0",
            "   ip address 10.9.9.10",
            "   ip ospf 10.9.9.0 area backbone",
            "   exit",
            "interface loopback 7",
            "   ip address 10.9.9.7",
            "   exit",
        ))
        assert _addresses(tree, "loopback0") == ["10.9.9.0/32", "10.9.9.10/32"]
        assert _addresses(tree, "loopback7") == ["10.9.9.7/32"]
        # The stanza after them is read whole.
        assert _addresses(tree, "Vlan1") == ["10.0.0.1/24"]

    def test_a_flat_stanza_is_read_the_same(self) -> None:
        """A config whose indentation was lost reads as the printed one
        does (the AOS-S stanza ends at its ``exit``)."""
        stanza = ("interface loopback 1", "   ip address 10.9.9.1", "   ipv6 address 2001:db8::9", "   exit")
        printed = _AOSS.parse(_config(*stanza))
        flat = _AOSS.parse(_config(*stanza, indent=""))
        assert _addresses(flat, "loopback1") == _addresses(printed, "loopback1") == [
            "10.9.9.1/32", "2001:db8::9/128",
        ]

    def test_a_bare_address_is_a_host_address_only_on_a_loopback(self) -> None:
        """A port is given its mask; a bare address there is not read as
        a host address."""
        tree = _AOSS.parse(_config("interface 3", "   ip address 10.3.3.3", "   exit"))
        iface = next(i for i in tree.interfaces if i.name == "3")
        assert iface.ipv4_addresses == []


class TestTheRendererWritesTheDevicesForm:
    def _tree(self, *addresses: CanonicalIPv4Address | CanonicalIPv6Address) -> CanonicalIntent:
        return CanonicalIntent(interfaces=[CanonicalInterface(
            name="loopback1",
            ipv4_addresses=[a for a in addresses if isinstance(a, CanonicalIPv4Address)],
            ipv6_addresses=[a for a in addresses if isinstance(a, CanonicalIPv6Address)],
        )])

    def test_a_host_address(self) -> None:
        out = _AOSS.render(self._tree(
            CanonicalIPv4Address(ip="10.9.9.1", prefix_length=32),
            CanonicalIPv6Address(ip="2001:db8::9", prefix_length=128, scope="global"),
        ))
        assert "interface loopback 1\n   ip address 10.9.9.1\n   ipv6 address 2001:db8::9\n   exit\n" in out
        assert "review" not in out
        back = _AOSS.parse(out)
        assert _addresses(back, "loopback1") == ["10.9.9.1/32", "2001:db8::9/128"]

    def test_an_address_with_a_shorter_prefix_is_said(self) -> None:
        tree = self._tree(CanonicalIPv4Address(ip="10.9.9.1", prefix_length=24))
        out = _AOSS.render(tree)
        assert (
            "interface loopback 1\n"
            "   ; review: 10.9.9.1/24 is written as a host address: an AOS-S loopback takes no mask\n"
            "   ip address 10.9.9.1\n"
        ) in out
        assert _AOSS.render_warnings(tree) == [
            "loopback1: 10.9.9.1/24 is written as a host address: an AOS-S loopback takes no mask",
        ]

    def test_a_disabled_loopback_is_refused_and_said(self) -> None:
        """No form is known for an AOS-S loopback that is down: written,
        it would be up, its address with it."""
        tree = self._tree(CanonicalIPv4Address(ip="10.9.9.1", prefix_length=24))
        tree.interfaces[0].enabled = False
        out = _AOSS.render(tree)
        why = (
            "interface loopback1 is disabled, and no AOS-S form is known "
            "for a loopback that is down; not written"
        )
        assert f"; review: {why}" in out.splitlines()
        assert "10.9.9.1" not in out
        assert not [line for line in out.splitlines() if line.startswith("interface loopback")]
        assert _AOSS.render_warnings(tree) == [why]

    @pytest.mark.parametrize("name", ["Loopback0", "loopback0", "loopback 0"])
    def test_each_name_a_tree_gives_a_loopback(self, name: str) -> None:
        """IOS-XE, EOS and IOS XR name it ``Loopback0``, NX-OS
        ``loopback0``, AOS-CX ``loopback 0``: each is ``interface
        loopback 0``."""
        out = _AOSS.render(CanonicalIntent(interfaces=[CanonicalInterface(
            name=name, ipv4_addresses=[CanonicalIPv4Address(ip="10.9.9.0", prefix_length=32)],
        )]))
        assert "interface loopback 0\n   ip address 10.9.9.0\n   exit\n" in out
        assert _addresses(_AOSS.parse(out), "loopback0") == ["10.9.9.0/32"]


class TestTheNumberIsKept:
    @pytest.mark.parametrize("index", range(8))
    def test_loopbacks_0_to_7(self, index: int) -> None:
        identity = PortIdentity(kind="loopback", index=index, original=f"Loopback{index}")
        assert _AOSS.format_port_identity(identity) == f"loopback{index}"

    def test_none_above_7(self) -> None:
        identity = PortIdentity(kind="loopback", index=8, original="Loopback8")
        assert _AOSS.format_port_identity(identity) is None

    def test_the_parsers_name_is_a_loopback(self) -> None:
        identity = _AOSS.classify_port_name("loopback3")
        assert (identity.kind, identity.index) == ("loopback", 3)


_IOSXE = """\
hostname r1
interface Loopback0
 ip address 10.9.9.0 255.255.255.255
interface Loopback1
 ip address 10.9.9.1 255.255.255.255
interface GigabitEthernet1/0/1
 no switchport
 ip address 10.1.1.1 255.255.255.0
end
"""


def test_two_loopbacks_stay_two() -> None:
    """Loopback0 and Loopback1 of a Catalyst are loopbacks 0 and 1."""
    job = run_plan_with_checked_names(get_codec("cisco_iosxe_cli"), _AOSS, _IOSXE, port_rename_map={})
    assert job.status.value == "completed"
    out = job.rendered or ""
    assert "interface loopback 0\n   ip address 10.9.9.0\n   exit\n" in out
    assert "interface loopback 1\n   ip address 10.9.9.1\n   exit\n" in out
    back = _AOSS.parse(out)
    assert _addresses(back, "loopback0") == ["10.9.9.0/32"]
    assert _addresses(back, "loopback1") == ["10.9.9.1/32"]


_LOOPBACKS = _config(
    "interface loopback 0",
    "   ip address 10.9.9.0",
    "   exit",
    "interface loopback 1",
    "   ip address 10.9.9.1",
    "   exit",
)

#: Targets that have one loopback where AOS-S has eight: the second is
#: dropped and said (an unresolved name, which holds the job).
_ONE_LOOPBACK = {"juniper_junos"}


@pytest.mark.parametrize("target", sorted(list_public_codecs()))
def test_every_target_has_the_loopbacks(target: str) -> None:
    """Each address of an AOS-S loopback is in the output, read back with
    the target's own parser, on an interface of its own."""
    tgt = get_codec(target)
    job = run_plan_with_checked_names(_AOSS, tgt, _LOOPBACKS, port_rename_map={})
    back = tgt.parse(job.rendered or "")
    holder = {
        a.ip: i.name
        for i in back.interfaces
        for a in i.ipv4_addresses
        if a.ip.startswith("10.9.9.")
    }
    if target in _ONE_LOOPBACK:
        assert list(holder) == ["10.9.9.0"]
        assert job.unresolved_ports == ["loopback1"]
        return
    assert set(holder) == {"10.9.9.0", "10.9.9.1"}
    assert holder["10.9.9.0"] != holder["10.9.9.1"]
