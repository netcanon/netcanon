# VRF / routing-instance: not_applicable on OPNsense source

OPNsense has no VRF / routing-instance concept in `config.xml`.  The
platform is a FreeBSD-based firewall/router with a single global
routing table; FreeBSD's FIB-based per-jail routing is a kernel
feature not exposed via OPNsense's canonical wire format.

Sources:
- OPNsense: https://docs.opnsense.org/manual/interfaces.html (retrieved 2026-04-30)

## Implications for OPNsense -> Junos

OPNsense never populates these canonical fields on parse:

* `CanonicalIntent.routing_instances` — always empty list.
* `CanonicalInterface.vrf` — always empty string.
* `CanonicalRoutingInstance.l3_vni` — N/A (no record to carry).

Junos target supports `routing-instances` (capability matrix lists
`/routing-instances/instance` as `supported` via GAP 6) but receives
nothing to render.  The cross-pair never produces VRF apparatus on
the Junos side.

This is a SOURCE-side structural absence rather than a TARGET-side
unsupported.  The fields are `not_applicable` on OPNsense source
because OPNsense's wire format simply doesn't model the concept;
nothing was lost (compared to the Junos -> OPNsense direction where
Junos's populated routing-instances actively drop on render).

Disposition: **not_applicable** for `routing_instances` and all
sub-fields when OPNsense is the source.
