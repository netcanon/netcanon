"""OPNsense static-route parse harvest — promotion #15.

Parse now harvests the box default route (from ``<gateway_item
defaultgw=1>``) plus explicit ``<staticroutes><route>`` entries, resolving
a named gateway through the ``<gateways>`` map.  The matrix stays LOSSY —
render still emits no ``<staticroutes>`` block — so this closes an
opnsense-as-source silent loss, not a round-trip.  The load-bearing guard
applies the IP check to the RESOLVED next-hop so an unresolvable name or a
dynamic/DHCP gateway is dropped rather than emitted as a bogus next-hop.
"""
from __future__ import annotations

import pathlib

from netcanon.migration.codecs.opnsense.codec import OPNsenseCodec

_FIXTURES = pathlib.Path(__file__).parents[2] / "fixtures" / "real" / "opnsense"


def _parse(raw: str):
    return {r.destination: r for r in OPNsenseCodec().parse(raw).static_routes}


def test_real_ha_master_synthesises_default_route():
    raw = (_FIXTURES / "opnsense_docs_carp_ha_master.xml").read_text(
        encoding="utf-8",
    )
    routes = _parse(raw)
    assert "0.0.0.0/0" in routes
    assert routes["0.0.0.0/0"].gateway == "172.18.0.250"


def test_supergate_capital_gateways_dhcp_default_is_skipped():
    """A capital-<Gateways> (OPNsense 25 model) defaultgw with an empty
    DHCP <gateway/> resolves to nothing — not a bogus next-hop."""
    raw = (_FIXTURES / "user_contrib_supergate_opn25.xml").read_text(
        encoding="utf-8",
    )
    assert _parse(raw) == {}


def _wrap(body: str) -> str:
    return f"<?xml version='1.0'?>\n<opnsense>{body}</opnsense>"


def test_named_gateway_resolves_unresolvable_and_dynamic_are_dropped():
    raw = _wrap(
        """
        <gateways>
          <gateway_item>
            <name>WAN_GW</name><interface>wan</interface>
            <ipprotocol>inet</ipprotocol><gateway>203.0.113.1</gateway>
          </gateway_item>
          <gateway_item>
            <name>DHCP_GW</name><interface>opt1</interface>
            <ipprotocol>inet</ipprotocol><gateway></gateway>
          </gateway_item>
        </gateways>
        <staticroutes>
          <route><network>10.1.0.0/16</network><gateway>WAN_GW</gateway></route>
          <route><network>10.2.0.0/16</network><gateway>DHCP_GW</gateway></route>
          <route><network>10.3.0.0/16</network><gateway>GHOST</gateway></route>
          <route><network>10.4.0.0/16</network><gateway>198.51.100.9</gateway></route>
        </staticroutes>
        """
    )
    routes = _parse(raw)
    # WAN_GW resolves to its IP; a literal next-hop passes through.
    assert routes["10.1.0.0/16"].gateway == "203.0.113.1"
    assert routes["10.4.0.0/16"].gateway == "198.51.100.9"
    # DHCP_GW (empty gateway) and GHOST (undefined name) are dropped.
    assert "10.2.0.0/16" not in routes
    assert "10.3.0.0/16" not in routes


def test_ipv6_defaultgw_synthesises_v6_default_and_disabled_skipped():
    raw = _wrap(
        """
        <gateways>
          <gateway_item>
            <name>WAN6</name><interface>wan</interface>
            <ipprotocol>inet6</ipprotocol><gateway>2001:db8::1</gateway>
            <defaultgw>1</defaultgw>
          </gateway_item>
          <gateway_item>
            <name>OLD</name><interface>opt2</interface>
            <ipprotocol>inet</ipprotocol><gateway>10.9.9.9</gateway>
            <defaultgw>1</defaultgw><disabled>1</disabled>
          </gateway_item>
        </gateways>
        """
    )
    routes = _parse(raw)
    assert routes["::/0"].gateway == "2001:db8::1"
    # The disabled defaultgw must not synthesise a v4 default route.
    assert "0.0.0.0/0" not in routes
