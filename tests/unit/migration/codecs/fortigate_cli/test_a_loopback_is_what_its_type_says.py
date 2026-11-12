"""A FortiOS loopback or tunnel is what its ``set type`` says, whatever its name.

FortiOS names a loopback or a tunnel freely: Fortinet's own loopback
example is ``Lo-BGP-RID``, and an IPsec tunnel interface takes the name
of its phase 1.  The parser typed every such interface by the shape of
its name, so each was a PORT in the tree, and the renderer wrote a
loopback or a tunnel with no ``set type`` -- a new interface that states
no type is not a loopback on a FortiGate.  So:

* between two FortiOS configs a loopback or a tunnel came back with no
  type;
* a loopback an operator called ``port1.5`` went after ``port1`` as its
  unit 5, onto whatever port ``port1`` became;
* onto RouterOS a loopback or a tunnel was looked up as an Ethernet
  port (``set [ find default-name=... ]``, a lookup no device matches),
  and onto IOS-XE NETCONF written ``ianaift:ethernetCsmacd``;
* a loopback or a tunnel of ANOTHER vendor was written onto FortiOS
  with no ``set type`` either.

What each line means is typed here by hand, and each output is read as
TEXT, so that no expectation is the parser's or the renderer's own
answer.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs import get_codec
from netcanon.migration.codecs.registry import list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

#: A loopback and a tunnel under names of the operator's own, one
#: loopback named as a unit of a port the config has, and the three
#: tunnels FortiOS adds of itself to a VDOM.
_SOURCE = """config system interface
    edit "port1"
        set vdom "root"
        set ip 192.0.2.1 255.255.255.0
        set type physical
    next
    edit "wan1"
        set vdom "root"
        set ip 203.0.113.2 255.255.255.252
        set type physical
    next
    edit "Lo-BGP-RID"
        set vdom "root"
        set ip 10.255.255.1 255.255.255.255
        set allowaccess ping
        set type loopback
    next
    edit "port1.5"
        set vdom "root"
        set ip 10.255.255.5 255.255.255.255
        set type loopback
    next
    edit "VPN-HQ"
        set vdom "root"
        set ip 169.254.1.1 255.255.255.255
        set remote-ip 169.254.1.2 255.255.255.252
        set type tunnel
        set interface "wan1"
    next
    edit "ssl.root"
        set vdom "root"
        set type tunnel
        set alias "SSL VPN interface"
    next
    edit "naf.root"
        set vdom "root"
        set type tunnel
    next
    edit "l2t.root"
        set vdom "root"
        set type tunnel
    next
