# Interface naming: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses a **bare numeric** form on standalone units and a
**slot-letter+port** form on stacks / chassis with uplink modules:

```
interface 1
   name "user-desk-01"
   enable
   exit
interface A1
   name "router-uplink-A"
   routing
   ip address 10.0.0.2/30
   exit
interface Trk1
   name "stack-uplink-A"
   enable
   exit
```

The codec's `_IFACE_HEADER_RE` accepts `interface
<[A-Za-z]*\d+(/\d+)?>`: examples include `1`, `A1`, `B24`, `Trk1`,
`Vlan100` — but **not** the slot/letter-port composite form
(`interface 1/A1`).  AOS-S has no IANA `ifType` directive; the
codec infers type from the name shape (bare number → ethernet,
`Trk` → port-channel, `Vlan` → l3ipvlan).

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

FortiGate uses a **flat operator-curated namespace** with model-
specific defaults and operator-renameable interfaces:

```
config system interface
    edit "port1"
        set alias "WAN-uplink"
        set ip 198.51.100.2 255.255.255.252
        set status up
    next
    edit "wan1"
        set alias "ISP1"
        set status up
    next
    edit "loopback0"
        set type loopback
        set ip 10.255.255.1 255.255.255.255
        set status up
    next
end
```

Notable FortiOS specifics:

- **Edit ID is the interface identity.**  Default names follow
  model-specific conventions: `port1` / `port2` ... on FortiGate
  100E / 200F class; `wan1` / `wan2` / `internal1` ... on lower-
  end models.
- **`set alias`** carries an operator-friendly description (capped
  at 25 characters).  Aruba's `name "..."` is the closest analogue.
- **`set type`** explicitly declares aggregate / vlan / loopback
  / tunnel.  Bare physical ports omit it.
- **Status** is `up` / `down` (FortiOS) versus Aruba's `enable` /
  `disable` (which the codec normalises to `enabled: bool`).

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalInterface(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    interface_type: str = ""
    ...
```

- **name** — `lossy`.  Aruba's `1` / `A1` / `Trk1` shape does not
  match FortiGate's `port1` / `wan1` / `agg1` flat namespace.  The
  port-rename mesh applies operator-curated mappings on cross-
  vendor render; without overrides the FortiGate codec preserves
  the Aruba name verbatim — FortiOS will accept the edit name but
  the resulting `port1` analogue may conflict with model defaults.
- **description** — `good`.  Aruba `name "..."` -> FortiOS `set
  alias "..."`.  FortiOS caps at 25 characters; longer Aruba names
  truncate.
- **enabled** — `good`.  Aruba `enable` / `disable` -> FortiOS
  `set status up` / `set status down`.
- **interface_type** — `lossy`.  Aruba codec infers from name
  shape; FortiOS emits explicit `set type` only for non-physical
  edits.  Cross-vendor render fills in the type only when the
  inference is unambiguous.

Disposition: **lossy** (name shape divergence requires the
port-rename mesh; description truncation possible).
