# VRF / routing-instance: unsupported on OPNsense target

OPNsense has no VRF / routing-instance concept in `config.xml`.
The platform is a FreeBSD-based firewall/router with a single
global routing table; FreeBSD's FIB-based per-jail routing is a
kernel-level feature not exposed via OPNsense's canonical wire
format.

Sources:
- OPNsense: https://docs.opnsense.org/manual/interfaces.html (retrieved 2026-04-30)
- OPNsense: https://docs.opnsense.org/manual/gateways.html (retrieved 2026-04-30)

## Implications for Junos -> OPNsense

Junos populates these canonical fields when the source config
includes routing-instances:

* `CanonicalIntent.routing_instances: list[CanonicalRoutingInstance]`
* `CanonicalInterface.vrf` (per-interface back-pointer)
* `CanonicalRoutingInstance.l3_vni` (for EVPN Type-5)

The opnsense render path emits NOTHING for any of these — the
entire VRF apparatus drops on the cross-pair, and interfaces lose
their VRF membership and revert to the implicit global routing
context.

This is a HARD platform limitation, not a codec wire-up gap.  It
would not close with future opnsense-codec work.

Disposition: **unsupported** for `routing_instances` and all
sub-fields when Junos source populates them.

See `vrf_routing_instances.md` for the structural detail.
