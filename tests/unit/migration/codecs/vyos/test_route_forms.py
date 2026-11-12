"""Every VyOS static-route form is read, written, or left out and said.

VyOS writes a static route's next hop in several forms (vyos-1x,
``interface-definitions/include/static/static-route.xml.i``; VyOS,
"Static", 1.3, 1.4 and rolling):

* ``route <subnet> next-hop <address>``, with the ``interface`` the next
  hop names ("Gateway interface name");
* ``route <subnet> interface <interface>`` ("the next-hop interface for
  an interface-based ... static route"), and VyOS 1.3's
  ``interface-route <subnet> next-hop-interface <interface>``;
* ``route <subnet> blackhole`` and ``reject``, ``route <subnet>
  dhcp-interface <interface>`` ("derives its next-hop IP address from
  the specified DHCP-enabled interface"), and ``route6 ... segments``
  (SRv6);
* and ``protocols static table <N> route ...``, the routes of the table
  a policy route sends traffic to (VyOS, "Policy examples").

Up to 0.7.7 the parser read ``next-hop <address>`` alone: an interface
route, ``blackhole`` and the rest were dropped with nothing said, a
next hop's interface was dropped, and the renderer wrote a route out an
interface as ``next-hop <interface>``, which is not a next hop VyOS
takes.  Read here: what each form becomes in the tree, in both of
VyOS's grammars; the rows that say what is left out; the output VyOS
is given, read as TEXT by a reader of this module's own; and every
public codec's output, read as text, for the destinations left out.
"""

from __future__ import annotations

import functools
import re

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalStaticRoute,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_IFACES = """interfaces {
    ethernet eth0 {
        address 192.0.2.2/24
    }
    ethernet eth1 {
        address 198.51.100.2/24
    }
}
"""

#: Each form, in VyOS's curly-brace grammar, with the same in set form.
_CURLY = _IFACES + """protocols {
    static {
        route 10.1.0.0/16 {
            next-hop 192.0.2.1 {
                distance 5
            }
        }
        route 10.2.0.0/16 {
            interface eth1 {
                distance 7
            }
        }
        route 10.3.0.0/16 {
            blackhole {
                distance 9
                tag 4
            }
        }
        route 10.4.0.0/16 {
            reject {
            }
        }
        route 10.5.0.0/16 {
            dhcp-interface eth0
        }
        route 10.6.0.0/16 {
            next-hop 192.0.2.1 {
                interface eth0
            }
        }
        route 10.7.0.0/16 {
            interface eth1 {
                disable
            }
        }
        route 10.8.0.0/16 {
            blackhole { }
        }
        route6 2001:db8:9::/48 {
            next-hop 2001:db8::1 {
                segments 2001:db8:aa::1/2001:db8:aa::2
            }
        }
        route6 2001:db8:10::/48 {
            interface eth1 {
            }
        }
        interface-route 10.11.0.0/16 {
            next-hop-interface eth1 {
                distance 3
            }
        }
        interface-route6 2001:db8:12::/48 {
            next-hop-interface eth1 {
            }
        }
        table 10 {
            route 10.13.0.0/16 {
                next-hop 192.0.2.1 {
                }
            }
        }
    }
}
vrf {
    name blue {
        table 100
        protocols {
            static {
                route 10.20.0.0/16 {
                    interface eth1 {
                        vrf default
                    }
                }
                route 10.21.0.0/16 {
                    blackhole {
                    }
                }
            }
        }
    }
}
"""

_SET = """set interfaces ethernet eth0 address '192.0.2.2/24'
set interfaces ethernet eth1 address '198.51.100.2/24'
set protocols static route 10.1.0.0/16 next-hop 192.0.2.1 distance '5'
set protocols static route 10.2.0.0/16 interface eth1 distance '7'
set protocols static route 10.3.0.0/16 blackhole distance '9'
set protocols static route 10.3.0.0/16 blackhole tag '4'
set protocols static route 10.4.0.0/16 reject
set protocols static route 10.5.0.0/16 dhcp-interface 'eth0'
set protocols static route 10.6.0.0/16 next-hop 192.0.2.1 interface 'eth0'
set protocols static route 10.7.0.0/16 interface eth1 disable
set protocols static route 10.8.0.0/16 blackhole
set protocols static route6 2001:db8:9::/48 next-hop 2001:db8::1 segments '2001:db8:aa::1/2001:db8:aa::2'
set protocols static route6 2001:db8:10::/48 interface eth1
set protocols static interface-route 10.11.0.0/16 next-hop-interface eth1 distance '3'
set protocols static interface-route6 2001:db8:12::/48 next-hop-interface eth1
set protocols static table 10 route 10.13.0.0/16 next-hop '192.0.2.1'
set vrf name blue table '100'
set vrf name blue protocols static route 10.20.0.0/16 interface eth1 vrf 'default'
set vrf name blue protocols static route 10.21.0.0/16 blackhole
"""

