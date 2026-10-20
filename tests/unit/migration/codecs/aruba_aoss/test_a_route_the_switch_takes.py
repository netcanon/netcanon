"""A static route is written as a line AOS-S takes, or left out and said.

HPE: "The next-hop can be either a gateway IP address, a VLAN, or the
keyword "reject" or "blackhole"" (ArubaOS-Switch Multicast and Routing
Guide, YC.16.04, "Configuring a static route"), and the guide names no
VRF.  The renderer wrote whatever the tree held where the next hop goes:
a route out an interface came out as ``ip route 10.2.0.0/16`` with
nothing after it (26 such lines over the committed captures, one ``ip
default-gateway`` and one ``ipv6 route`` among them), the IOS XR
``Null0`` routes the same, a route to a trunk as ``ip route ... Trk1``,
and a route in a VRF was written into the switch's one table -- and a
job whose routes all named an interface said ``completed``, the matrix
reading ``/routing/static-route/interface`` as supported.  The parser
read ``ip route ... vlan <id>`` and ``blackhole`` as nothing, in
silence.

The output is read by a reader of HPE's grammar typed here, never by
the AOS-S parser: every route line must be one of the grammar's forms,
and every route of the source must be in the output with the next hop
the source gave it -- worked out here from the source's own tree -- or
be named in a ``; review:`` line, in a job that is not ``completed``.

See also ``netcanon/migration/codecs/aruba_aoss/render.py``
(``_route_line``) and ``test_static_route_distance.py``.
"""

from __future__ import annotations

import ipaddress
import re
from collections import Counter
from pathlib import Path

import pytest

import netcanon.migration.codecs  # noqa: F401  (registers the codecs)
from netcanon.migration.codecs.aruba_aoss import render as aoss_render
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
PUBLIC = list_public_codecs()
AOSS = get_codec("aruba_aoss")

# ---------------------------------------------------------------------------
# HPE's grammar, typed by hand
# ---------------------------------------------------------------------------

_ADDR = r"[0-9A-Fa-f:.]+"
#: ``ip route <dest>/<len> | <dest> <mask>  <hop> [distance <1-255>]``
#: and its IPv6 form, where ``<hop>`` is an address, ``vlan <id>``,
#: ``reject`` or ``blackhole``; and ``ip default-gateway <address>``.
_ROUTE_LINE_RE = re.compile(
    rf"^(?P<kw>ip|ipv6) route (?P<dest>{_ADDR}(?:/\d+| {_ADDR})) "
    rf"(?P<hop>vlan (?P<vid>\d+)|reject|blackhole|(?P<addr>{_ADDR}))"
    r"(?: distance (?P<dist>\d+))?$"
)
_DEFAULT_GW_RE = re.compile(rf"^ip default-gateway (?P<addr>{_ADDR})$")
_ANY_ROUTE_LINE_RE = re.compile(r"^(?:ip|ipv6) (?:route|default-gateway)\b")
_REVIEW_RE = re.compile(r"^; review: static route (?P<dest>\S+) ")


def _network(dest: str) -> str:
    """*dest* as one spelling of the network, from either form."""
    if dest == "default":
        dest = "0.0.0.0/0"
    if " " in dest:
        address, mask = dest.split(" ")
        dest = f"{address}/{mask}"
    return str(ipaddress.ip_network(dest, strict=False))


def _read(out: str) -> tuple[Counter, set[str], list[str]]:
    """What the output routes, as ``(network, hop)``; the networks a
    review line names; and each route line that is no form of the
    grammar."""
    hops: Counter = Counter()
    reviewed: set[str] = set()
    wrong: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        review = _REVIEW_RE.match(line)
        if review:
            reviewed.add(_network(review.group("dest")))
            continue
        if not _ANY_ROUTE_LINE_RE.match(line):
            continue
        gw = _DEFAULT_GW_RE.match(line)
        route = _ROUTE_LINE_RE.match(line)
        if gw:
            hops[("0.0.0.0/0", ("address", gw.group("addr")))] += 1
        elif route and (route.group("dist") is None or 1 <= int(route.group("dist")) <= 255):
            if route.group("addr"):
                hop = ("address", route.group("addr"))
            elif route.group("vid"):
                hop = ("vlan", int(route.group("vid")))
            else:
                hop = (route.group("hop"),)
            hops[(_network(route.group("dest")), hop)] += 1
        else:
            wrong.append(line)
    return hops, reviewed, wrong


# ---------------------------------------------------------------------------
# What the source states, worked out from its own tree
# ---------------------------------------------------------------------------

_VLAN_IFACE_RE = re.compile(r"^[Vv]lan(\d+)$")
_DISCARD_RE = re.compile(r"^null ?0$", re.IGNORECASE)


