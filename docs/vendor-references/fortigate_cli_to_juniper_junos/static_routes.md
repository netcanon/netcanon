# Static routes: FortiGate FortiOS versus Juniper Junos

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
- **Per-VRF static routes** — `unsupported`.  CanonicalStaticRoute
  lacks a `vrf` field.

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
