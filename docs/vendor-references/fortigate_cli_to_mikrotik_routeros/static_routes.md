# Static routes: FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Configuring static routes](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config router static / edit <N> / set dst <NETWORK> <MASK> / set gateway <GW> / set device "<IFACE>"`.

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

Notable FortiOS specifics:

- Destination is **dotted-mask** (`set dst NETWORK MASK`), not CIDR.  Default route is `set dst 0.0.0.0 0.0.0.0`.
- Each static-route edit can carry both a `set gateway` (next-hop IP) and `set device` (outgoing interface).
- `set distance <N>` sets administrative distance (default 10); `set priority <N>` is a route-selection tiebreaker.
- `set blackhole enable` creates a blackhole route.
- VRF is per-interface (FortiOS 7.x integer VRF) but not yet wired into the FortiGate codec.

## MikroTik RouterOS

Sources:
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing) — `/ip route add dst-address=<CIDR> gateway=<GW>`.
- [IPv6 Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992806/IPv6+Routing) — `/ipv6 route` parallel.

Retrieved: 2026-04-30

```
/ip route
add dst-address=0.0.0.0/0 gateway=198.51.100.1 comment="default"
add dst-address=10.50.0.0/16 gateway=10.0.0.254
add dst-address=192.168.99.0/24 gateway=bridge1 type=blackhole

/ipv6 route
add dst-address=::/0 gateway=2001:db8:0:1::1
```

RouterOS uses **CIDR** on the destination (`dst-address=NETWORK/N`).  Gateway can be either a next-hop IP (`gateway=10.0.0.254`) or an outgoing interface (`gateway=bridge1`); the latter is used for connected-style and blackhole routes.

`distance=<N>` sets administrative distance (default 1 on RouterOS, vs FortiOS 10).  `routing-mark=<MARK>` selects a routing table (RouterOS's pre-VRF mechanism); `vrf=<NAME>` is the RouterOS 7+ form.

Description is `comment="..."` on the route record.

## Cross-vendor mapping (FortiGate → RouterOS)

Canonical surface (per-route):

```
CanonicalStaticRoute.destination: str   # CIDR
CanonicalStaticRoute.gateway: str       # next-hop IP
CanonicalStaticRoute.interface: str     # outgoing interface
CanonicalStaticRoute.metric: int
CanonicalStaticRoute.description: str
```

- **destination** — `good`.  FortiOS `set dst 10.99.0.0 255.255.0.0` converts to canonical CIDR `10.99.0.0/16` via the codec helpers; RouterOS render emits `dst-address=10.99.0.0/16` cleanly.  Default route `0.0.0.0/0` round-trips.  IPv6 lines on `/ipv6 route` parallel; FortiGate codec does not yet parse IPv6 static routes (`config router static6`) so those drop on parse.
- **gateway** — `good`.  Both vendors accept a bare next-hop IP.  FortiOS allows simultaneous `set gateway` + `set device`; the canonical model keeps them as separate fields.
- **interface** — `good`.  FortiOS `set device "port1"` populates the canonical interface field; RouterOS render emits `gateway=<iface>` form when the IP is empty, or carries the interface as a hint when both are present (RouterOS prefers the IP when both exist).  Port-rename mesh applies on the interface name.
- **metric** — `lossy`.  FortiOS `set distance N` (default 10) and `set priority N` (tiebreaker) both contribute to route selection; canonical stores a single `metric` integer.  Distance preserves on round-trip but priority drops.  RouterOS's `distance` semantics are similar (lower = preferred) but the default values differ.
- **description** — `lossy`.  FortiOS does not have a per-route description field on `config router static`; the FortiGate-source `description` is empty.  RouterOS `comment="..."` accepts free-form text but has no FortiGate counterpart so cross-vendor it is empty in this direction.
- **vrf** — `unsupported`.  Per-VRF static routes are not modelled on either side: `CanonicalStaticRoute` has no vrf field today, and neither codec parses VRF in v1.  Default-VRF routes are the only well-tested case.
