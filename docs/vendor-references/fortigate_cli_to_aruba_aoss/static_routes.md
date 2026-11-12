# Static routes: FortiGate FortiOS versus Aruba AOS-S

<!-- fortios-interface-vrf -->
> **Update 2026-11-12 — a FortiOS interface in a VRF other than 0 is not written into the global table.**  The FortiOS parser read no interface's `set vrf <id>`, so an interface in a VRF other than 0 was written with its addresses, its VRRP groups, the DHCP pool on it and the routes out it into the one table of the output, connected to every other interface.  It still reads no VRF.  It now keeps such an interface's record (description, state, MTU, type, tag) and leaves out its IPv4 and IPv6 addresses, DHCP client and VRRP groups, each DHCP pool on it and each route whose `set device` names it, each with a row in `dropped_tier3_sections`.  What the body below says of `set vrf <id>` being parsed and ignored, or dropped at parse, predates this.

<!-- aoss-route-distance -->
> **Update 2026-11-12 — a route's distance is declared supported on AOS-S.**  The AOS-S matrix declared `/routing/static-route/metric` lossy ("Render emits destination + next-hop only"), while its render writes a route's distance as `distance <N>` on every form it writes (an address, `vlan <id>`, `blackhole`) and its parser reads it back.  The path is declared supported now; AOS-Switch takes a static route's administrative distance from 1 to 255, default 1 (Aruba Central, "Configuring Routing").  What the body below says of the declared loss predates this.  Nor do the two distances differ in meaning, as the body says: FortiOS `set distance` and AOS-S `distance` are each the route's administrative distance.  A route that states none is written with none, so it is at each platform's default (10 on FortiOS, 1 on AOS-S); where that changes which of two routes to one destination is used, it is the CHANGELOG's known limitation on a destination whose next hops mix a stated and an unstated distance.

<!-- a-fortios-route-the-tree-cannot-hold -->
> **Update 2026-11-12 — a FortiOS route printed with no `set dst` is the default route, and a route the tree cannot hold is left out and said.**  The FortiOS parser read a `config router static` entry with no `set dst` (FortiOS prints none for the default, 0.0.0.0/0) as no route, read a blackhole route as a route with no next hop and a route of a VRF other than 0 as a route of the global table, and dropped a route to an address object or an Internet service without a word.  It now reads the first as the default route and leaves each of the others out with a row in `dropped_tier3_sections` (a route of `status disable` with a `disabled:` row); `config router static6` is read by the same rules, and `set gateway 0.0.0.0` is no gateway.  Measured after the change: `static_routes` still drifts on both cells that carry a route (an interface beside a gateway is not written); the cell whose only routes were blackholes is empty.  Sentences below that describe a blackhole route reaching this pair, or say that `set vrf` is not parsed, describe the codec before that change; a sentence that says `set comment` is not parsed is older still, for the parser reads a route's comment into its description.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/fortigate_cli__aruba_aoss.yaml`.

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/static_routes.md`](../aruba_aoss_to_fortigate_cli/static_routes.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Routing](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

```
config router static
    edit 1
        set dst 0.0.0.0 0.0.0.0
        set gateway 198.51.100.1
        set device "port1"
    next
    edit 2
        set dst 10.99.0.0 255.255.0.0
        set gateway 10.20.0.254
        set device "agg1"
    next
end
```

- Mask is dotted-decimal in `set dst`.
- Numeric edit IDs.
- `set device` specifies the outgoing interface.
- `set distance` maps to canonical `metric`.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
ip default-gateway 198.51.100.1
ip route 10.99.0.0/16 10.20.0.254
```

- Mask is CIDR by default; dotted form also accepted.
- `ip default-gateway` desugars to a `0.0.0.0/0` static route.
- No outgoing-interface field on Aruba static routes (gateway-only).

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalStaticRoute(BaseModel):
    destination: str
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
```

- **destination** — `good`.  FortiOS dotted-mask -> Aruba CIDR via
  the codec helpers.
- **gateway** — `good`.  Direct preservation.
- **interface** — `lossy`.  FortiOS `set device "port1"` lands in
  canonical, but Aruba render does not emit an outgoing-interface
  field on static routes (the platform infers from the gateway's
  reachable interface).  Cross-vendor migration loses the
  explicit binding; operators must verify gateway reachability
  post-migration.
- **metric** — `lossy`.  FortiGate distance / AD-ordering vs
  Aruba per-route preference are different primitives.
- **description** — `lossy`.  Both codecs do not parse a
  description field on static routes.

Per-VRF static routes (FortiGate `set vrf <id>`) are unsupported on
this pair — the FortiGate source codec does not parse `set vrf <id>`
(it declares `/routing/static-route/vrf` `unsupported`) and Aruba
has no VRF concept; `CanonicalStaticRoute.vrf` itself exists but is
never populated on either end here.  Aruba's legacy
`ip default-gateway` form synthesises from a `0.0.0.0/0` canonical
record.

Disposition: **lossy**.  Reason: outgoing-interface binding loss
on Aruba render (per-route metadata gap rather than vendor-feature
gap).
