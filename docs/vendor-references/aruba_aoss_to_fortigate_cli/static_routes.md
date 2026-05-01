# Static routes: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
ip default-gateway 10.0.0.1
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254
```

Notable AOS-S specifics:

- **Mixed mask form.**  `ip route` accepts both CIDR
  (`192.168.99.0/24`) and dotted-decimal
  (`172.16.0.0 255.255.0.0`).  The codec normalises to canonical
  CIDR on parse.
- **Default-gateway shortcut.**  `ip default-gateway <gw>`
  desugars to a `0.0.0.0/0` static route.
- **No VRF support.**  All routes live in the global routing
  table.

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

Notable FortiOS specifics:

- **Mask is always dotted-decimal** in `set dst`.
- **Numeric edit IDs** on each route entry.
- **`set device`** specifies the outgoing interface (matches
  `CanonicalStaticRoute.interface`).
- **`set distance`** maps to canonical `metric` (FortiOS
  administrative-distance ordering; default 10).
- **Per-VRF routes** via `set vrf <id>` (FortiOS 7.0+); not parsed
  by the codec in v1.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalStaticRoute(BaseModel):
    destination: str
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
```

- **destination** — `good`.  Aruba CIDR -> FortiOS dotted-mask via
  the codec helper.
- **gateway** — `good`.  Direct preservation.
- **interface** — `lossy`.  Aruba sources rarely populate
  `set interface` on static routes (the platform infers from the
  route's gateway); FortiOS render emits `set device` only when
  the canonical field is non-empty.  Cross-vendor migration loses
  nothing on this direction (Aruba source is empty -> FortiGate
  render emits no `set device`).
- **metric** — `lossy`.  Aruba's per-route preference and
  FortiGate's distance / AD-ordering are different primitives;
  the integer preserves but its meaning differs.
- **description** — `lossy`.  Both codecs do not parse a
  description field on static routes.

Aruba's legacy `ip default-gateway` directive normalises to a
`0.0.0.0/0` canonical record that FortiGate renders as
`set dst 0.0.0.0 0.0.0.0`.

Per-VRF static routes are structurally absent (Aruba has no VRF
concept); the FortiGate-side `set vrf <id>` is not emitted.

Disposition: **good**.  Reason: default-VRF static routes round-
trip cleanly; per-route metadata gaps are pre-existing canonical
schema limits, not cross-vendor losses on this direction.
