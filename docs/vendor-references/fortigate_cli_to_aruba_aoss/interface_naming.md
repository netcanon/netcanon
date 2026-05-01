# Interface naming: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/interface_naming.md`](../aruba_aoss_to_fortigate_cli/interface_naming.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

```
config system interface
    edit "port1"
        set alias "WAN-uplink"
        set ip 198.51.100.2 255.255.255.252
        set status up
    next
end
```

FortiGate uses a flat operator-curated namespace.  Default names
are model-specific: `port1` ... `portN` on 100E/200F-class units;
`wan1` / `internal1` ... on lower-end models.  See
[`../aruba_aoss_to_fortigate_cli/interface_naming.md`](../aruba_aoss_to_fortigate_cli/interface_naming.md)
for full FortiGate specifics.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Basic Operation Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/BOG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
interface 1
   name "WAN-uplink"
   routing
   ip address 198.51.100.2/30
   enable
   exit
```

The codec's `_IFACE_HEADER_RE` requires `interface
<[A-Za-z]*\d+(/\d+)?>` — bare numeric, optional letter prefix
(`A1`), or slash-separated stack form (`1/24`).  Importantly,
**FortiGate's `port1` would FAIL Aruba parse** if rendered
verbatim — the codec rejects names with multiple consecutive
non-numeric segments (`port` + `1` is acceptable shape, but
the AOS-S CLI itself only accepts a fixed set of letter prefixes
for uplink modules).

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalInterface(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    interface_type: str = ""
    ...
```

- **name** — `lossy`.  FortiGate's `port1` / `wan1` / `agg1` does
  not match Aruba's `1` / `A1` / `Trk1` pattern.  The port-rename
  mesh **must** be authored by the operator on this direction
  because verbatim FortiGate names will not parse on a downstream
  Aruba re-import.  Aruba render emits whatever the canonical
  carries; the rename mesh applies operator-curated mappings.
- **description** — `good`.  FortiOS `set alias` (capped 25
  chars) -> Aruba `name "..."`.  No truncation in this direction.
- **enabled** — `good`.  FortiOS `set status up` / `set status
  down` -> Aruba `enable` / `disable`.
- **interface_type** — `lossy`.  FortiGate emits explicit
  `set type` only for non-physical edits; Aruba codec infers
  from name shape.

Disposition: **lossy** (FortiGate-source name shape demands
operator-curated rename mappings to land on Aruba's `_IFACE_HEADER_RE`).
