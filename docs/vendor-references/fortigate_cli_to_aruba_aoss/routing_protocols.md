# Routing protocols: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/routing_protocols.md`](../aruba_aoss_to_fortigate_cli/routing_protocols.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Dynamic routing](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiOS 7.x uses an FRR-based routing daemon with rich BGP / OSPF
/ RIP / IS-IS support.  See
[`../aruba_aoss_to_fortigate_cli/routing_protocols.md`](../aruba_aoss_to_fortigate_cli/routing_protocols.md)
for the FortiOS specifics.  The FortiGate codec does not parse
`config router bgp` / `config router ospf` / etc. into canonical
records in v1.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Limited dynamic-routing surface (OSPFv2 + RIP; no BGP / EIGRP /
IS-IS).  See forward-direction sibling for full Aruba specifics.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface: **none**.  v1 canonical model has no
representation for dynamic routing protocols beyond static routes.
Both codecs parse-and-ignore the relevant stanzas.

Disposition: **not_applicable** for this cross-pair (no canonical
field exists).  Operators migrating between vendors with dynamic
routing must manually translate the source's protocol config to
the target.

The mismatch on this direction is also a feature-coverage gap
beyond canonical-schema: FortiOS supports BGP and IS-IS that
Aruba AOS-S does not, so even a hypothetical canonical-schema
extension that captured BGP intent would have nowhere to land it
on the Aruba target.
