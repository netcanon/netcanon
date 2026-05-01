# VLAN configuration: MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)
- [Bridge VLAN Table — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/28606465/Bridge+VLAN+Table)

Retrieved: 2026-04-30

Two VLAN planes (see `switching_model.md` for the philosophy):

### Plane 1 — `/interface vlan` (router-on-a-stick)

```
/interface vlan
add name=vlan10 vlan-id=10 interface=ether1
add name=vlan20 vlan-id=20 interface=ether1

/ip address
add address=10.10.10.1/24 interface=vlan10
```

### Plane 2 — bridge VLAN filtering

```
/interface bridge
add name=bridge1 vlan-filtering=yes

/interface bridge port
add bridge=bridge1 interface=ether2 pvid=10 \
    frame-types=admit-only-untagged-and-priority-tagged
add bridge=bridge1 interface=ether3 \
    frame-types=admit-only-vlan-tagged

/interface bridge vlan
add bridge=bridge1 vlan-ids=10 untagged=ether2 tagged=ether3
add bridge=bridge1 vlan-ids=20 tagged=ether3
```

## Cisco IOS-XE

Source: Cisco IOS XE Layer-2 Configuration Guide.

```
vlan 10
 name USERS
vlan 20
 name VOICE

interface GigabitEthernet0/0/2
 switchport
 switchport mode access
 switchport access vlan 10

interface GigabitEthernet0/0/3
 switchport
 switchport mode trunk
 switchport trunk allowed vlan 10,20

interface Vlan10
 ip address 10.10.10.1 255.255.255.0
```

## Cross-vendor mapping

The canonical surface is

```
CanonicalVlan(id, name, description, tagged_ports[], untagged_ports[],
              ipv4_addresses[])
CanonicalInterface(switchport_mode, access_vlan, trunk_allowed_vlans,
                   trunk_native_vlan, voice_vlan)
```

### MikroTik -> Cisco direction

The MikroTik codec parses Plane 1 (`/interface vlan`) into
`CanonicalVlan` records (id + name) and creates a sibling
`CanonicalInterface` per VLAN sub-interface.  Cisco's render of
this canonical shape lands as:

- A global `vlan <N> / name <name>` block per `CanonicalVlan`.
- An `interface Vlan<N> / ip address ...` SVI when the VLAN
  carries `ipv4_addresses`.
- Per-port switchport configuration ONLY when the canonical
  records carry `tagged_ports` / `untagged_ports` — which Plane 1
  alone does NOT populate.  Plane 2 (bridge VLAN filtering)
  parsing of `/interface bridge vlan` rows is the path that fills
  these lists.

### Bridge VLAN filtering parsing (partial in v1)

The MikroTik codec recognises:

- `/interface bridge port pvid=N` -> sets the `interfaces[].
  access_vlan = N` and `switchport_mode = "access"` on the
  matching `CanonicalInterface`.
- `/interface bridge vlan` rows -> populates
  `vlans[].tagged_ports` and `vlans[].untagged_ports` lists.

These are partial in v1; complex bridge filtering (multiple
bridges, VLAN-aware bonding) does not lift cleanly into the
canonical model.

### voice_vlan

RouterOS has no voice-VLAN concept.  MikroTik source never
populates `interfaces[].voice_vlan`; on render to Cisco, the
field is empty and Cisco emits no `switchport voice vlan`.
This is the inverse of the cisco -> mikrotik direction's
unsupported finding — no information to LOSE means
`not_applicable` in the canonical scoring.

### vlans[].name

RouterOS conflates the L3 interface name (e.g. `vlan10`) with
the descriptive VLAN name; the codec strips the `vlan` prefix
and uses the suffix as `CanonicalVlan.name` when no separate
descriptive name exists.  This is round-trip-stable
single-vendor but cross-vendor render to Cisco may emit a
generic numeric name (e.g. `name VLAN_10`) when the parsed
name is already vacuous.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `vlans[].id` | good |
| `vlans[].name` | lossy (interface-name conflation; cross-vendor name preservation depends on operator form) |
| `vlans[].description` | not_applicable (RouterOS has no description field; nothing to migrate) |
| `vlans[].tagged_ports` | lossy (Plane-2 parse partial in v1) |
| `vlans[].untagged_ports` | lossy (Plane-2 parse partial in v1) |
| `vlans[].ipv4_addresses` | good (`/interface vlan` + `/ip address` -> `interface Vlan<N>`) |
| `interfaces[].switchport_mode` | lossy (Plane-2 parse partial) |
| `interfaces[].access_vlan` | lossy (parsed from bridge-port `pvid=`) |
| `interfaces[].trunk_allowed_vlans` | lossy (parsed from `/interface bridge vlan`) |
| `interfaces[].trunk_native_vlan` | lossy (RouterOS encodes via `pvid=` + frame-types combo) |
| `interfaces[].voice_vlan` | not_applicable (no RouterOS source) |
