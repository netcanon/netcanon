# VLAN + switchport state — Arista source to OpenConfig NETCONF render gap

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [Arista EOS VLAN Configuration (4.35.2F)](https://www.arista.com/en/um-eos/eos-vlan-configuration)
Retrieved: 2026-05-01

## Arista source surface

The arista_eos parser populates `intent.vlans` with full
VLAN-centric records: id, name, tagged_ports, untagged_ports, plus
the SVI-absorbed L3 addresses (when the source has `interface VlanN`
with `ip address X/N`).  It also populates per-interface switchport
state (`switchport_mode`, `access_vlan`, `trunk_allowed_vlans`,
`trunk_native_vlan`) on every Ethernet-shaped interface that has
`switchport mode access` / `switchport mode trunk`.

Both surfaces are populated independently:

* `intent.vlans[]` — what VLANs exist + their L2 / L3 properties.
* `intent.interfaces[].switchport_*` — how each interface connects
  to those VLANs.

The arista_eos CapabilityMatrix lists `/vlans/vlan/id` and
`/vlans/vlan/name` under `supported`.

## OpenConfig target wire format

OpenConfig has two distinct subtrees for VLAN information:

* Top-level `<vlans>` list (from the `openconfig-vlan` module) —
  declares the VLANs themselves: id, name, status.
* Per-interface `openconfig-vlan:switched-vlan` augment under
  `<ethernet>` — declares membership: interface mode (TRUNK / ACCESS),
  access-vlan, trunk-vlans, native-vlan.

A complete OpenConfig VLAN render needs both subtrees emitted in the
same XML payload.

## What the cisco_iosxe codec emits

`_render_canonical()` walks `intent.interfaces` only.  It does NOT
emit:

* The top-level `<vlans>` list — `intent.vlans` is silently dropped.
* The `switched-vlan` augment under `<ethernet>` — every per-interface
  switchport field (`switchport_mode`, `access_vlan`,
  `trunk_allowed_vlans`, `trunk_native_vlan`, `voice_vlan`) is
  silently dropped.

The capability matrix declares `/vlans/vlan/id` and `/vlans/vlan/name`
under `supported` aspirationally — for cross-codec mesh translations
where another codec consumes the canonical tree downstream — but the
NETCONF render output never contains a `<vlans>` element regardless
of source content.

## Concrete demonstration

For an Arista source like:

```
vlan 10
   name USERS
!
interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Vlan10
   ip address 10.10.10.1/24
```

The cisco_iosxe NETCONF output contains:

* The `Ethernet2` interface entry with name / enabled / type
  (`ethernetCsmacd`) — but NO `switched-vlan` augment.  The
  switchport state is gone.
* The `Vlan10` interface entry with name / enabled / type
  (`l2vlan`) and the `ip address 10.10.10.1/24` as an
  `<subinterface><ipv4>` block.  The SVI's L3 state survives.
* NO top-level `<vlans>` element.  The VLAN definition is gone.

A downstream OpenConfig consumer sees an `Vlan10` SVI with no
declaration of VLAN 10 in the `<vlans>` list and no membership
binding to indicate that Ethernet2 is in VLAN 10.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vlans` | unsupported | Render walks `intent.interfaces` only; no `<vlans>` emitted |
| `vlans[].id` | unsupported | Same render-side gap |
| `vlans[].name` | unsupported | Same render-side gap |
| `vlans[].tagged_ports` | unsupported | Same render-side gap |
| `vlans[].untagged_ports` | unsupported | Same render-side gap |
| `vlans[].ipv4_addresses` (SVI L3) | partially survives | When the Arista codec synthesises `interface VlanN` with addressing, the SVI passes through the interface walk and the L3 addresses survive — the VLAN declaration itself does not |
| `interfaces[].switchport_mode` | unsupported | `switched-vlan` augment not emitted |
| `interfaces[].access_vlan` | unsupported | Same |
| `interfaces[].trunk_allowed_vlans` | unsupported | Same |
| `interfaces[].trunk_native_vlan` | unsupported | Same |
| `interfaces[].voice_vlan` | unsupported | Same; OpenConfig voice-VLAN support is also patchy across releases |

Operator implication: for Arista source carrying any meaningful
VLAN / switchport state, route through `cisco_iosxe_cli` instead.
