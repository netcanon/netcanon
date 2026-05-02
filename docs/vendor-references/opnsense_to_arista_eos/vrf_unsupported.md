# VRF / routing-instance unsupported on OPNsense source

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
and [OPNsense Routing](https://docs.opnsense.org/manual/routes.html)
Retrieved: 2026-04-30

OPNsense `config.xml` has NO VRF / routing-instance schema.  The
FreeBSD kernel supports VNETs (jail-scoped network stacks) and
FIBs (multiple FIB tables) but OPNsense exposes neither through
`config.xml` directly — those are kernel-level features
configured outside the OPNsense web GUI's data model.

The opnsense codec capability matrix has no `/routing-instances/*`
or `/vxlan-vnis/*` supported entries (the VXLAN entries are
explicitly listed under unsupported with rationale "VXLAN not
modelled — OPNsense is a firewall codec").

## Arista EOS

Source: [Arista EOS User Manual — VRFs](https://www.arista.com/en/um-eos/eos-vrf)
and [Configuring EVPN](https://www.arista.com/en/um-eos/eos-configuring-evpn)
Retrieved: 2026-05-01

Arista EOS has full VRF support: `vrf instance <name>` declares
the VRF; `ip routing vrf <name>` enables routing inside it;
per-interface `vrf <name>` declares membership; and
`router bgp <asn> / vrf <name>` carries per-VRF MP-BGP RD / RT
state.  EVPN Type-5 IRB additionally uses a per-VRF L3-VNI
declared inside `interface Vxlan1` (`vxlan vrf X vni N`).

## Cross-vendor disposition

Canonical fields affected:

- `routing_instances` (and all sub-fields)
- `interfaces[].vrf`
- `vxlan_vnis` (Arista's L3-VNI / VTEP plumbing)
- `evpn_type5_routes`

All **not_applicable** on this direction — OPNsense source never
populates VRFs, EVPN-VXLAN state, or per-interface VRF
back-pointers.  The fields are structurally empty rather than
actively dropped.  Arista target accepts the VRF / EVPN-VXLAN
shape but on this direction there is nothing to render.
