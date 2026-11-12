# VRF / VDOM: FortiGate FortiOS versus Aruba AOS-S

<!-- fortios-interface-vrf -->
> **Update 2026-11-12 — a FortiOS interface in a VRF other than 0 is not written into the global table.**  The FortiOS parser read no interface's `set vrf <id>`, so an interface in a VRF other than 0 was written with its addresses, its VRRP groups, the DHCP pool on it and the routes out it into the one table of the output, connected to every other interface.  It still reads no VRF.  It now keeps such an interface's record (description, state, MTU, type, tag) and leaves out its IPv4 and IPv6 addresses, DHCP client and VRRP groups, each DHCP pool on it and each route whose `set device` names it, each with a row in `dropped_tier3_sections`.  What the body below says of `set vrf <id>` being parsed and ignored, or dropped at parse, predates this.

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/vrf.md`](../aruba_aoss_to_fortigate_cli/vrf.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — VDOMs and per-interface VRF](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate has two distinct multi-tenancy primitives:

1. **VDOMs** — heavyweight, per-VDOM firewall-policy / address /
   admin / routing tables.  Enabled via
   `config global / set vdom-mode multi-vdom`.
2. **Per-interface VRF** (FortiOS 7.0+) — lightweight numeric VRF
   ID `0..251` via `set vrf <id>` on an interface edit.

The FortiGate codec does not currently parse either form into
`CanonicalRoutingInstance` records in v1.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has **no VRF concept**.  Single global routing table,
single-tenant.  Multi-tenancy / route isolation is not modelled.

## Cross-vendor mapping (FortiGate -> Aruba)

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

`CanonicalIntent.routing_instances` is empty after FortiGate parse
in v1 (the codec parse-and-ignores the relevant stanzas).  Even if
the FortiGate codec wired through `set vrf <id>` to populate
`CanonicalInterface.vrf`, Aruba target has no VRF concept to
consume — the field would drop on render.

VDOMs require per-VDOM canonical-tree splitting that the v1
pipeline does not support; Aruba could not represent VDOM
multi-tenancy regardless of canonical-side wiring.

Disposition: **unsupported**.  Reason: FortiGate VRF / VDOM intent
has no Aruba target; the AOS-S platform is single-tenant.
