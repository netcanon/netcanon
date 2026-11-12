# Static routes: FortiGate FortiOS versus Juniper Junos

<!-- fortios-interface-vrf -->
> **Update 2026-11-12 — a FortiOS interface in a VRF other than 0 is not written into the global table.**  The FortiOS parser read no interface's `set vrf <id>`, so an interface in a VRF other than 0 was written with its addresses, its VRRP groups, the DHCP pool on it and the routes out it into the one table of the output, connected to every other interface.  It still reads no VRF.  It now keeps such an interface's record (description, state, MTU, type, tag) and leaves out its IPv4 and IPv6 addresses, DHCP client and VRRP groups, each DHCP pool on it and each route whose `set device` names it, each with a row in `dropped_tier3_sections`.  What the body below says of `set vrf <id>` being parsed and ignored, or dropped at parse, predates this.

<!-- junos-route-preference -->
> **Update 2026-11-12 — a route's distance is written as its Junos `preference`.**  Up to 0.7.7 the Junos render wrote destination and next hop only, so a route's distance was lost and a floating route came out as a second next hop of the same preference, carrying traffic beside the route it backs up.  The next hops at a destination's lowest distance are now written `next-hop <address>` with one `route <prefix> preference <n>` line, and each other next hop `qualified-next-hop <address> preference <n>` ("The qualified next-hop preference and metric override the route preference and metric", Juniper, "Static Route Preferences and Qualified Next Hops").  A destination whose next hops mix a stated and an unstated distance is a known limitation: the unstated one is written at the Junos default, 5.  What the body below says of the distance on this pair predates this.

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route is written under `rib inet6.0`.**  Up to 0.7.7 the Junos render wrote an IPv6 static route under `routing-options static`, as an IPv4 route is.  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  The render now writes it there, and the Junos parser reads it back.  The body's `set routing-options static route ::/0 ...` is the form the render wrote before.

<!-- a-fortios-route-the-tree-cannot-hold -->
> **Update 2026-11-12 — a FortiOS route printed with no `set dst` is the default route, and a route the tree cannot hold is left out and said.**  The FortiOS parser read a `config router static` entry with no `set dst` (FortiOS prints none for the default, 0.0.0.0/0) as no route, read a blackhole route as a route with no next hop and a route of a VRF other than 0 as a route of the global table, and dropped a route to an address object or an Internet service without a word.  It now reads the first as the default route and leaves each of the others out with a row in `dropped_tier3_sections` (a route of `status disable` with a `disabled:` row); `config router static6` is read by the same rules, and `set gateway 0.0.0.0` is no gateway.  Measured after the change: `static_routes` still drifts on both cells that carry a route (the outgoing interface does not come back, nor a stated distance); the cell whose only routes were blackholes is empty.  Sentences below that describe a blackhole route reaching this pair, or say that `set vrf` is not parsed, describe the codec before that change; a sentence that says `set comment` is not parsed is older still, for the parser reads a route's comment into its description.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/fortigate_cli__juniper_junos.yaml`.

## FortiGate FortiOS

Source: [FortiGate / FortiOS Administration Guide — Routing / Static routes](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiGate models static routes under `config router static`, keyed by
numeric edit ID:

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
        set distance 5
    next
end
```

Notable FortiOS specifics:

- **Destination form**: dotted-quad address + dotted-quad mask
  (`set dst A.B.C.D MASK`).  No CIDR.
- **Outgoing interface**: `set device "<ifname>"` (mandatory in many
  configs; FortiGate uses it for ECMP keying).
- **Distance**: `set distance N` is FortiOS's administrative-distance
  / preference scalar (1-255).  Default 10 for static.
- **VRF binding**: `set vrf <id>` (FortiOS 7.0+, integer 0-251).
  Not parsed into canonical in v1.
- **Default route blackhole**: `set blackhole enable`.

## Juniper Junos

Source: [Junos static routing topic-map](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html).
Retrieved: 2026-05-01.

Junos models static routes under `set routing-options static
route ...`:

```
set routing-options static route 0.0.0.0/0 next-hop 198.51.100.1
set routing-options static route 10.99.0.0/16 next-hop 10.20.0.254
set routing-options static route 192.168.50.0/24 qualified-next-hop 10.0.0.5 preference 10
set routing-options static route 192.168.50.0/24 qualified-next-hop 10.0.0.6 preference 20
set routing-options static route ::/0 next-hop 2001:db8::2
```

Notable Junos specifics:

- **Destination form**: CIDR (`A.B.C.D/N` for IPv4; IPv6 uses
  colon-hex CIDR).
- **Next hop**: `next-hop <addr>`.  Discard / reject:
  `next-hop discard` / `next-hop reject`.
- **Outgoing interface**: typically encoded by the next-hop's
  reachability rather than a separate field.
- **Preference**: Junos's `preference <N>` is the AD analogue (lower
  = preferred).  Per-route or per-qualified-next-hop.
- **Qualified next-hop**: multiple paths with independent
  preferences (Junos's primary/backup ECMP form); flattens to
  multiple canonical entries with different metrics.
- **Per-VRF**: under `set routing-instances <name> routing-options
  static route ...`.

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surface (`CanonicalStaticRoute`):

```
class CanonicalStaticRoute(BaseModel):
    destination: str        # CIDR
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
```

- **destination** — `good`.  FortiOS dotted-mask -> CIDR conversion
  on parse; Junos render emits CIDR directly.
- **gateway** — `good`.  Direct map.
- **interface** — `lossy`.  FortiOS `set device "<name>"` requires
  rename mesh to map `port1` -> `ge-0/0/X`.  Junos render does not
  always need an outgoing-interface field; the next-hop's reachability
  resolves it.
- **metric** — `lossy`.  FortiOS `distance` and Junos `preference`
  are vendor-specific scalars not 1:1 in semantics.  Integer
  preserves but its meaning differs.
- **description** — `lossy`.  FortiOS `set comment` is not parsed
  into canonical in v1.
- **Per-VRF static routes** — `unsupported`.  The FortiGate source
  codec does not parse `set vrf <id>` (it declares
  `/routing/static-route/vrf` `unsupported`), so
  `CanonicalStaticRoute.vrf` is never populated from this source and
  there is no VRF to carry on this direction.  (The Junos target would
  render `set routing-instances X routing-options static route ...` if
  a VRF were present.)

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/static_routes.md`):

- **destination** — `good`.  CIDR -> dotted-mask on FortiGate render.
- **interface** — `lossy`.  Junos has no first-class outgoing-interface
  field on most static routes; FortiGate render synthesises from
  next-hop reachability.
- **qualified-next-hop** — flattens to multiple canonical entries;
  FortiGate render emits multiple `edit N` records with different
  distances.
- **metric** — same vendor-semantic-scalar mismatch as forward
  direction.
- **Per-VRF static routes** — `unsupported`.