end
"""

#: What each interface IS, from its ``set type`` line.
_WHAT_EACH_IS = {
    "port1": "ianaift:ethernetCsmacd",
    "wan1": "ianaift:ethernetCsmacd",
    "Lo-BGP-RID": "ianaift:softwareLoopback",
    "port1.5": "ianaift:softwareLoopback",
    "VPN-HQ": "ianaift:tunnel",
    "ssl.root": "ianaift:tunnel",
    "naf.root": "ianaift:tunnel",
    "l2t.root": "ianaift:tunnel",
}

#: The ``set type`` FortiOS prints for each loopback and tunnel.
_TYPE_LINE = {
    "Lo-BGP-RID": "loopback",
    "port1.5": "loopback",
    "VPN-HQ": "tunnel",
    "ssl.root": "tunnel",
    "naf.root": "tunnel",
    "l2t.root": "tunnel",
}

#: The tunnels FortiOS makes from an entry of another table, which an
#: output of this tree does not have.  ``ssl.root``, ``naf.root`` and
#: ``l2t.root`` FortiOS adds of itself.
_MADE_FROM_AN_ENTRY = {"VPN-HQ"}

_REVIEW = "# review: a tunnel interface"


def _edits(text: str) -> dict[str, list[str]]:
    """The lines of each ``edit`` block of ``config system interface``
    in a FortiOS text, by the name the block edits."""
    blocks: dict[str, list[str]] = {}
    inside = False
    current: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "config system interface":
            inside = True
            continue
        if not inside:
            continue
        if stripped == "end" and not line.startswith(" "):
            break
        m = re.fullmatch(r'edit "([^"]*)"', stripped)
        if m:
            current = blocks.setdefault(m.group(1), [])
            continue
        if stripped == "next":
            current = None
            continue
        if current is not None:
            current.append(stripped)
    return blocks


def _job(target: str, text: str = _SOURCE, source: str = "fortigate_cli"):
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )


class TestTheParserReadsTheType:
    def test_each_interface_is_what_its_type_says(self) -> None:
        tree = get_codec("fortigate_cli").parse(_SOURCE)
        assert {i.name: i.interface_type for i in tree.interfaces} == _WHAT_EACH_IS


class TestFortiOSWritesTheType:
    def test_between_two_fortios_configs(self) -> None:
        job = _job("fortigate_cli")
        edits = _edits(job.rendered)
        for name, kind in _TYPE_LINE.items():
            assert f"set type {kind}" in edits[name], name
            assert (_REVIEW in " ".join(edits[name])) is (name in _MADE_FROM_AN_ENTRY), name
        for name in ("port1", "wan1"):
            assert not any(line.startswith("set type") for line in edits[name]), name

    def test_the_parser_reads_back_what_was_written(self) -> None:
        job = _job("fortigate_cli")
        tree = get_codec("fortigate_cli").parse(job.rendered)
        assert {i.name: i.interface_type for i in tree.interfaces} == _WHAT_EACH_IS

    @pytest.mark.parametrize(("source", "text", "loopback", "tunnel"), [
        (
            "cisco_iosxe_cli",
            "hostname r1\n"
            "interface Loopback0\n ip address 10.255.255.1 255.255.255.255\n"
            "interface Tunnel0\n ip address 172.16.0.1 255.255.255.252\n"
            " tunnel source GigabitEthernet0/1\n tunnel destination 198.51.100.9\n"
            "interface GigabitEthernet0/1\n ip address 203.0.113.2 255.255.255.252\n",
            "10.255.255.1 255.255.255.255",
            "172.16.0.1 255.255.255.252",
        ),
        (
            "juniper_junos",
            "set system host-name r1\n"
            "set interfaces lo0 unit 0 family inet address 10.255.255.1/32\n"
            "set interfaces st0 unit 1 family inet address 172.16.1.1/30\n",
            "10.255.255.1 255.255.255.255",
            "172.16.1.1 255.255.255.252",
        ),
        (
            # The VyOS parser gives a loopback no type: the name it is
            # written under says what it is.
            "vyos",
            "set system host-name r1\n"
            "set interfaces loopback lo address 10.255.255.1/32\n",
            "10.255.255.1 255.255.255.255",
            None,
        ),
    ], ids=["cisco_iosxe_cli", "juniper_junos", "vyos"])
    def test_from_another_vendor(self, source, text, loopback, tunnel) -> None:
        job = _job("fortigate_cli", text, source)
        edits = _edits(job.rendered)
        by_address = {
            line.split(" ", 2)[2]: (name, lines)
            for name, lines in edits.items()
            for line in lines if line.startswith("set ip ")
        }
        for address, kind in ((loopback, "loopback"), (tunnel, "tunnel")):
            if address is None:
                continue
            name, lines = by_address[address]
            # Stated, and ahead of the address: an interface whose edit
            # states no type is not a loopback or a tunnel.
            assert lines.index(f"set type {kind}") < lines.index(f"set ip {address}"), name
            assert (_REVIEW in " ".join(lines)) is (kind == "tunnel"), name


class TestALoopbackIsNotAUnit:
    @pytest.mark.parametrize("target", sorted(set(list_public_codecs()) - {"fortigate_cli"}))
    def test_port1_5_does_not_go_after_port1(self, target: str) -> None:
        job = _job(target)
        port1 = job.port_renames["port1"]
        assert job.port_renames.get("port1.5") != f"{port1}.5"
        # As a name of its own: "1.5" is in a release number too.
        assert not re.search(
            rf"(?<![\w./:-]){re.escape(port1)}\.5(?![\w./:-])", job.rendered,
        )


class TestWhereTheTargetStatesWhatItIs:
    def test_routeros_looks_up_no_ethernet_port_for_them(self) -> None:
        job = _job("mikrotik_routeros")
        for name in ("Lo-BGP-RID", "VPN-HQ"):
            assert f"default-name={name}" not in job.rendered, name
        sections: dict[str, list[str]] = {}
        current: list[str] = []
        for line in job.rendered.splitlines():
            if line.startswith("/"):
                current = sections.setdefault(line.strip(), [])
            elif line.startswith("add "):
                current.append(line)
        # RouterOS has no loopback type; a bridge with no ports is its
        # loopback.  A tunnel is declared in its own section.
        assert any("name=Lo-BGP-RID" in line for line in sections["/interface bridge"])
        assert any("name=VPN-HQ" in line for line in sections["/interface gre"])

    def test_iosxe_netconf_types_them(self) -> None:
        job = _job("cisco_iosxe")
        for name, kind in (("Lo-BGP-RID", "softwareLoopback"), ("VPN-HQ", "tunnel")):
            # The <config> of the interface of that name, and its type.
            m = re.search(
                rf"<config>\s*<name>{re.escape(name)}</name>(.*?)</config>",
                job.rendered, re.DOTALL,
            )
            assert m is not None, name
            assert f"<type>ianaift:{kind}</type>" in m.group(1), name
