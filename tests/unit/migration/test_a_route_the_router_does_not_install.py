"""A route the router does not install is not a route to translate.

IOS gives a route of administrative distance 255 to a source it does
not believe, and keeps it out of the routing table (Cisco,
"Understand Administrative Distance", document 15986).  The IOS-XE parser read
such a route as any other: onto IOS XR, which takes 1 to 254, it was
written with 254, which the router installs, in a job that said
nothing.  It is a statement the source holds and does not run, and is
left out and said, as a RouterOS route held ``disabled=yes`` is.

IOS XR as the TARGET still meets distances it cannot take, from
platforms that allow 255 or more: such a route is written with 254,
and a review line before ``router static`` says so.  A ``!`` inside
the block would end the mode it is in, so the line is at the top.

Each is read here from the OUTPUT of the plan path the API uses, onto
every public codec where it is the source's half.
"""

from __future__ import annotations

import functools

import pytest

from netcanon.migration._tier3_detection import LEFT_OUT_ROWS_SHOWN, is_left_out_row
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_WHY = "a route of administrative distance 255, which the source does not install; not translated"


@functools.cache
def _job(source: str, text: str, target: str) -> MigrationJob:
    """*text* onto *target*, as the plan endpoints run it."""
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )
    assert job.rendered, f"{source} -> {target}: {job.error}"
    return job


def _xe(*lines: str) -> str:
    head = "hostname r1\n!\ninterface GigabitEthernet1\n ip address 192.0.2.1 255.255.255.0\n!\n"
    return head + "\n".join(lines) + "\n!\nend\n"


def _read(*lines: str):
    """(destination, gateway, distance) of each route the IOS-XE
    parser keeps, and its rows."""
    tree = get_codec("cisco_iosxe_cli").parse(_xe(*lines))
    return [(r.destination, r.gateway, r.metric) for r in tree.static_routes], tree.dropped_tier3_sections


class TestAnIosXeRouteOfDistance255:
    @pytest.mark.parametrize(
        ("line", "row"),
        [
            ("ip route 10.9.0.0 255.255.0.0 192.0.2.254 255", "disabled: ip route 10.9.0.0/16"),
            ("ip route 10.9.0.0 255.255.0.0 GigabitEthernet1 192.0.2.254 255 name spare",
             "disabled: ip route 10.9.0.0/16"),
            ("ip route 10.9.0.0 255.255.0.0 loopback 66 255", "disabled: ip route 10.9.0.0/16"),
            ("ip route vrf A 10.9.0.0 255.255.0.0 192.0.2.254 255", "disabled: ip route vrf A 10.9.0.0/16"),
            ("ip route 10.9.0.0 255.255.0.0 192.0.2.254 255 tag 7", "disabled: ip route 10.9.0.0/16"),
            ("ipv6 route 2001:db8::/32 2001:db8:1::1 255", "disabled: ipv6 route 2001:db8::/32"),
        ],
    )
    def test_it_is_left_out_and_said(self, line: str, row: str) -> None:
        routes, rows = _read(line)
        assert routes == []
        assert rows == [f"{row} ({_WHY})"]
        assert is_left_out_row(rows[0])

    @pytest.mark.parametrize(
        ("line", "read"),
        [
            ("ip route 10.9.0.0 255.255.0.0 192.0.2.254 254", ("10.9.0.0/16", "192.0.2.254", 254)),
            # The distance is the first number; a second is read past.
            ("ip route 10.9.0.0 255.255.0.0 192.0.2.254 200 255", ("10.9.0.0/16", "192.0.2.254", 200)),
            ("ip route 10.9.0.0 255.255.0.0 192.0.2.254 tag 255", ("10.9.0.0/16", "192.0.2.254", 0)),
            ("ip route 10.9.0.0 255.255.0.0 192.0.2.254 name 255", ("10.9.0.0/16", "192.0.2.254", 0)),
            # A mask is no distance.
            ("ip route 10.9.0.0 255.255.255.255 192.0.2.254", ("10.9.0.0/32", "192.0.2.254", 0)),
        ],
    )
    def test_any_other_is_a_route(self, line: str, read: tuple) -> None:
        assert _read(line) == ([read], [])

    def test_beside_a_route_in_force(self) -> None:
        routes, rows = _read(
            "ip route 10.9.0.0 255.255.0.0 192.0.2.254 255",
            "ip route 10.8.0.0 255.255.0.0 192.0.2.254 20",
        )
        assert routes == [("10.8.0.0/16", "192.0.2.254", 20)]
        assert rows == [f"disabled: ip route 10.9.0.0/16 ({_WHY})"]

    def test_the_rows_are_bounded(self) -> None:
        count = LEFT_OUT_ROWS_SHOWN + 25
        lines = [f"ip route 10.{n // 256}.{n % 256}.0 255.255.255.0 192.0.2.254 255" for n in range(count)]
        routes, rows = _read(*lines)
        assert routes == []
        assert len(rows) == LEFT_OUT_ROWS_SHOWN + 1
        assert rows[-1] == "disabled: ... (25 more statements left out; not listed)"
        assert all(is_left_out_row(row) for row in rows)

    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_output_has_it(self, target: str) -> None:
        text = _xe(
            "ip route 198.51.100.0 255.255.255.0 192.0.2.254 255",
            "ip route 203.0.113.0 255.255.255.0 192.0.2.254 20",
        )
        job = _job("cisco_iosxe_cli", text, target)
        assert "198.51.100.0" not in job.rendered, target
        assert f"disabled: ip route 198.51.100.0/24 ({_WHY})" in job.dropped_tier3_sections, target


