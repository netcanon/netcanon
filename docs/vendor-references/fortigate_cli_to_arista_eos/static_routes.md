# Static routes: FortiGate FortiOS versus Arista EOS

<!-- fortios-interface-vrf -->
> **Update 2026-11-12 — a FortiOS interface in a VRF other than 0 is not written into the global table.**  The FortiOS parser read no interface's `set vrf <id>`, so an interface in a VRF other than 0 was written with its addresses, its VRRP groups, the DHCP pool on it and the routes out it into the one table of the output, connected to every other interface.  It still reads no VRF.  It now keeps such an interface's record (description, state, MTU, type, tag) and leaves out its IPv4 and IPv6 addresses, DHCP client and VRRP groups, each DHCP pool on it and each route whose `set device` names it, each with a row in `dropped_tier3_sections`.  What the body below says of `set vrf <id>` being parsed and ignored, or dropped at parse, predates this.

<!-- a-fortios-route-the-tree-cannot-hold -->
> **Update 2026-11-12 — a FortiOS route printed with no `set dst` is the default route, and a route the tree cannot hold is left out and said.**  The FortiOS parser read a `config router static` entry with no `set dst` (FortiOS prints none for the default, 0.0.0.0/0) as no route, read a blackhole route as a route with no next hop and a route of a VRF other than 0 as a route of the global table, and dropped a route to an address object or an Internet service without a word.  It now reads the first as the default route and leaves each of the others out with a row in `dropped_tier3_sections` (a route of `status disable` with a `disabled:` row); `config router static6` is read by the same rules, and `set gateway 0.0.0.0` is no gateway.  Measured after the change: `static_routes` is preserved on both cells that carry a route and empty on the other two, and the YAML calls it `good`.  Sentences below that describe a blackhole route reaching this pair, or say that `set vrf` is not parsed, describe the codec before that change; a sentence that says `set comment` is not parsed is older still, for the parser reads a route's comment into its description.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/fortigate_cli__arista_eos.yaml`.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — Static Routing (FortiOS 7.4 Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

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
        set distance 10
        set comment "to-PoP-A"
    next
end
```

Notable FortiOS specifics:

- **Dotted-mask only** for `set dst <ip> <mask>`; codec converts at
  the boundary on parse.
- **`set device "<name>"`** is the outgoing interface — required for
  some route shapes; useful for ECMP / weighted load-sharing.
- **`set distance N`** for administrative distance (FortiGate default
  10).
- **`set comment "..."`** for description.
- **Per-VRF static** via `set vrf <id>` (FortiOS 7.x integer VRF);
  FortiGate codec does not parse this in v1.
- **No native IPv6 static in this block** — IPv6 lives under `config
  router static6` (separate edit-table).

## Arista EOS

Source: [Arista EOS User Manual — Routing Static (4.35.2F)](https://www.arista.com/en/um-eos/eos-routing-static)
Retrieved: 2026-05-01

```
ip route 0.0.0.0/0 192.168.100.1
ip route 10.50.0.0/16 10.0.0.2
ip route 10.99.0.0/16 Ethernet1 10.0.0.2 name "to-PoP-A" 100
!
ipv6 route ::/0 2001:db8:0:1::2
```

Notable Arista specifics:

- **CIDR-only** on modern EOS (`ip route 0.0.0.0/0 <gw>`).
- **Optional outgoing interface** before next-hop (`ip route DEST/N
  <iface> <gw>`).
- **Optional `name "<desc>"`** as a free-form label.
- **Optional administrative distance** as a trailing integer
  (default 1).
- **Per-VRF routes** via `ip route vrf <name> ...` — the
  `arista_eos` codec does not yet parse / render this form (it
  declares `/routing/static-route/vrf` `unsupported`), though
  `CanonicalStaticRoute.vrf` exists.
- **IPv6** via `ipv6 route ::/0 <gw>` with the same modifier syntax.

## Cross-vendor mapping (FortiGate -> Arista)

Canonical surface:

```
static_routes[].destination: str (CIDR)
static_routes[].gateway: str
static_routes[].interface: str   (vendor-native)
static_routes[].metric: int
static_routes[].description: str
```

- **destination** — `good`.  FortiOS dotted-mask (`10.99.0.0
  255.255.0.0`) converts to Arista CIDR (`10.99.0.0/16`) via
  codec helpers.  IPv4 default route (`0.0.0.0 0.0.0.0` <->
  `0.0.0.0/0`) tracks the same path.
- **gateway** — `good`.  Address preserves verbatim.
- **interface** — `lossy`.  FortiGate's `port1` / `agg1` requires
  the port-rename mesh to map to Arista's `Ethernet<N>` /
  `Port-Channel<N>` shapes; without operator-authored mappings the
  Arista parser will reject the device reference.
- **metric (distance)** — `lossy`.  Both vendors store an integer
  but the semantics differ: FortiGate default 10 (AD-ordered);
  Arista default 1 (per-static comparator).  The integer round-
  trips numerically but its meaning shifts on the target.
  Operators should review.
- **description** — `lossy`.  FortiOS `set comment "<desc>"`
  populates canonical; Arista renders `name "<desc>"` modifier.
  FortiGate codec parses `set comment` into the canonical
  description as of Phase 4 wave 7c-F.
- **Per-VRF routes (FortiOS `set vrf <id>`)** — `unsupported`.
  `CanonicalStaticRoute.vrf` exists, but the FortiGate source codec
  does not parse `set vrf <id>`, so data drops at parse; the Arista
  target codec does not render the per-VRF form either.
- **IPv6 routes** — `unsupported`.  FortiGate codec does not parse
  `config router static6` into the canonical static_routes list;
  data drops at parse, and Arista codec wouldn't have any IPv6
  data to render anyway.

Disposition summary: **good** for IPv4 default-VRF route round-trip
(destination, gateway).  **Lossy** for interface (rename mesh),
metric (semantic mismatch), description (codec coverage gap).
**Unsupported** for per-VRF routes (neither the FortiGate source nor
the Arista target wires the per-VRF form, though
`CanonicalStaticRoute.vrf` exists) and IPv6 routes (codec wire-up
gap).
