# Static routes: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE IP Routing Configuration Guide — static route
chapter.

Cisco IOS-XE uses **dotted-decimal masks** in the global form:

```
ip route 0.0.0.0 0.0.0.0 198.51.100.1
ip route 10.1.0.0 255.255.0.0 10.0.0.1 100
ip route 10.2.0.0 255.255.0.0 GigabitEthernet0/0/1
ip route vrf MGMT 10.3.0.0 255.255.0.0 10.0.0.2
```

Form: `ip route [vrf <name>] <dest> <mask> {<gateway> | <interface>}
[<metric>] [name <description>] [tag <N>]`.

Per-VRF static routes are scoped via the `vrf <name>` keyword
immediately after `ip route`.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / Static routes](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config router static`.
Source: FortiOS CLI Reference — `config router static`.
Retrieved: 2026-04-30

FortiOS uses the `config / edit / set / next / end` block grammar
with numeric edit IDs:

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

Notable FortiOS specifics:

- **Dotted-decimal masks**, same as Cisco IOS-XE.  Both vendors
  share `set dst <ip> <mask>` shape (FortiOS) versus `ip route <ip>
  <mask>` (Cisco).  The FortiGate codec normalises both to the
  canonical CIDR form on parse.
- **Numeric edit IDs.**  FortiOS routes are addressed by integer
  index (1, 2, 3, ...) rather than by Cisco's positional form.
- **Per-VRF routes** are scoped via `set vrf <id>` (numeric VRF
  identifier) inside the edit block.  The FortiGate codec does not
  currently parse / render VRF-scoped routes; field is parse-and-
  ignore.
- **Default-route detection.**  Both vendors recognise
  `0.0.0.0 0.0.0.0` as the default route.

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface:

```
class CanonicalStaticRoute(BaseModel):
    destination: str        # CIDR: "10.0.0.0/24" or "0.0.0.0/0"
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
```

- **destination** — `good`.  Both codecs convert dotted-mask <-> CIDR
  via `_mask_to_prefix` / `_prefix_to_mask`.
- **gateway** — `good`.  Both vendors accept a next-hop IP.
- **interface** — `good`.  Cisco's `ip route DEST MASK <iface>`
  maps to FortiOS `set device "<iface>"`.  Interface names are
  vendor-native opaque strings — port-rename mesh applies on
  cross-vendor render.
- **metric** — `lossy`.  Cisco's metric token maps to FortiOS's
  `set distance <N>`, but the two carry different semantics: Cisco
  metric is a comparator within static routes; FortiOS distance is
  AD (administrative distance) ordering across protocols.  Both
  codecs treat the integer as opaque on round-trip, so the value
  itself preserves but its meaning differs.
- **description** — `lossy`.  Cisco's `name <desc>` token has a
  FortiOS counterpart in `set comment "..."` but the FortiGate codec
  does not currently parse / render this field.

Per-VRF routes (Cisco `ip route vrf X ...`) are `unsupported` on
both codecs in v1 — `CanonicalStaticRoute` has no `vrf` field.
Cross-vendor migration of multi-VRF static-route tables therefore
flattens to global routes with a banner.

Disposition for default-VRF static routes: **good**.

Disposition for `metric` field: **lossy** (semantic re-interpretation
across vendors).

Disposition for `description` field: **lossy** (FortiGate render
not yet wired).

Disposition for per-VRF static routes: **unsupported** (canonical
schema gap).
