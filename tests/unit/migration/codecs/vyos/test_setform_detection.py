"""A VyOS set-form paste is detected as VyOS, whichever VyOS interface it names.

VyOS names an interface by its type and a number (vyos-1x,
``interface-definitions``: ``bond[0-9]+``, ``tun[0-9]+``, ``wg[0-9]+``;
an ethernet port ``(eth|lan)[0-9]+`` or ``(eno|ens|enp|enx).+``), and
its loopback ``lo``.  Up to 0.7.7 the VyOS probe's marker for such a
name ended in a word boundary straight after the type's prefix
(``eth``), which stands before no ``eth0``: of all VyOS's names it held
for ``lo`` alone.  And the Junos probe counted any name that BEGINS
``et``, ``ge`` or ``lo`` as a Junos port, so ``ethernet eth0``,
``geneve gnv0`` and ``loopback lo`` were Junos ports to it.  A paste of
VyOS interfaces, a BGP block and a host name was offered as Junos, and
read as Junos it is one interface called ``ethernet``.

Each check here is read beside a text it has to reject: a Junos paste
is still Junos, and a VyOS probe that ignores its interface lines
loses the paste again.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.juniper_junos.codec import JunosCodec
from netcanon.migration.codecs.vyos.codec import VyOSCodec
from netcanon.services.migration_detect import detect_codec

pytestmark = pytest.mark.unit

#: Every interface type VyOS names by a prefix and a number, an
#: ethernet port by each of the other names vyos-1x takes, and the
#: loopback.
VYOS_INTERFACES = [
    "ethernet eth0",
    "ethernet eth12",
    "ethernet lan0",
    "ethernet eno1",
    "ethernet ens192",
    "ethernet enp0s3",
    "ethernet enx0a1b2c3d4e5f",
    "bonding bond0",
    "dummy dum0",
    "vxlan vxlan0",
    "bridge br0",
    "wireguard wg0",
    "tunnel tun0",
    "pppoe pppoe0",
    "geneve gnv0",
    "loopback lo",
]

#: Junos ports, one of each name shape the Junos probe counts.
JUNOS_PORTS = [
    "ge-0/0/0 unit 0",
    "xe-0/0/1 unit 0",
    "et-0/0/2 unit 0",
    "fe-0/0/3 unit 0",
    "em0 unit 0",
    "me0 unit 0",
    "fxp0 unit 0",
    "ae0 unit 0",
    "lo0 unit 0",
    "irb unit 100",
]

#: Two lines both platforms write.  To the Junos probe they are two of
#: its markers, so a third makes a text Junos.
_SHARED = (
    "set protocols bgp system-as 65001\n"
    "set system host-name r1\n"
)


def _vyos_paste(kind: str, rest: str = _SHARED) -> str:
    return f"set interfaces {kind} address '192.0.2.1/24'\n" + rest


def _junos_paste(port: str) -> str:
    return (
        f"set interfaces {port} family inet address 192.0.2.1/24\n"
        "set protocols bgp group G type external\n"
        "set system host-name r1\n"
    )


def _top(text: str) -> str | None:
    """The codec detection offers first, or None."""
    ranked = detect_codec(text)
    return ranked[0].codec if ranked else None


def _junos_counts_three(text: str) -> bool:
    """The Junos probe found three of its markers in *text*."""
    result = JunosCodec.probe(text)
    return result is not None and result[0] >= 88


class TestAVyOSPaste:
    @pytest.mark.parametrize("kind", VYOS_INTERFACES)
    def test_with_bgp_and_a_host_name(self, kind: str) -> None:
        assert _top(_vyos_paste(kind)) == "vyos"

    @pytest.mark.parametrize("kind", VYOS_INTERFACES)
    def test_its_interfaces_alone(self, kind: str) -> None:
        assert _top(_vyos_paste(kind, rest="")) == "vyos"

    @pytest.mark.parametrize("kind", VYOS_INTERFACES)
    def test_with_a_firewall_both_platforms_write(self, kind: str) -> None:
        text = _vyos_paste(
            kind, rest="set firewall name F rule 10 action drop\n" + _SHARED,
        )
        assert _top(text) == "vyos"

    @pytest.mark.parametrize("kind", VYOS_INTERFACES)
    def test_the_junos_probe_takes_no_vyos_name_for_a_port(self, kind: str) -> None:
        assert not _junos_counts_three(_vyos_paste(kind))

    @pytest.mark.parametrize(
        "kind", ["ethernet eth", "ethernet ethX", "bonding bond", "tunnel tunnel1"],
    )
    def test_a_name_vyos_does_not_take_is_no_marker(self, kind: str) -> None:
        # A type with no number, or with another word, is not a VyOS
        # interface, and on its own claims nothing.
        assert VyOSCodec.probe(_vyos_paste(kind, rest="")) is None


class TestAJunosPaste:
    @pytest.mark.parametrize("port", JUNOS_PORTS)
    def test_is_still_junos(self, port: str) -> None:
        text = _junos_paste(port)
        assert _top(text) == "juniper_junos"
        assert _junos_counts_three(text)
        assert VyOSCodec.probe(text) is None


class TestTheChecksCanFail:
    @pytest.mark.parametrize("kind", ["ethernet eth0", "bonding bond0", "geneve gnv0"])
    def test_a_vyos_probe_that_reads_no_interface_loses_the_paste(
        self, kind: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The marker as it was held for no numbered name; a probe that
        # does not see the interface lines is that probe.
        setform = VyOSCodec._probe_setform.__func__

        def without_interfaces(cls: type[VyOSCodec], raw: str) -> tuple[int, str] | None:
            return setform(cls, re.sub(r"(?m)^set interfaces .*$", "", raw))

        monkeypatch.setattr(VyOSCodec, "_probe_setform", classmethod(without_interfaces))
        assert _top(_vyos_paste(kind)) != "vyos"

    def test_the_junos_count_sees_a_junos_port(self) -> None:
        # The same two shared lines and a Junos port are three markers.
        assert _junos_counts_three("set interfaces ge-0/0/0 unit 0\n" + _SHARED)
