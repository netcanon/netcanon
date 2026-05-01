# VRF / routing-instance unsupported on both vendors

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Management and Configuration Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S has NO VRF / routing-instance concept.  Every
campus-class platform in the AOS-S family (2930F / 2930M / 3810 /
5400R) operates with a single global routing table.  The `vrf`
keyword does not exist in the AOS-S CLI.

The aruba_aoss codec capability matrix accordingly has no
`/routing-instances/*` supported entries, and `CanonicalIntent.
routing_instances` is always empty after an Aruba parse.
`CanonicalInterface.vrf` is always the empty string.

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense's `config.xml` has NO VRF / routing-instance schema
either.  The FreeBSD kernel supports VNETs (jail-scoped network
stacks) and FIBs (multiple FIB tables) but OPNsense exposes neither
through `config.xml` directly — those are kernel-level features
configured outside the OPNsense web GUI's data model.

The opnsense codec capability matrix has no `/routing-instances/*`
supported entries.

## Cross-vendor disposition

Canonical fields affected:

- `routing_instances`
- `interfaces[].vrf`

Both **not_applicable** on this direction (Aruba source carries no
VRF state; the field is structurally empty rather than actively
dropped).  The reverse direction (`opnsense_to_aruba_aoss`) is the
mirror situation — OPNsense source also carries no VRFs.
