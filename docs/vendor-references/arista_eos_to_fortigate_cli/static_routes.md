# Static routes: Arista EOS versus FortiGate FortiOS

## Arista EOS

Source: [Arista EOS User Manual — Routing Static (4.35.2F)](https://www.arista.com/en/um-eos/eos-routing-static)
Retrieved: 2026-05-01

```
ip route 0.0.0.0/0 192.168.100.1
ip route 10.50.0.0/16 10.0.0.2
ip route 10.99.0.0/16 Ethernet1 10.0.0.2 name "to-PoP-A" 100
!
ip route vrf TENANT_A 10.100.99.0/24 10.100.0.254
!
ipv6 route ::/0 2001:db8:0:1::2
```

Notable Arista specifics:

- **CIDR-only on modern EOS** (`ip route 0.0.0.0/0 <gw>`); legacy
  dotted-mask form is accepted on input but `running-config` always
  emits CIDR.
- **Optional outgoing interface** before next-hop (`ip route DEST/N
  <iface> <gw>`).
- **Optional `name "<desc>"`** as a free-form label on the route.
- **Optional administrative distance** as a trailing integer (default
  1; higher integer = less preferred — used for floating statics).
- **Per-VRF routes** via `ip route vrf <name> ...` — the canonical
  model lacks a `vrf` field on `CanonicalStaticRoute`, so per-VRF
  routes parse-and-ignore.
- **IPv6** via `ipv6 route ::/0 <gw>` with the same modifier syntax.

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — Static Routing (FortiOS 7.4 Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
config router static
    edit 1
        set dst 0.0.0.0 0.0.0.0
        set gateway 192.168.100.1
        set device "port1"
    next
    edit 2
        set dst 10.50.0.0 255.255.0.0
        set gateway 10.0.0.2
        set device "agg1"
        set distance 10
        set comment "to-PoP-A"
    next
end
```

Notable FortiOS specifics:

- **Dotted-mask only** for `set dst <ip> <mask>`; codec converts at
  the boundary on parse and render.
- **Per-route edit-id** sequenced 1, 2, 3 — the codec re-numbers on
  render rather than preserving Arista's source order.
- **`set device "<name>"` is the outgoing interface** — FortiOS
  commonly requires this for connected/blackhole-style routes; for
  ordinary next-hop routes it is the egress port name.  Cross-vendor
  render must apply the port-rename mesh to map Arista's `Ethernet1`
  to FortiGate's `port1` shape.
- **`set distance N`** for administrative distance (default 10 for
  FortiGate; semantic differs from Arista's default 1).
- **`set comment "..."`** for free-form description.
- **Per-VRF static** via `set vrf <id>` (FortiOS 7.x integer VRF);
  the FortiGate codec does not parse this in v1.
- **No native IPv6 static** in the same `config router static`
  block — IPv6 lives under `config router static6` (separate
  edit-table; not currently wired through the canonical
  static_routes list either way).

## Cross-vendor mapping (Arista -> FortiGate)

Canonical surface:

```
static_routes[].destination: str (CIDR)
static_routes[].gateway: str
static_routes[].interface: str   (vendor-native)
static_routes[].metric: int
static_routes[].description: str
```

- **destination** — `good`.  Arista CIDR (`10.50.0.0/16`) ->
  FortiGate dotted-mask (`10.50.0.0 255.255.0.0`).  Codec helpers
  handle the conversion losslessly.  IPv4 default route
  (`0.0.0.0/0` <-> `0.0.0.0 0.0.0.0`) tracks the same path.
- **gateway** — `good`.  Address preserves verbatim.
- **interface** — `lossy`.  Arista's `Ethernet1` requires the port-
  rename mesh to map to FortiGate's `port1` shape; without operator-
  authored mappings the FortiGate parser will reject the device
  reference.
- **metric (distance)** — `lossy`.  Both vendors store an integer,
  but the semantics differ: Arista default 1 (per-static comparator);
  FortiGate default 10 (AD-ordered).  The integer round-trips
  numerically but its meaning changes on the target — operators
  reviewing the FortiGate config will see distances that look
  "weak" relative to FortiGate's AD scale.
- **description** — `lossy`.  Arista `name "<desc>"` populates
  canonical; FortiGate renders as `set comment "<desc>"`.  Codec
  parse coverage on Arista's `name` modifier may be inconsistent
  in v1 — verify with real-capture fixture.
- **Per-VRF routes (`ip route vrf X`)** — `unsupported`.  Canonical
  model lacks a `vrf` field on `CanonicalStaticRoute`; data drops at
  parse on Arista source.  Even if it carried, FortiGate codec
  doesn't parse `set vrf <id>`.
- **IPv6 routes** — `unsupported`.  Not wired through canonical
  `static_routes` list on either codec; data drops on parse.

Disposition summary: **good** for IPv4 default-VRF route round-trip
(destination, gateway).  **Lossy** for interface (rename mesh),
metric (semantic mismatch), description (codec parse coverage).
**Unsupported** for per-VRF and IPv6 routes (canonical-model gap +
codec wire-up gap).
