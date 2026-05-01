# VRF / routing-instance unsupported on both vendors

Mirror of `aruba_aoss_to_opnsense/vrf_unsupported.md` for the
reverse direction.

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense's `config.xml` has no VRF / routing-instance schema.
FreeBSD VNETs / FIBs are kernel-level features not exposed via
OPNsense's web GUI data model.  The opnsense codec capability
matrix has no `/routing-instances/*` supported entries.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Management and Configuration Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S has no VRF concept.  Every campus-class platform in
the AOS-S family operates with a single global routing table.  The
aruba_aoss codec capability matrix has no `/routing-instances/*`
supported entries.

## Cross-vendor disposition

Canonical fields affected:

- `routing_instances`
- `interfaces[].vrf`

Both **not_applicable** on this direction — OPNsense source
carries no VRF state; the field is structurally empty rather than
actively dropped.
