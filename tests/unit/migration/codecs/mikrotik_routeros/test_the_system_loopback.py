"""``lo`` is the loopback RouterOS 7.14 and later has of its own.

RouterOS 7.14beta: "system - expose "lo" interface".  Every such router
has it, it cannot be removed, and no interface can be added under its
name -- so ``/interface bridge add name=lo``, the line the renderer
wrote for every loopback 0 up to 0.7.7, is a line a router of 7.14 or
later refuses.  RouterOS 6, which the codec also writes, shows no
``lo``.  So:

* the parser reads an address put on ``lo`` -- an export has no line
  for ``lo`` itself -- as an address of a loopback;
* the renderer writes no line for ``lo``, and the addresses on it as
  they are.  What no line says of it (a description; that it is
  disabled) it says in a review line and a warning, and the addresses
  of a ``lo`` the source holds disabled are left out rather than put
  into service;
* a loopback of every other vendor is written ``loopback<N>``, the
  empty bridge MikroTik documents for a loopback, which loads on 6 and
  on 7: the port translator writes ``lo`` only for the ``lo`` of a
  RouterOS config;
* a bridge a config names ``lo`` (a RouterOS 6 config can have one) is
  a bridge, and is written as one.

Sources:

* https://forum.mikrotik.com/t/v7-14beta-testing-is-released/172080?page=2
  (the 7.14beta change log)
* https://forum.mikrotik.com/t/lo-interface-loopback/174549
* https://forum.mikrotik.com/t/the-loopback-interface-was-deleted-by-remove-button/183449
* https://wiki.mikrotik.com/Creating_loopback_address_for_IPv6
  (the empty bridge)
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
from netcanon.migration.codecs.mikrotik_routeros.render import system_lo_notes
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

ROS = get_codec("mikrotik_routeros")

#: A RouterOS 7 export with addresses on its own ``lo``, which the
#: export has no line for, and on a port.
_ROS7_LO = (
    "# 2026-01-01 00:00:00 by RouterOS 7.18.2\n"
    "/interface ethernet\n"
    "set [ find default-name=ether1 ] comment=uplink\n"
    "/ip address\n"
    "add address=192.0.2.1 interface=lo network=192.0.2.1\n"
    "add address=198.51.100.1/24 interface=ether1 network=198.51.100.0\n"
    "/ipv6 address\n"
    "add address=2001:db8::1/128 interface=lo\n"
)

#: A RouterOS 6 export with a bridge it names ``lo``.
_ROS6_BRIDGE_LO = (
    "# jan/01/2026 00:00:00 by RouterOS 6.49.10\n"
    "/interface bridge\n"
    "add name=lo\n"
    "/ip address\n"
    "add address=192.0.2.1/32 interface=lo network=192.0.2.1\n"
)

#: A loopback 0 with an address, in the grammar of each source written
#: by hand here.  Every public codec's own name for a loopback is
#: covered by :meth:`TestThePortTranslator.test_no_other_vendors_loopback_is_lo`.
_LOOPBACK_ZERO = {
    "cisco_iosxe_cli": (
        "hostname r1\ninterface Loopback0\n ip address 192.0.2.1 255.255.255.255\nend\n"
    ),
    "cisco_nxos": "hostname r1\ninterface loopback0\n  ip address 192.0.2.1/32\n",
    "arista_eos": "hostname r1\n!\ninterface Loopback0\n   ip address 192.0.2.1/32\n!\nend\n",
    "cisco_iosxr": (
        "hostname r1\ninterface Loopback0\n ipv4 address 192.0.2.1 255.255.255.255\n!\nend\n"
    ),
    "juniper_junos": (
        "set system host-name r1\n"
        "set interfaces lo0 unit 0 family inet address 192.0.2.1/32\n"
    ),
    "vyos": "set system host-name r1\nset interfaces loopback lo address 192.0.2.1/32\n",
    "aruba_aoscx": "hostname r1\ninterface loopback 0\n    ip address 192.0.2.1/32\n",
    "aruba_aoss": "hostname \"r1\"\ninterface loopback 0\n   ip address 192.0.2.1\n   exit\n",
    "dell_os10": "hostname r1\n!\ninterface loopback0\n no shutdown\n ip address 192.0.2.1/32\n",
}


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()]


def _lo(**fields) -> CanonicalInterface:
    return CanonicalInterface(
        name="lo", interface_type="ianaift:softwareLoopback", **fields,
    )


class TestTheParser:
    def test_an_address_on_lo_is_a_loopbacks(self) -> None:
        tree = ROS.parse(_ROS7_LO)
        (lo,) = [i for i in tree.interfaces if i.name == "lo"]
        assert lo.interface_type == "ianaift:softwareLoopback"
        assert [(a.ip, a.prefix_length) for a in lo.ipv4_addresses] == [("192.0.2.1", 32)]
        assert [(a.ip, a.prefix_length) for a in lo.ipv6_addresses] == [("2001:db8::1", 128)]

    def test_a_bridge_named_lo_is_a_bridge(self) -> None:
        (lo,) = [i for i in ROS.parse(_ROS6_BRIDGE_LO).interfaces if i.name == "lo"]
        assert lo.interface_type == "ianaift:bridge"


class TestTheRenderer:
    def test_lo_is_written_no_line(self) -> None:
        out = ROS.render(ROS.parse(_ROS7_LO))
        lines = _lines(out)
        assert not [line for line in lines if "name=lo" in line.split()]
        assert "/interface bridge" not in lines
        assert "add address=192.0.2.1/32 interface=lo" in lines
        assert "add address=2001:db8::1/128 interface=lo" in lines
        assert not [line for line in lines if line.startswith("# review: lo ")]

    def test_and_reads_back_as_it_was(self) -> None:
        def shape(tree):
            return sorted(
                (i.name, i.interface_type,
                 tuple((a.ip, a.prefix_length) for a in i.ipv4_addresses),
                 tuple((a.ip, a.prefix_length) for a in i.ipv6_addresses))
                for i in tree.interfaces
            )

        tree = ROS.parse(_ROS7_LO)
        assert shape(ROS.parse(ROS.render(tree))) == shape(tree)

    def test_a_routeros_job_onto_routeros_keeps_it(self) -> None:
        job = run_plan_with_checked_names(ROS, ROS, _ROS7_LO, port_rename_map={})
        assert job.status.value == "completed"
        assert "lo" not in (job.port_renames or {})
        lines = _lines(job.rendered or "")
        assert "add address=192.0.2.1/32 interface=lo" in lines
        assert not [line for line in lines if "name=lo" in line.split()]

    def test_a_bridge_named_lo_is_written_as_one(self) -> None:
        lines = _lines(ROS.render(ROS.parse(_ROS6_BRIDGE_LO)))
        bridge = lines.index("/interface bridge")
        assert lines[bridge + 1] == "add name=lo"
        assert "add address=192.0.2.1/32 interface=lo" in lines

    def test_a_description_is_said_and_not_written(self) -> None:
        tree = CanonicalIntent(interfaces=[_lo(
            description="router id",
            ipv4_addresses=[CanonicalIPv4Address(ip="192.0.2.1", prefix_length=32)],
        )])
        out = ROS.render(tree)
        assert "router id" not in out
        assert (
            "# review: lo is the loopback RouterOS 7.14 and later has of its "
            "own, and is written no line; its description in the source is "
            "not written"
        ) in _lines(out)
        assert "add address=192.0.2.1/32 interface=lo" in _lines(out)
        assert ROS.render_warnings(tree) == [
            "lo is the loopback RouterOS 7.14 and later has of its own, and "
            "is written no line, so its description in the source is not "
            "written; a review line in the output says so."
        ]

    def test_a_disabled_lo_has_its_addresses_left_out(self) -> None:
        tree = CanonicalIntent(interfaces=[
            _lo(
                enabled=False,
                ipv4_addresses=[CanonicalIPv4Address(ip="192.0.2.1", prefix_length=32)],
                ipv6_addresses=[CanonicalIPv6Address(ip="2001:db8::1", prefix_length=128)],
            ),
            CanonicalInterface(
                name="ether1", interface_type="ianaift:ethernetCsmacd",
                ipv4_addresses=[CanonicalIPv4Address(ip="198.51.100.1", prefix_length=24)],
            ),
        ])
        out = ROS.render(tree)
        assert "192.0.2.1" not in out
        assert "2001:db8::1" not in out
        assert "/ipv6 address" not in out
        assert "add address=198.51.100.1/24 interface=ether1" in _lines(out)
        assert (
            "# review: lo is disabled in the source, and no line disables "
            "the loopback RouterOS 7.14 and later has of its own; its "
            "addresses are left out"
        ) in _lines(out)
        assert ROS.render_warnings(tree) == [
            "lo is disabled in the source, and no line disables the loopback "
            "RouterOS 7.14 and later has of its own; its addresses are left "
            "out; a review line in the output says so."
        ]

    def test_a_disabled_lo_with_no_address(self) -> None:
        tree = CanonicalIntent(interfaces=[_lo(enabled=False)])
        ((review, warning),) = system_lo_notes(tree)
        assert "left out" not in review
        assert "left out" not in warning
        assert review in _lines(ROS.render(tree))

    def test_a_bridge_named_lo_is_not_noted(self) -> None:
        tree = CanonicalIntent(interfaces=[CanonicalInterface(
            name="lo", interface_type="ianaift:bridge", description="x",
            enabled=False,
        )])
        assert system_lo_notes(tree) == []
        lines = _lines(ROS.render(tree))
        assert 'add comment="x" name=lo disabled=yes' in lines


class TestThePortTranslator:
    def test_lo_is_routeros_own(self) -> None:
        assert ROS.format_port_identity(ROS.classify_port_name("lo")) == "lo"

    @pytest.mark.parametrize("name", ["LO", "Lo", "loopback0"])
    def test_no_other_name_is(self, name: str) -> None:
        assert ROS.format_port_identity(ROS.classify_port_name(name)) == "loopback0"

    @pytest.mark.parametrize("codec_name", list_public_codecs())
    def test_no_other_vendors_loopback_is_lo(self, codec_name: str) -> None:
        """Each codec's own name for loopback 0, read by that codec,
        is written ``loopback0``: a loopback of any other vendor is
        one RouterOS 7.14 and later has no line for, under ``lo``."""
        codec = get_codec(codec_name)
        own = codec.format_port_identity(PortIdentity(kind="loopback", index=0))
        assert own
        assert ROS.format_port_identity(codec.classify_port_name(own)) == "loopback0"

    @pytest.mark.parametrize("source_name", sorted(_LOOPBACK_ZERO))
    def test_onto_routeros_it_is_an_empty_bridge(self, source_name: str) -> None:
        job = run_plan_with_checked_names(
            get_codec(source_name), ROS, _LOOPBACK_ZERO[source_name], port_rename_map={},
        )
        lines = _lines(job.rendered or "")
        bridge = lines.index("/interface bridge")
        assert lines[bridge + 1] == "add name=loopback0"
        assert "add address=192.0.2.1/32 interface=loopback0" in lines
        assert not [line for line in lines if {"name=lo", "interface=lo"} & set(line.split())]
        assert job.status.value == "completed"

    def test_routeros_lo_onto_another_vendor(self) -> None:
        job = run_plan_with_checked_names(
            ROS, get_codec("arista_eos"), _ROS7_LO, port_rename_map={},
        )
        assert job.port_renames["lo"] == "Loopback0"
        assert "interface Loopback0" in _lines(job.rendered or "")