#: What the tree holds: (destination, gateway, interface, metric, VRF).
_HELD = [
    ("10.1.0.0/16", "192.0.2.1", "", 5, ""),
    ("10.2.0.0/16", "", "eth1", 7, ""),
    ("10.3.0.0/16", "", "Null0", 9, ""),
    ("10.6.0.0/16", "192.0.2.1", "eth0", 0, ""),
    ("10.8.0.0/16", "", "Null0", 0, ""),
    ("2001:db8:10::/48", "", "eth1", 0, ""),
    ("10.11.0.0/16", "", "eth1", 3, ""),
    ("2001:db8:12::/48", "", "eth1", 0, ""),
    ("10.21.0.0/16", "", "Null0", 0, "blue"),
]

#: The destinations of the routes left out.
_LEFT_OUT = ["10.4.0.0", "10.5.0.0", "10.7.0.0", "2001:db8:9::", "10.13.0.0", "10.20.0.0"]

_ROWS = [
    "disabled: protocols static route 10.7.0.0/16 interface eth1 (a route the source holds "
    "disabled, so it installs nothing; not translated)",
    "protocols static: 1 route(s) whose next hop is in another VRF (next-hop <address> vrf "
    "<name>, or interface <name> vrf <name>): the tree has no form for a next hop outside the "
    "route's own VRF; not translated",
    "protocols static: 1 reject route(s): a reject route discards with an ICMP error to the "
    "sender, which the tree's one discard (a route to Null0) does not say; not translated",
    "protocols static: 1 route(s) through the gateway DHCP gives an interface (dhcp-interface "
    "<name>): the tree has no form for a gateway learned by DHCP; not translated",
    "protocols static: 1 route(s) of a routing table other than the main one (table <id>, "
    "which policy routing sends traffic to): the tree has no form for such a table; not "
    "translated",
    "protocols static: 1 route(s) through SRv6 segments (next-hop <address> segments <list>): "
    "the tree has no form for a segment list; not translated",
]


def _routes(text: str) -> list[tuple[str, str, str, int, str]]:
    tree = get_codec("vyos").parse(text)
    return [(r.destination, r.gateway, r.interface, r.metric, r.vrf) for r in tree.static_routes]


def _route_rows(text: str) -> list[str]:
    return [
        r for r in get_codec("vyos").parse(text).dropped_tier3_sections
        if r.startswith(("protocols static", "disabled: protocols static"))
    ]


@functools.cache
def _job(source: str, target: str, text: str) -> MigrationJob:
    return run_plan_with_checked_names(get_codec(source), get_codec(target), text, {})


_ROUTE_HEAD = re.compile(r"^[ \t]*(?:route6?|interface-route6?)[ \t]+(\S+)[ \t]*\{[ \t]*$")


def _hops(output: str) -> dict[str, list[str]]:
    """What a VyOS output writes under each route: the destination, and
    each line of the route's block with its indentation taken off.  Read
    from the text, not by the parser."""
    hops: dict[str, list[str]] = {}
    lines = output.splitlines()
    for i, line in enumerate(lines):
        m = _ROUTE_HEAD.match(line)
        if not m:
            continue
        depth, body = len(line) - len(line.lstrip()), []
        for inner in lines[i + 1:]:
            if len(inner) - len(inner.lstrip()) <= depth:
                break
            body.append(inner.strip())
        hops.setdefault(m.group(1), []).extend(body)
    return hops


def _left_out_in(output: str) -> list[str]:
    """The left-out destinations an output spells, read from the text."""
    return [d for d in _LEFT_OUT if d in output]


class TestTheParser:
    @pytest.mark.parametrize("text", [_CURLY, _SET], ids=["curly", "set"])
    def test_each_form_is_read(self, text: str) -> None:
        assert _routes(text) == _HELD

    @pytest.mark.parametrize("text", [_CURLY, _SET], ids=["curly", "set"])
    def test_the_rows_say_what_is_left_out(self, text: str) -> None:
        assert _route_rows(text) == _ROWS

    def test_only_the_route_held_disabled_is_a_statement_left_out(self) -> None:
        assert [is_left_out_row(r) for r in _route_rows(_CURLY)] == [True, *[False] * 5]

    def test_a_count_names_no_destination(self) -> None:
        for row in _route_rows(_CURLY)[1:]:
            assert not [d for d in [*_LEFT_OUT, "blue", "10.", "2001:"] if d in row], row

    @pytest.mark.parametrize("line", [
        "set protocols static route 10.4.0.0/16 reject",
        "set protocols static route 10.4.0.0/16 reject distance '5'",
        "set protocols static route 10.5.0.0/16 dhcp-interface 'eth0'",
        "set protocols static table 10 route 10.13.0.0/16 next-hop '192.0.2.1'",
        "set protocols static table 10 route 10.13.0.0/16 interface eth1",
        "set protocols static route6 2001:db8:9::/48 next-hop 2001:db8::1 segments 'a/b'",
        "set protocols static route6 2001:db8:9::/48 interface eth1 segments 'a/b'",
    ])
    def test_each_form_alone_is_left_out_with_one_row(self, line: str) -> None:
        text = _SET.splitlines()[0] + "\n" + line + "\n"
        assert _routes(text) == []
        assert len(_route_rows(text)) == 1

    def test_a_route_written_twice_is_counted_once(self) -> None:
        """Two blocks of one route (the set form merges two lines of one
        path before the walker sees them; the brace form does not)."""
        block = "        route 10.4.0.0/16 {\n            reject {\n            }\n        }\n"
        text = _IFACES + "protocols {\n    static {\n" + block + block + "    }\n}\n"
        assert _route_rows(text) == [_ROWS[2]]

    def test_a_vrf_of_its_own_and_a_table_of_a_vrf_are_not_this(self) -> None:
        """``vrf name <X> table <N>`` is the VRF's table, not a route's."""
        tree = get_codec("vyos").parse(_SET)
        assert [ri.name for ri in tree.routing_instances] == ["blue"]