def _is_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _expected(route) -> tuple | None:
    """The next hop AOS-S is to be given for a source *route*, or
    ``None`` where it has none for it."""
    if route.vrf:
        return None
    if _is_address(route.gateway):
        return ("address", route.gateway)
    via = route.interface or route.gateway
    if _DISCARD_RE.match(via):
        return ("blackhole",)
    vlan = _VLAN_IFACE_RE.match(via)
    if vlan:
        return ("vlan", int(vlan.group(1)))
    return None


def _findings(source: str, text: str) -> list[str]:
    """How the AOS-S output of *text* departs from its routes."""
    routes = get_codec(source).parse(text).static_routes
    job = run_plan_with_checked_names(get_codec(source), AOSS, text, port_rename_map={})
    if not job.rendered:
        return []
    hops, reviewed, wrong = _read(job.rendered)
    found = [f"no form of the grammar: {line}" for line in wrong]
    # A port the target has no name for is listed by the job, which is
    # then not ``completed``; the translator takes the routes out of it
    # with it, on every target, before any renderer sees them.
    gone = set(job.unresolved_ports or [])
    wanted: Counter = Counter()
    left_out: set[str] = set()
    went_with_a_port = False
    for route in routes:
        network = _network(route.destination)
        hop = _expected(route)
        if {route.interface, route.gateway} & gone:
            went_with_a_port = True
        elif hop is None:
            left_out.add(network)
        else:
            wanted[(network, hop)] += 1
    if hops != wanted:
        found.append(f"routes {dict(hops - wanted)} written, {dict(wanted - hops)} wanted")
    for network in sorted(left_out - reviewed):
        found.append(f"{network} left out and named in no review line")
    if (left_out or went_with_a_port) and job.status == MigrationJobStatus.completed:
        found.append(f"{sorted(left_out)} left out of a job that said completed")
    return found


# ---------------------------------------------------------------------------
# Each form, from IOS-XE
# ---------------------------------------------------------------------------

_BASE = """hostname r1
!
vrf definition BLUE
 rd 65000:1
 address-family ipv4
 exit-address-family
!
interface GigabitEthernet0/1
 no switchport
 ip address 10.0.1.1 255.255.255.0
!
interface Port-channel1
 no switchport
 ip address 10.0.2.1 255.255.255.0
!
vlan 20
!
interface Vlan20
 ip address 10.0.20.1 255.255.255.0
!
"""

#: One route of each form, alone in its config, and what becomes of it.
_FORMS = {
    "address": ("ip route 10.1.0.0 255.255.0.0 10.0.1.254", "ip route 10.1.0.0/16 10.0.1.254"),
    "distance": ("ip route 10.7.0.0 255.255.0.0 10.0.1.251 50", "ip route 10.7.0.0/16 10.0.1.251 distance 50"),
    "default": ("ip route 0.0.0.0 0.0.0.0 10.0.1.250", "ip default-gateway 10.0.1.250"),
    "default with a distance": ("ip route 0.0.0.0 0.0.0.0 10.0.1.250 7", "ip route 0.0.0.0/0 10.0.1.250 distance 7"),
    "address and port": (
        "ip route 10.6.0.0 255.255.0.0 GigabitEthernet0/1 10.0.1.252",
        "ip route 10.6.0.0/16 10.0.1.252",
    ),
    "discard": ("ip route 10.3.0.0 255.255.0.0 Null0", "ip route 10.3.0.0/16 blackhole"),
    "discard with a distance": (
        "ip route 10.3.0.0 255.255.0.0 Null0 200",
        "ip route 10.3.0.0/16 blackhole distance 200",
    ),
    "vlan interface": ("ip route 10.4.0.0 255.255.0.0 Vlan20", "ip route 10.4.0.0/16 vlan 20"),
    "port": ("ip route 10.2.0.0 255.255.0.0 GigabitEthernet0/1", "; review: static route 10.2.0.0/16 goes out "),
    "lag": ("ip route 10.8.0.0 255.255.0.0 Port-channel1", "; review: static route 10.8.0.0/16 goes out Trk1,"),
    "vrf": ("ip route vrf BLUE 10.5.0.0 255.255.0.0 10.0.1.253", "; review: static route 10.5.0.0/16 is in VRF BLUE"),
}


@pytest.mark.parametrize("form", sorted(_FORMS))
def test_each_form_from_ios_xe(form: str) -> None:
    line, written = _FORMS[form]
    text = _BASE + line + "\n"
    assert _findings("cisco_iosxe_cli", text) == []
    job = run_plan_with_checked_names(get_codec("cisco_iosxe_cli"), AOSS, text, port_rename_map={})
    assert any(out.startswith(written) for out in job.rendered.splitlines()), job.rendered


