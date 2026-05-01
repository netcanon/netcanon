# VLAN configuration: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide
for 2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba is **VLAN-centric** with absorbed SVI L3:

```
vlan 100
   name "USERS"
   untagged 1-24
   tagged 25-26
   ip address 192.168.10.1/24
   exit
```

Port lists accept ranges (`1-24`), comma-separated lists (`25,26`),
and chassis-letter forms (`A1-A4,B1`).  The codec's
`_parse_port_list` helper expands the list into individual port
names that match the canonical schema.

The L3 SVI address (`ip address ...`) is part of the VLAN stanza
(no separate `interface Vlan100` directive), captured by the
codec's `absorbs_svi_into_vlan: true` class-var.

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching (bridge VLAN filtering) — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)

Retrieved: 2026-04-30

RouterOS splits VLAN modeling across **two unrelated planes**:

### Plane 1: `/interface vlan` (router-on-a-stick)

```
/interface vlan
add name=vlan100 vlan-id=100 interface=bridge1

/ip address
add address=192.168.10.1/24 interface=vlan100
```

Each `/interface vlan` row creates a tagged sub-interface bound to
ONE parent (`interface=ether1` or `interface=bridge1`).  Used by
RouterOS routers (RB-series) for routed VLAN uplinks.  Does not
model port-level access/trunk membership.

### Plane 2: bridge VLAN filtering

```
/interface bridge
add name=bridge1 vlan-filtering=yes

/interface bridge port
add bridge=bridge1 interface=ether1 pvid=100 frame-types=admit-only-untagged-and-priority-tagged
add bridge=bridge1 interface=ether25 frame-types=admit-only-vlan-tagged

/interface bridge vlan
add bridge=bridge1 vlan-ids=100 untagged=ether1 tagged=ether25
add bridge=bridge1 vlan-ids=200,300 tagged=ether25
```

Plane 2 is enabled when `vlan-filtering=yes` is set on the bridge.
This is how RouterOS switches (CRS-series) implement Aruba-like
switchport semantics.  Each `/interface bridge vlan` row carries
VLAN-centric port-list membership — which conveniently matches the
canonical port-list shape.

`name` and `description` are NOT first-class on either plane.
Operators stash names in `/interface vlan name=` (Plane 1) or in
port `comment=` fields (Plane 2).  The MikroTik codec's
`/vlans/vlan/name` `LossyPath` entry documents the conflation.

## Cross-vendor mapping

The canonical surface is

```
CanonicalVlan(id, name, description, tagged_ports[], untagged_ports[],
              ipv4_addresses[])
```

Aruba's native VLAN-centric `untagged 1-24 / tagged 25-26 / ip
address X/N` populates the canonical record directly; RouterOS
render needs to emit Plane 1 (for the SVI L3) AND Plane 2 (for the
port membership).  Bridge VLAN filtering (Plane 2) parsing is
**partial** in v1 — the codec recognises `/interface bridge port`
`pvid=` as access-VLAN intent but does not wire up the
`tagged_ports[]` / `untagged_ports[]` lists from
`/interface bridge vlan` rows.

### Specific lossy points

- **`vlans[].name`** — RouterOS conflates the L3 interface name
  (e.g. `vlan100`) with the descriptive VLAN name; cross-vendor
  rendering may emit `name=USERS` or default to `vlan100`,
  depending on direction.  Documented in the MikroTik codec's
  `/vlans/vlan/name` `LossyPath` entry.
- **`vlans[].description`** — RouterOS does not model VLAN
  descriptions in either plane.  Aruba's
  `description "executive-floor"` drops on render or is stamped as
  a `comment=` on the bridge-vlan row.
- **`interfaces[].switchport_mode` / `access_vlan` /
  `trunk_allowed_vlans` / `trunk_native_vlan`** — Aruba carries
  these implicitly via VLAN-centric port lists; RouterOS Plane-2
  parsing is partial in v1, so cross-vendor render may produce a
  partially populated bridge-VLAN table.
- **`interfaces[].voice_vlan`** — Aruba models voice VLAN via LLDP-
  MED policy on a separate plane, NOT via `switchport voice vlan`
  like Cisco.  RouterOS has no LLDP-MED voice-VLAN equivalent.
  Field unmodelled on both sides; lossy on round-trip.

### SVI absorption

Aruba's `vlan 10 / ip address X/N` populates
`CanonicalVlan.ipv4_addresses`.  RouterOS render emits a synthetic
`/interface vlan add name=vlan10 vlan-id=10 interface=<parent>`
plus `/ip address add address=X/N interface=vlan10`.  The choice
of parent (typically `bridge1` if the source had a bridge, else the
primary uplink interface) is a render policy decision; operators
may need to rebind the parent post-migration.

### Disposition

| Field | Disposition |
|---|---|
| `vlans[].id` | good |
| `vlans[].name` | lossy (interface-name conflation) |
| `vlans[].description` | lossy (no RouterOS field) |
| `vlans[].tagged_ports` | lossy (Plane-2 wire-up partial) |
| `vlans[].untagged_ports` | lossy (Plane-2 wire-up partial) |
| `vlans[].ipv4_addresses` | good (SVI -> /ip address on /interface vlan) |
| `interfaces[].switchport_mode` | lossy (model mismatch + partial Plane-2 wire-up) |
| `interfaces[].access_vlan` | lossy |
| `interfaces[].trunk_allowed_vlans` | lossy |
| `interfaces[].trunk_native_vlan` | lossy |
| `interfaces[].voice_vlan` | unsupported (no concept on either side) |