class TestTheRenderer:
    def _out(self, routes: list[CanonicalStaticRoute]) -> str:
        tree = CanonicalIntent(
            hostname="r1",
            interfaces=[CanonicalInterface(
                name="eth1", ipv4_addresses=[CanonicalIPv4Address(ip="198.51.100.2", prefix_length=24)])],
            static_routes=routes,
        )
        return get_codec("vyos").render(tree)

    def test_a_route_out_an_interface_is_an_interface_route(self) -> None:
        out = self._out([CanonicalStaticRoute(destination="10.2.0.0/16", interface="eth1", metric=7)])
        assert _hops(out) == {"10.2.0.0/16": ["interface eth1 {", "distance 7", "}"]}

    def test_a_route_to_null0_is_blackhole(self) -> None:
        out = self._out([CanonicalStaticRoute(destination="10.3.0.0/16", interface="Null0", metric=9)])
        assert _hops(out) == {"10.3.0.0/16": ["blackhole {", "distance 9", "}"]}

    def test_a_gateway_keeps_its_interface(self) -> None:
        out = self._out([CanonicalStaticRoute(destination="10.6.0.0/16", gateway="192.0.2.1", interface="eth1")])
        assert _hops(out) == {"10.6.0.0/16": ["next-hop 192.0.2.1 {", "interface eth1", "}"]}

    def test_a_gateway_that_is_a_name_is_an_interface(self) -> None:
        out = self._out([CanonicalStaticRoute(destination="10.2.0.0/16", gateway="eth1")])
        assert _hops(out) == {"10.2.0.0/16": ["interface eth1 {", "}"]}

    def test_the_output_reads_back(self) -> None:
        job = _job("vyos", "vyos", _CURLY)
        assert sorted(_routes(job.rendered or "")) == sorted(_HELD)


class TestFromAnotherVendor:
    _IOS = (
        "hostname r1\n"
        "interface GigabitEthernet1\n"
        " ip address 192.0.2.2 255.255.255.0\n"
        "ip route 10.50.0.0 255.255.0.0 Null0\n"
        "ip route 10.52.0.0 255.255.0.0 GigabitEthernet1 192.0.2.1\n"
    )

    def test_a_route_to_null0_is_written_blackhole(self) -> None:
        hops = _hops(_job("cisco_iosxe_cli", "vyos", self._IOS).rendered or "")
        assert hops["10.50.0.0/16"] == ["blackhole {", "}"]

    def test_a_next_hop_keeps_the_interface_it_names(self) -> None:
        hops = _hops(_job("cisco_iosxe_cli", "vyos", self._IOS).rendered or "")
        assert hops["10.52.0.0/16"][0] == "next-hop 192.0.2.1 {"
        assert hops["10.52.0.0/16"][1].startswith("interface ")


class TestOntoEveryTarget:
    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_output_spells_a_route_left_out(self, target: str) -> None:
        assert _left_out_in(_job("vyos", target, _CURLY).rendered or "") == [], target

    @pytest.mark.parametrize("target", PUBLIC)
    def test_the_rows_reach_the_job(self, target: str) -> None:
        rows = [
            r for r in _job("vyos", target, _CURLY).dropped_tier3_sections
            if r.startswith(("protocols static", "disabled: protocols static"))
        ]
        assert rows == _ROWS, target


class TestTheChecksCanFail:
    """The readers are handed what the codec wrote and read up to 0.7.7."""

    def test_the_reader_sees_a_next_hop_that_is_a_name(self) -> None:
        old = "    static {\n        route 10.2.0.0/16 {\n            next-hop eth1 {\n            }\n        }\n"
        assert _hops(old) == {"10.2.0.0/16": ["next-hop eth1 {", "}"]}
        assert _hops(old) != {"10.2.0.0/16": ["interface eth1 {", "}"]}

    def test_the_reader_sees_a_destination_left_out(self) -> None:
        assert _left_out_in("ip route 10.13.0.0 255.255.0.0 192.0.2.1\n") == ["10.13.0.0"]

    def test_the_old_reading_is_not_the_table(self) -> None:
        old = [("10.1.0.0/16", "192.0.2.1", "", 5, ""), ("10.6.0.0/16", "192.0.2.1", "", 0, "")]
        assert old != _HELD
