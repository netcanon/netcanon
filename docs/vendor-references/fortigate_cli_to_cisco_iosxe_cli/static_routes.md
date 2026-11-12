# Static routes: FortiGate FortiOS versus Cisco IOS-XE

<!-- fortios-interface-vrf -->
> **Update 2026-11-12 — a FortiOS interface in a VRF other than 0 is not written into the global table.**  The FortiOS parser read no interface's `set vrf <id>`, so an interface in a VRF other than 0 was written with its addresses, its VRRP groups, the DHCP pool on it and the routes out it into the one table of the output, connected to every other interface.  It still reads no VRF.  It now keeps such an interface's record (description, state, MTU, type, tag) and leaves out its IPv4 and IPv6 addresses, DHCP client and VRRP groups, each DHCP pool on it and each route whose `set device` names it, each with a row in `dropped_tier3_sections`.  What the body below says of `set vrf <id>` being parsed and ignored, or dropped at parse, predates this.

<!-- a-fortios-route-the-tree-cannot-hold -->
> **Update 2026-11-12 — a FortiOS route printed with no `set dst` is the default route, and a route the tree cannot hold is left out and said.**  The FortiOS parser read a `config router static` entry with no `set dst` (FortiOS prints none for the default, 0.0.0.0/0) as no route, read a blackhole route as a route with no next hop and a route of a VRF other than 0 as a route of the global table, and dropped a route to an address object or an Internet service without a word.  It now reads the first as the default route and leaves each of the others out with a row in `dropped_tier3_sections` (a route of `status disable` with a `disabled:` row); `config router static6` is read by the same rules, and `set gateway 0.0.0.0` is no gateway.  Measured after the change: `static_routes` is preserved on both cells that carry a route and empty on the other two, and the YAML calls it `good`.  Sentences below that describe a blackhole route reaching this pair, or say that `set vrf` is not parsed, describe the codec before that change; a sentence that says `set comment` is not parsed is older still, for the parser reads a route's comment into its description.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/fortigate_cli__cisco_iosxe_cli.yaml`.

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
**unsupported** in v1 — the `cisco_iosxe_cli` target renders the
`ip route vrf X ...` form and `CanonicalStaticRoute.vrf` carries the
discriminator, but the FortiGate source codec does not parse
`set vrf <id>` (it declares `/routing/static-route/vrf`
`unsupported`), so the VRF never reaches canonical on this
direction.

Disposition for default-VRF static routes: **good** (with
rename-mesh dependency for the `interface` field).

Disposition for `metric` field: **lossy** (semantic re-
interpretation across vendors; numeric value preserves but
meaning differs).

Disposition for `description` field: **lossy**.

Disposition for per-VRF static routes: **unsupported** (FortiGate
source does not parse `set vrf <id>`; the Cisco target could render
`ip route vrf X`).
