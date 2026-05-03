"""
FortiGate render-side regression: static-route descriptions must emit
``set comment "<text>"`` inside the ``config router static / edit N``
block.

The bug was flagged by the mikrotik_routeros source Phase 4b agent --
the FortiGate render dropped ``CanonicalStaticRoute.description`` for
all routes, even though FortiOS supports a ``set comment`` attribute
(singular, max 255 chars) on each entry.

FortiOS reference:
https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/522620/config-router-static

NOTE: the parser (``fortigate_cli/parse.py::_apply_router_static``)
does *not* currently read the ``comment`` field back into
``CanonicalStaticRoute``, so a FortiGate -> FortiGate round-trip
through canonical is still lossy on this field.  Closing the loop
is a parse-side follow-up; this test file covers only the render
side.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalStaticRoute,
)
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec

pytestmark = pytest.mark.unit


def _render(routes: list[CanonicalStaticRoute]) -> str:
    tree = CanonicalIntent(hostname="fw01", static_routes=routes)
    return FortiGateCLICodec().render(tree)


def test_fortigate_static_route_with_description_emits_comments() -> None:
    """A non-empty ``description`` on a static route must surface as
    ``set comment "<text>"`` inside the ``edit N`` block."""
    out = _render([
        CanonicalStaticRoute(
            destination="10.0.0.0/24",
            gateway="192.168.1.1",
            description="Datacentre route",
        ),
    ])
    assert 'set comment "Datacentre route"' in out
    # And it must live inside a static-route edit block, not stray
    # at file scope.
    static_block = out.split("config router static", 1)[1]
    static_block = static_block.split("\nend", 1)[0]
    assert 'set comment "Datacentre route"' in static_block


def test_fortigate_static_route_without_description_unchanged() -> None:
    """Routes with empty ``description`` must NOT emit a stray
    ``set comment`` line -- byte-identity guard against accidentally
    emitting ``set comment ""`` or similar."""
    out = _render([
        CanonicalStaticRoute(
            destination="10.0.0.0/24",
            gateway="192.168.1.1",
        ),
    ])
    assert "set comment" not in out
    # Sanity: the rest of the static-route block still rendered.
    assert "config router static" in out
    assert "set dst 10.0.0.0 255.255.255.0" in out
    assert "set gateway 192.168.1.1" in out


def test_fortigate_static_route_description_only_on_described_routes() -> None:
    """Mixed input -- only routes with a non-empty description should
    carry the ``set comment`` line; the empty-description route stays
    bare."""
    out = _render([
        CanonicalStaticRoute(
            destination="10.0.0.0/24",
            gateway="192.168.1.1",
            description="Datacentre",
        ),
        CanonicalStaticRoute(
            destination="10.0.1.0/24",
            gateway="192.168.1.2",
            # no description
        ),
        CanonicalStaticRoute(
            destination="0.0.0.0/0",
            gateway="192.168.1.254",
            description="Default upstream",
        ),
    ])
    assert out.count("set comment") == 2
    assert 'set comment "Datacentre"' in out
    assert 'set comment "Default upstream"' in out


def test_fortigate_static_route_round_trip_description_parser_gap() -> None:
    """Round-trip through the FortiGate codec is currently LOSSY on
    ``description`` because the parser does not read ``set comment``
    back.  This test pins the gap so it's visible: render emits the
    line, but parse drops it -- a sub-finding for a parse-side
    follow-up.

    Update this test to assert ``description == "Datacentre route"``
    once the parser is taught to read ``set comment``.
    """
    codec = FortiGateCLICodec()
    rendered = codec.render(CanonicalIntent(
        hostname="fw01",
        static_routes=[CanonicalStaticRoute(
            destination="10.0.0.0/24",
            gateway="192.168.1.1",
            description="Datacentre route",
        )],
    ))
    # Render side carries the description through.
    assert 'set comment "Datacentre route"' in rendered

    # Parse side is currently lossy -- regression-pin the gap.
    re_parsed = codec.parse(rendered)
    assert len(re_parsed.static_routes) == 1
    assert re_parsed.static_routes[0].destination == "10.0.0.0/24"
    assert re_parsed.static_routes[0].gateway == "192.168.1.1"
    # FIXME(parse): teach _apply_router_static to read `set comment`.
    assert re_parsed.static_routes[0].description == ""
