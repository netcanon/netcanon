# VXLAN / EVPN: not_applicable on OPNsense source

OPNsense is a FreeBSD-based firewall codec.  It does not model
VXLAN, EVPN, or any overlay-fabric primitives in `config.xml`.

Sources:
- OPNsense: https://docs.opnsense.org/manual/interfaces.html (retrieved 2026-04-30)

The opnsense codec capability matrix lists every VXLAN path under
`unsupported` with rationale "VXLAN not modelled — OPNsense is a
firewall codec":

* `/vxlan-vnis/vni`
* `/vxlan-vnis/source-interface`
* `/vxlan-vnis/udp-port`

FreeBSD's `if_vxlan(4)` driver exists at the OS level, but OPNsense
does not surface VXLAN configuration through `config.xml` / the
operator UI.

## Implications for OPNsense -> Junos

OPNsense never populates these canonical fields on parse:

* `CanonicalIntent.vxlan_vnis` — always empty list.
* `CanonicalIntent.evpn_type5_routes` — always empty list.

Junos target supports `vxlan_vnis` (`supported` in capability matrix
via GAP 6 / GAP-EVPN-2) but receives nothing to render.  No VXLAN
overlay apparatus appears on the Junos cross-pair output.

This is a SOURCE-side structural absence rather than a TARGET-side
unsupported.  The fields are `not_applicable` on OPNsense source.

Disposition: **not_applicable** for `vxlan_vnis`, `evpn_type5_routes`,
and the `l3_vni` field on routing-instances when OPNsense is the
source.
