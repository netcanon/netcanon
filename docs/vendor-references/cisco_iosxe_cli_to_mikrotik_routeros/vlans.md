# VLAN configuration: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE Layer-2 Configuration Guide.

```
vlan 10
 name USERS

vlan 20
 name VOICE
 description executive-floor-phones

interface GigabitEthernet0/0/1
 switchport
 switchport mode access
 switchport access vlan 10
 switchport voice vlan 20

interface GigabitEthernet0/0/2
 switchport
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
 switchport trunk native vlan 99

interface Vlan10
 description users-svi
 ip address 10.10.10.1 255.255.255.0
```

Cisco's switching model is **interface-centric**: each port carries
its own `switchport mode` + `switchport access vlan` / `switchport
trunk allowed vlan` declaration, and the global `vlan <N>` stanza
exists primarily for the optional `name` / `description` metadata.

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)
- [Bridge VLAN Table — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/28606465/Bridge+VLAN+Table)

Retrieved: 2026-04-30

RouterOS splits VLAN modeling across **two unrelated planes** that
serve different purposes:

### Plane 1: `/interface vlan` (router-on-a-stick model)

```
/interface vlan
add name=vlan10 vlan-id=10 interface=ether1
add name=vlan20 vlan-id=20 interface=ether1
add name=vlan30 vlan-id=30 interface=ether1

/ip address
add address=10.10.10.1/24 interface=vlan10
```

Each `/interface vlan` line creates a tagged sub-interface bound to
ONE parent (`interface=ether1`) — equivalent to a Linux `vlan10@eth1`
802.1Q sub-interface or a Junos `ge-0/0/0.10` unit.  This is how
RouterOS routers (RB-series) configure VLANs on routed uplinks.

The L2 ethernet-switching surface (which port is access on which
VLAN, which port trunks which list) is NOT modeled here at all.

### Plane 2: bridge VLAN filtering (switching model)

```
/interface bridge
add name=bridge1 vlan-filtering=yes

/interface bridge port
add bridge=bridge1 interface=ether2 pvid=10 frame-types=admit-only-untagged-and-priority-tagged
add bridge=bridge1 interface=ether3 frame-types=admit-only-vlan-tagged

/interface bridge vlan
add bridge=bridge1 vlan-ids=10 untagged=ether2 tagged=ether3
add bridge=bridge1 vlan-ids=20,30 tagged=ether3
```

Only enabled when `vlan-filtering=yes` on the bridge.  This is how
RouterOS switches (CRS-series) implement Cisco-like switchport
semantics.  Each `/interface bridge vlan` row is a VLAN-centric
membership declaration — which conveniently matches the canonical
VLAN-centric port-list shape.

`name`/`description` for VLANs as first-class fields is NOT modeled
on either plane.  Operators stash names in `/interface vlan name=`
(if using Plane 1) or in port `comment=` fields (Plane 2).

### Bridge-VLAN versus router-on-a-stick mismatch

The two planes are not freely interchangeable:

- A RB-series router exposing 802.1Q on uplinks uses Plane 1; there
  is no L2 switching to model.
- A CRS-series switch with bridge VLAN filtering uses Plane 2; the
  `/interface vlan` stanza, if present, sits on top of the bridge
  for management addressing only.

Cross-vendor migration from Cisco's interface-centric switchport
model lands in Plane 2 (bridge VLAN filtering); the access/trunk
intent translates to bridge-port `pvid=` + `frame-types=` plus
`/interface bridge vlan` membership rows.

## Cross-vendor mapping

The canonical surface is

```
CanonicalVlan(id, name, description, tagged_ports[], untagged_ports[],
              ipv4_addresses[])
CanonicalInterface(switchport_mode, access_vlan, trunk_allowed_vlans,
                   trunk_native_vlan, voice_vlan)
```

The MikroTik codec parses `/interface vlan` (Plane 1) into
`CanonicalVlan` records (id + name) and creates a sibling
`CanonicalInterface` record so the rename mesh works.  Bridge VLAN
filtering (Plane 2) parsing is partial in v1 — the codec recognises
`/interface bridge port` `pvid=` as access-VLAN intent but does not
wire up the `tagged_ports[]` / `untagged_ports[]` lists from
`/interface bridge vlan` rows.  Cross-vendor render emits the
Plane 2 surface from the canonical port-list when targeting RouterOS.

### Specific lossy points

- **`vlans[].name`** — RouterOS conflates the L3 interface name
  (e.g. `vlan10`) with the descriptive VLAN name; cross-vendor
  rendering may emit `name=USERS` or default to `vlan10`,
  depending on direction.  Documented in the MikroTik codec's
  `/vlans/vlan/name` `LossyPath` entry.
- **`vlans[].description`** — RouterOS does not model VLAN
  descriptions in either plane.  Cross-vendor render drops the
  description (or stamps it as a `comment=` on the bridge-vlan
  row).
- **`interfaces[].voice_vlan`** — RouterOS has no equivalent
  concept; Cisco's `switchport voice vlan` falls off on render.
  LLDP-MED voice-VLAN advertisement on RouterOS is a separate
  configuration plane.
- **`interfaces[].switchport_mode`** — Plane-2 mapping is
  partial; bridge-port frame-types translate access/trunk intent
  but not all Cisco edge cases (e.g. `dot1q-tunnel`).

### Disposition

| Field | Disposition |
|---|---|
| `vlans[].id` | good |
| `vlans[].name` | lossy (interface-name conflation) |
| `vlans[].description` | lossy (no RouterOS field) |
| `vlans[].tagged_ports` | lossy (Plane-2 wire-up partial) |
| `vlans[].untagged_ports` | lossy (Plane-2 wire-up partial) |
| `vlans[].ipv4_addresses` | good (SVI -> /ip address on /interface vlan) |
| `interfaces[].switchport_mode` | lossy (model mismatch) |
| `interfaces[].access_vlan` | lossy |
| `interfaces[].trunk_allowed_vlans` | lossy |
| `interfaces[].trunk_native_vlan` | lossy |
| `interfaces[].voice_vlan` | unsupported (no MikroTik concept) |
