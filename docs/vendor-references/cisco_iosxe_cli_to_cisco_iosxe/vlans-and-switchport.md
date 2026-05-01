# VLANs and switchport — IOS-XE CLI versus OpenConfig NETCONF

## CLI form

Source: [VLAN Configuration Guide, Cisco IOS XE 17.17.x (Catalyst
9600)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-17/configuration_guide/vlan/b_1717_vlan_9600_cg/configuring_vlans.html)
(retrieved 2026-04-30).

```
vlan 100
 name engineering
!
vlan 200
 name lab
!
interface GigabitEthernet1/0/1
 switchport mode trunk
 switchport trunk allowed vlan 100,200
 switchport trunk native vlan 1
!
interface GigabitEthernet1/0/2
 switchport mode access
 switchport access vlan 100
!
```

Two separate stanzas:

1. **VLAN database** — global `vlan <id> / name <X>` entries declaring
   each VLAN.  IDs 1-4094 (1, 1002-1005 reserved).
2. **Per-interface switchport** — `switchport mode access|trunk` and
   the membership lines.

## OpenConfig NETCONF form

Source: [openconfig-vlan model schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
(retrieved 2026-04-30).

The OpenConfig story splits across two locations:

**VLAN database** lives under `network-instance / vlans`:

```xml
<network-instances xmlns="http://openconfig.net/yang/network-instance">
  <network-instance>
    <name>default</name>
    <vlans>
      <vlan>
        <vlan-id>100</vlan-id>
        <config>
          <vlan-id>100</vlan-id>
          <name>engineering</name>
          <status>ACTIVE</status>
        </config>
      </vlan>
    </vlans>
  </network-instance>
</network-instances>
```

**Per-interface switchport** lives in the `openconfig-vlan` augment of
`openconfig-interfaces`, under `ethernet / switched-vlan`:

```xml
<interface>
  <name>GigabitEthernet1/0/1</name>
  <ethernet xmlns="http://openconfig.net/yang/interfaces/ethernet">
    <switched-vlan xmlns="http://openconfig.net/yang/vlan">
      <config>
        <interface-mode>TRUNK</interface-mode>
        <native-vlan>1</native-vlan>
        <trunk-vlans>100</trunk-vlans>
        <trunk-vlans>200</trunk-vlans>
      </config>
    </switched-vlan>
  </ethernet>
</interface>
```

`interface-mode` is an enum: `ACCESS` or `TRUNK`.  `access-vlan`
appears under access mode; `trunk-vlans` (a leaf-list) and
`native-vlan` appear under trunk.

## Cross-format mapping in this repository

The OpenConfig NETCONF codec in this repository (`cisco_iosxe/codec.py`)
**does not wire** the `openconfig-vlan` augment.  Its capability
matrix declares `/vlans/vlan/id` and `/vlans/vlan/name` as
`supported`, but those are canonical-tree paths that the codec
**doesn't actually populate** on parse and **doesn't emit** on render
— the parser only walks `<interfaces>` and the renderer only emits
`<interfaces>`.

The CLI codec (`cisco_iosxe_cli`) parses both the VLAN database and
the per-interface switchport state, populating `intent.vlans` and the
per-interface `switchport_mode` / `access_vlan` / `trunk_allowed_vlans`
/ `trunk_native_vlan` leaves.

| Direction | Disposition |
|---|---|
| CLI -> NETCONF | unsupported — `intent.vlans` and switchport leaves are dropped on render (NETCONF codec emits no VLAN XML). |
| NETCONF -> CLI | not_applicable — NETCONF parser never populates VLANs, so CLI render emits no VLAN stanzas (matches the empty source). |

This is a wire-up gap, not a model gap.  When the NETCONF codec is
extended to emit `openconfig-vlan` XML and parse the corresponding
`<network-instances><vlans>` and `<switched-vlan>` augments, the
disposition flips to `good` for the canonical-stable surface
(`vlans[].id`, `vlans[].name`, `interfaces[].switchport_mode`,
`interfaces[].access_vlan`, `interfaces[].trunk_allowed_vlans`,
`interfaces[].trunk_native_vlan`).

`interfaces[].voice_vlan` will remain `lossy` even after wire-up —
OpenConfig models voice-VLAN under a different augment (`oc-vlan`
plus the `voip` extension) that not all platforms support.