#: What the parser reads back of each form the renderer writes.
_READ_BACK = {
    "ip route 10.1.0.0/16 10.0.1.254": ("10.1.0.0/16", "10.0.1.254", "", 0),
    "ip route 10.3.0.0/16 blackhole distance 200": ("10.3.0.0/16", "", "Null0", 200),
    "ip route 10.4.0.0/16 vlan 20": ("10.4.0.0/16", "", "Vlan20", 0),
    "ipv6 route 2001:db8:4::/48 vlan 20 distance 9": ("2001:db8:4::/48", "", "Vlan20", 9),
    "ipv6 route 2001:db8:3::/48 blackhole": ("2001:db8:3::/48", "", "Null0", 0),
    "ipv6 route 2001:db8:1::/48 2001:db8::1": ("2001:db8:1::/48", "2001:db8::1", "", 0),
}


@pytest.mark.parametrize("line", sorted(_READ_BACK))
def test_what_the_renderer_writes_the_parser_reads(line: str) -> None:
    (route,) = AOSS.parse(f"hostname t\n{line}\n").static_routes
    assert (route.destination, route.gateway, route.interface, route.metric) == _READ_BACK[line]
    assert AOSS.render(AOSS.parse(f"hostname t\n{line}\n")).count(line) == 1


@pytest.mark.parametrize("line", [
    "ip route 10.0.0.0/8 reject",
    "ipv6 route 2001:db8::/32 reject",
    "ip route 10.0.0.0/8 10.0.0.1 metric 5",
    "ip route 10.0.0.0/8 vlan 99999",
    "ipv6 route 2001:db8::/32 vlan 66 fe80::1",
    "ipv6 route 2001:db8::/32 Trk1",
])
def test_a_route_line_this_parser_does_not_read_is_said(line: str) -> None:
    tree = AOSS.parse(f"hostname t\n{line}\n")
    assert tree.static_routes == []
    assert [row for row in tree.dropped_tier3_sections if row.startswith(line + " (")], tree.dropped_tier3_sections


# ---------------------------------------------------------------------------
# Every committed capture
# ---------------------------------------------------------------------------

_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py"}


def _captures() -> list[tuple[str, Path]]:
    """(codec, path) for every committed capture of a public codec whose
    parser reads a static route."""
    found: list[tuple[str, Path]] = []
    for root in ("real", "synthetic"):
        for path in sorted(p for p in (FIXTURES / root).rglob("*") if p.is_file()):
            if path.suffix.lower() in _NOT_A_CAPTURE:
                continue
            codec = DIR_TO_CODEC_NAME.get(path.relative_to(FIXTURES / root).parts[0])
            if codec not in PUBLIC:
                continue
            try:
                routes = get_codec(codec).parse(path.read_text(encoding="utf-8", errors="replace")).static_routes
            except Exception:  # a refused input has no route here
                continue
            if routes:
                found.append((codec, path))
    return found


CAPTURES = _captures()


def test_the_captures_hold_each_kind_of_route_the_forms_are_for() -> None:
    """The corpus has the routes the defect was found on: out a port, to
    ``Null0``, with no next hop, in a VRF."""
    kinds = set()
    for codec, path in CAPTURES:
        for route in get_codec(codec).parse(path.read_text(encoding="utf-8", errors="replace")).static_routes:
            kinds.add("vrf" if route.vrf else _expected(route)[0] if _expected(route) else "none")
    assert {"address", "blackhole", "vrf", "none"} <= kinds, kinds


@pytest.mark.parametrize(("codec", "path"), CAPTURES, ids=[f"{c}:{p.name}" for c, p in CAPTURES])
def test_every_capture_onto_aos_s(codec: str, path: Path) -> None:
    assert _findings(codec, path.read_text(encoding="utf-8", errors="replace")) == []


# ---------------------------------------------------------------------------
# The check, handed the defect
# ---------------------------------------------------------------------------


def test_the_check_sees_the_old_render(monkeypatch) -> None:
    """With the next hop written as the tree holds it, as before, the
    check fails on a route out a port, to ``Null0``, and in a VRF."""

    def as_before(route) -> str:
        hop = route.gateway or ""
        dist = f" distance {route.metric}" if route.metric else ""
        return f"ip route {route.destination} {hop}{dist}"

    monkeypatch.setattr(aoss_render, "_route_line", as_before)
    for form in ("port", "discard", "vrf"):
        assert _findings("cisco_iosxe_cli", _BASE + _FORMS[form][0] + "\n"), form
