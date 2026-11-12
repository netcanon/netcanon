# Static routes: MikroTik RouterOS versus FortiGate FortiOS

<!-- ipv6-route-section -->
> **Update 2026-11-12 — an IPv6 route of `/ipv6 route` is read.**  Up to 0.7.7 the RouterOS parser read no `/ipv6 route` section, and every IPv6 route of a RouterOS config was lost on every target, with nothing said, whatever the body below says of it.  `/ipv6 route` is now read with the keys of `/ip route` ([MikroTik, IP Routing](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing): "To add or remove routes /ip(ipv6) route menus should be used"), and a route of another routing table, a disabled route and a route that discards are left out of it and said as they are there.  The FortiOS render writes such a route into `config router static6`, which the FortiOS parser reads back; the body's "drop on render" was not so.  The *IPv6 Routing* page linked below no longer resolves; the IP Routing page covers both menus.

## MikroTik RouterOS

Sources:
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing) — `/ip route add dst-address=<CIDR> gateway=<GW>`.
- [IPv6 Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992806/IPv6+Routing) — `/ipv6 route` parallel.

Retrieved: 2026-04-30

```
/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 gateway=198.51.100.1
add comment="Branch network via core" dst-address=10.50.0.0/16 gateway=10.0.0.254
add comment="Blackhole RFC1918 leakage" dst-address=192.168.99.0/24 gateway=bridge1

/ipv6 route
add dst-address=::/0 gateway=2001:db8:0:1::1
```

Notable RouterOS specifics:

- Destination is **CIDR** (`dst-address=NETWORK/N`).  Default route is `dst-address=0.0.0.0/0`.
- `gateway=` accepts either a next-hop IP or an outgoing interface name; for blackhole routes use `type=blackhole`.
- `distance=N` is administrative distance (default 1).
- `routing-mark=` selects a routing table (RouterOS's pre-VRF mechanism); RouterOS 7+ also supports `vrf=<NAME>`.
- `comment="..."` is the human description.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Configuring static routes](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config router static`.

Retrieved: 2026-04-30

```
config router static
    edit 1
        set dst 0.0.0.0 0.0.0.0
        set gateway 198.51.100.1
        set device "port1"
    next
    edit 2
        set dst 10.50.0.0 255.255.0.0
        set gateway 10.0.0.254
    next
end
```

Destination is dotted-mask (`set dst NETWORK MASK`); default route is `set dst 0.0.0.0 0.0.0.0`.  Each edit can carry both a `set gateway` (next-hop IP) and `set device` (outgoing interface).  `set distance N` is administrative distance (default 10); `set blackhole enable` for blackhole routes.

VRF: per-interface integer VRF (FortiOS 7.x) is not yet wired in the FortiGate codec.

## Cross-vendor mapping (RouterOS → FortiGate)

Canonical surface (per-route):

```
CanonicalStaticRoute.destination: str   # CIDR
CanonicalStaticRoute.gateway: str       # next-hop IP
CanonicalStaticRoute.interface: str     # outgoing interface
CanonicalStaticRoute.metric: int
CanonicalStaticRoute.description: str
```

- **destination** — `good`.  RouterOS `dst-address=10.50.0.0/16` parses to canonical CIDR; FortiOS render emits `set dst 10.50.0.0 255.255.0.0` via the codec's prefix-to-mask helper.  Default route round-trips.  IPv6 routes on `/ipv6 route` parse but the FortiGate codec does not yet emit `config router static6` so IPv6 static routes drop on render.
- **gateway** — `good` for IP-form gateways.  RouterOS `gateway=10.0.0.254` -> FortiOS `set gateway 10.0.0.254`.  Interface-form gateways (`gateway=bridge1`) populate canonical `interface` instead and FortiOS render emits `set device "<iface>"`.
- **interface** — `good`.  RouterOS `gateway=<iface>` form (used for connected-style and blackhole routes) lands on `CanonicalStaticRoute.interface`; FortiOS render emits `set device "<iface>"` after the rename mesh.
- **metric** — `lossy`.  RouterOS `distance=N` (default 1) and FortiOS `set distance N` (default 10) carry similar AD semantics but with different defaults; the integer preserves verbatim, but a RouterOS-source default route with no explicit distance (RouterOS default 1) renders as FortiOS `set distance 1`, which has different priority semantics on the FortiGate side.  Operators should review.
- **description** — `lossy`.  RouterOS `comment="..."` parses cleanly; FortiOS `config router static` does not have a per-route description field, so the comment drops on FortiGate render.
- **vrf / blackhole / type** — `unsupported` for VRF.  `CanonicalStaticRoute.vrf` carries the per-route discriminator, but neither codec on this pair wires it: the RouterOS source codec does not parse `routing-table=` / `vrf=` and the FortiGate target codec does not render `set vrf <id>` (both declare `/routing/static-route/vrf` `unsupported`).  Blackhole routes (`type=blackhole` on RouterOS, `set blackhole enable` on FortiOS) are not modelled canonically — the route falls back to a regular `set gateway` on FortiOS render even when the source had an interface-only blackhole.
