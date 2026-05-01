# VLAN configuration: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching (bridge VLAN filtering) — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)

Retrieved: 2026-04-30

RouterOS splits VLAN modeling across **two unrelated planes**:

### Plane 1: `/interface vlan` (router-on-a-stick)

```
/interface vlan
add comment="Users VLAN" interface=bridge1 name=vlan100 vlan-id=100

/ip address
add address=10.100.0.1/24 interface=vlan100
```

Tagged sub-interfaces bound to ONE parent.  Used by RouterOS
routers (RB-series) for routed VLAN uplinks.

### Plane 2: bridge VLAN filtering

```
/interface bridge
add name=bridge1 vlan-filtering=yes

/interface bridge port
add bridge=bridge1 interface=ether1 pvid=100 frame-types=admit-only-untagged-and-priority-tagged
add bridge=bridge1 interface=ether25 frame-types=admit-only-vlan-tagged

/interface bridge vlan
add bridge=bridge1 vlan-ids=100 untagged=ether1 tagged=ether25
```

Used by RouterOS switches (CRS-series) to implement Aruba-like
switchport semantics.  Each `/interface bridge vlan` row carries
VLAN-centric port-list membership.

`name` and `description` are NOT first-class VLAN fields on
either plane.  Operators stash names in `/interface vlan name=`
(Plane 1) or in port `comment=` fields (Plane 2).  The MikroTik
codec's `/vlans/vlan/name` `LossyPath` entry documents the
conflation.

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

Port lists accept ranges (`1-24`), comma-separated lists, and
chassis-letter forms (`A1-A4,B1`).  The codec's `_parse_port_list`
helper expands the list.

The L3 SVI address is part of the VLAN stanza (the
`absorbs_svi_into_vlan: true` codec class-var).

## Cross-vendor mapping

The canonical surface is

```
CanonicalVlan(id, name, description, tagged_ports[], untagged_ports[],
              ipv4_addresses[])
```

The MikroTik codec parses Plane 1 (`/interface vlan`) into
`CanonicalVlan` records with the L3 sub-interface name as `name`
(`vlan100`), and creates a sibling `CanonicalInterface` so the
rename mesh works.  Plane 2 (bridge VLAN filtering) parsing is
**partial in v1** — `/interface bridge port pvid=` is recognised
as access-VLAN intent but `/interface bridge vlan` rows are NOT
fully parsed into `tagged_ports[]` / `untagged_ports[]`.

Aruba target render emits the canonical record as a single
`vlan <id> / name "..." / untagged <ports> / tagged <ports> / ip
address X/N` stanza after the rename mesh maps RouterOS port
names to Aruba bare-numeric / chassis-letter forms.

### Specific lossy points

- **`vlans[].name`** — RouterOS L3 interface-name conflation.
  Source `name=vlan100` lifts to canonical `name="vlan100"`;
  Aruba target render emits `name "vlan100"` (operator-typed VLAN
  name like "USERS" is lost on the canonical layer because
  RouterOS Plane 1 only carries the interface-name).  Operators
  may want to re-enter Aruba VLAN names post-migration.
- **`vlans[].description`** — RouterOS does not model VLAN
  descriptions in either plane.  Field is empty after RouterOS
  parse, so Aruba target emits no `description` keyword.
  Re-classified as **not_applicable** (structural absence on the
  source) rather than lossy.
- **`vlans[].tagged_ports` / `untagged_ports`** — Plane-2 wire-up
  is partial.  When the RouterOS source uses Plane 2 (bridge
  VLAN filtering), the codec captures partial port-list
  membership (pvid=untagged for access ports; tagged ports drop
  unless they appear on `/interface bridge vlan` rows that the
  codec's parser has been extended to read).  Cross-vendor render
  to Aruba may produce a partially populated VLAN port list.
- **`interfaces[].switchport_mode` etc.** — Plane-2 wire-up
  partial; cross-vendor render to Aruba's VLAN-centric model
  works only when the RouterOS source has clean Plane-2 parse
  (the codec re-projects via
  `project_switchport_to_vlan` so Aruba target sees the canonical
  port-list).
- **`interfaces[].voice_vlan`** — Neither vendor models the Cisco
  voice-VLAN concept directly.  Aruba uses LLDP-MED policy on a
  separate plane; RouterOS has no voice-VLAN equivalent.  Field
  empty on both ends.

### SVI absorption

RouterOS `/interface vlan / name=vlan100` + `/ip address add
address=X/N interface=vlan100` lifts to canonical
`CanonicalVlan(id=100).ipv4_addresses = [X/N]` via the codec's
interface-type inference; Aruba target render emits `ip address
X/N` inside the `vlan 100 / name "..."` stanza.

### Disposition

| Field | Disposition |
|---|---|
| `vlans[].id` | good |
| `vlans[].name` | lossy (RouterOS interface-name conflation) |
| `vlans[].description` | not_applicable (structural absence on RouterOS source) |
| `vlans[].tagged_ports` | lossy (Plane-2 wire-up partial) |
| `vlans[].untagged_ports` | lossy (Plane-2 wire-up partial) |
| `vlans[].ipv4_addresses` | good (SVI absorption round-trips) |
| `interfaces[].switchport_mode` | lossy (Plane-2 wire-up partial; partial canonicalisation) |
| `interfaces[].access_vlan` | lossy |
| `interfaces[].trunk_allowed_vlans` | lossy |
| `interfaces[].trunk_native_vlan` | lossy |
| `interfaces[].voice_vlan` | not_applicable (no concept on either side) |
