# Static routes: FortiGate FortiOS versus Arista EOS

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
- **Per-VRF routes** via `ip route vrf <name> ...` — canonical
  model lacks a vrf field on CanonicalStaticRoute.
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
  Codec parse coverage on FortiGate's `set comment` may be
  inconsistent in v1.
- **Per-VRF routes (FortiOS `set vrf <id>`)** — `unsupported`.
  Canonical model lacks a vrf field on CanonicalStaticRoute, AND
  the FortiGate codec does not currently parse `set vrf` even if
  the field existed.  Data drops at parse.
- **IPv6 routes** — `unsupported`.  FortiGate codec does not parse
  `config router static6` into the canonical static_routes list;
  data drops at parse, and Arista codec wouldn't have any IPv6
  data to render anyway.

Disposition summary: **good** for IPv4 default-VRF route round-trip
(destination, gateway).  **Lossy** for interface (rename mesh),
metric (semantic mismatch), description (codec coverage gap).
**Unsupported** for per-VRF and IPv6 routes (canonical-model gap +
codec wire-up gap).