#: An EOS config with routes of distance 255 (EOS takes 1 to 255),
#: one of them in a VRF, and one of 20.
_EOS = """hostname r1
vrf instance A
!
interface Ethernet1
   no switchport
   ip address 198.51.100.1/24
!
ip route 10.9.0.0/16 198.51.100.2 255
ip route vrf A 10.7.0.0/16 198.51.100.2 255
ip route 10.8.0.0/16 198.51.100.2 20
!
end
"""

_REVIEW = (
    "! review: static route {dest} has administrative distance 255 in the "
    "source; IOS XR takes 1 to 254, and it is written with 254"
)


class TestADistanceIosXrCannotTake:
    def test_it_is_written_with_254_and_said(self) -> None:
        lines = _job("arista_eos", _EOS, "cisco_iosxr").rendered.splitlines()
        assert "  10.9.0.0/16 198.51.100.2 254" in lines
        assert "   10.7.0.0/16 198.51.100.2 254" in lines
        assert "  10.8.0.0/16 198.51.100.2 20" in lines
        reviews = [line for line in lines if "review: static route" in line]
        assert reviews == [_REVIEW.format(dest="10.9.0.0/16"), _REVIEW.format(dest="10.7.0.0/16 vrf A")]

    def test_the_review_lines_are_before_the_block(self) -> None:
        """At the top level: a ``!`` inside ``router static`` ends the
        mode it is in, and the routes after it would be read outside
        their address family."""
        lines = _job("arista_eos", _EOS, "cisco_iosxr").rendered.splitlines()
        block = lines.index("router static")
        assert [n for n, line in enumerate(lines) if "review: static route" in line] == [block - 2, block - 1]

    def test_the_output_reads_back(self) -> None:
        back = get_codec("cisco_iosxr").parse(_job("arista_eos", _EOS, "cisco_iosxr").rendered)
        assert sorted((r.vrf, r.destination, r.metric) for r in back.static_routes) == [
            ("", "10.8.0.0/16", 20), ("", "10.9.0.0/16", 254), ("A", "10.7.0.0/16", 254),
        ]
        assert back.dropped_tier3_sections == []

    def test_a_distance_it_takes_has_no_review_line(self) -> None:
        text = _EOS.replace(" 255\n", " 254\n")
        rendered = _job("arista_eos", text, "cisco_iosxr").rendered
        assert "review: static route" not in rendered
        assert "  10.9.0.0/16 198.51.100.2 254" in rendered.splitlines()
