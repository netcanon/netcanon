# VRF / VDOM: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has **no VRF concept**.  The platform is a campus L2/L3
switch with a single global routing table.  Multi-tenancy / route
isolation is not modelled; if operators need it, they deploy
multiple physical or virtual switches.

The Aruba AOS-S codec's `iter_xpaths` does not include any
`/routing-instances/...` paths and the parse path never populates
`CanonicalIntent.routing_instances`.  `CanonicalInterface.vrf` is
always empty on AOS-S source.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — VDOMs and per-interface VRF](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate has two distinct multi-tenancy primitives:

1. **VDOMs** (Virtual Domains).  Heavyweight: each VDOM has its
   own firewall policy table, address objects, admin sessions,
   routing table, interfaces.  VDOMs are enabled globally with
   `config global / set vdom-mode multi-vdom`.  Out of canonical
   scope in v1 — VDOMs require per-VDOM canonical-tree splitting
   that the v1 pipeline does not support.

2. **Per-interface VRF** (FortiOS 7.0+).  Lightweight: a numeric
   VRF ID `0..251` configured via `set vrf <id>` on a single
   interface edit:

   ```
   config system interface
       edit "port1"
           set vrf 5
           ...
       next
   end
   ```

   The FortiGate codec does not currently parse `set vrf <id>`
   into `CanonicalRoutingInstance` records in v1.  No name, no RD,
   no RT — just an integer ID.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalRoutingInstance(BaseModel):
    name: str
    instance_type: str = "vrf"
    route_distinguisher: str = ""
    rt_imports: list[str]
    rt_exports: list[str]
    description: str = ""
    l3_vni: int | None = None
```

`CanonicalIntent.routing_instances` is always empty on Aruba
source (no concept).  `CanonicalInterface.vrf` is also always
empty.  FortiGate target's per-interface integer VRF model has
nothing to consume; the FortiGate render emits no `set vrf` lines.

Disposition: **not_applicable**.  Reason: Aruba source carries no
VRF intent; the canonical field is structurally absent on this
direction.
