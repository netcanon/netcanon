# Static routes: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/static_routes.md`](../cisco_iosxe_cli_to_fortigate_cli/static_routes.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Static routes](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config router static`.
Retrieved: 2026-04-30

```
config router static
    edit 1
        set dst 0.0.0.0 0.0.0.0
        set gateway 198.51.100.1
    next
    edit 2
        set dst 10.1.0.0 255.255.0.0
        set gateway 10.0.0.1
        set distance 100
    next
    edit 3
        set dst 10.2.0.0 255.255.0.0
        set device "port1"
    next
end
```

## Cisco IOS-XE

Source: Cisco IOS XE IP Routing Configuration Guide.

```
ip route 0.0.0.0 0.0.0.0 198.51.100.1
ip route 10.1.0.0 255.255.0.0 10.0.0.1 100
ip route 10.2.0.0 255.255.0.0 GigabitEthernet0/0/1
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

```
class CanonicalStaticRoute(BaseModel):
    destination: str        # CIDR
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
```

- **destination** — `good`.  Both codecs round-trip dotted-mask
  <-> CIDR via `_mask_to_prefix` / `_prefix_to_mask`.
- **gateway** — `good`.
- **interface** — `lossy`.  FortiGate's `set device "<iface>"`
  lands in the canonical `interface` field; the Cisco render emits
  `ip route DEST MASK <iface>` only after the rename mesh maps
  FortiGate's `port1` to a Cisco-shape name (default
  `GigabitEthernet0/0/N`).  Without the rename, the literal
  `port1` token would appear in Cisco's `ip route` line and Cisco
  would reject it as an unknown interface.
- **metric** — `lossy`.  FortiGate's `set distance` versus Cisco's
  positional metric token: same value, different semantics
  (administrative distance versus per-static comparator).
- **description** — `lossy`.  FortiGate's `set comment` is not
  currently parsed; Cisco's `name <desc>` is not currently
  rendered.  Field always empty on this cross-pair.

Per-VRF static routes (FortiGate `set vrf <id>`) are
**unsupported** in v1 — `CanonicalStaticRoute` has no `vrf`
field.

Disposition for default-VRF static routes: **good** (with
rename-mesh dependency for the `interface` field).

Disposition for `metric` field: **lossy** (semantic re-
interpretation across vendors; numeric value preserves but
meaning differs).

Disposition for `description` field: **lossy**.

Disposition for per-VRF static routes: **unsupported** (canonical
schema gap).
