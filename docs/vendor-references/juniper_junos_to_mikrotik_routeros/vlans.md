# VLANs (id, name, port-membership, SVI): Juniper Junos versus MikroTik RouterOS

How VLANs and per-VLAN L3 interfaces are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching (retrieved 2026-05-01)

Citation ids: `junos-vlans-statement`, `junos-bridging-overview`,
`mikrotik-vlan`, `mikrotik-bridge-vlan`.

## Junos form

```
set vlans USERS vlan-id 10
set vlans USERS vxlan vni 10010
set vlans VOICE vlan-id 20
set vlans TENANT_A_DATA vlan-id 100
set vlans TENANT_A_DATA l3-interface irb.100

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE
set interfaces ge-0/0/1 unit 0 family ethernet-switching native-vlan-id 1
```

Junos models VLANs by name; the `vlan-id <N>` is a property of the
named record.  VLAN names allow letters, digits, hyphens, periods
(no underscores, no spaces).  SVI addressing happens via a separate
`irb` (integrated routing and bridging) interface unit (`irb.100`)
plus a `set vlans <name> l3-interface irb.<unit>` binding.  Trunk /
access mode + member VLANs are configured under each interface's
`unit 0 family ethernet-switching` hierarchy; `native-vlan-id` lives
at the parent-interface level (NOT under the unit).

## RouterOS form

```
/interface vlan
add interface=bridge1 name=vlan100 vlan-id=100
add interface=bridge1 name=vlan200 vlan-id=200

/interface bridge port
add bridge=bridge1 interface=ether2

/interface bridge vlan
add bridge=bridge1 vlan-ids=100 tagged=ether2,bond1 untagged=ether3

/ip address
add address=10.100.0.1/24 interface=vlan100
```

RouterOS has TWO VLAN planes: Plane 1 is `/interface vlan` (router-on-
a-stick — each VLAN becomes a separate L3 interface attached to a
parent — typically used on the routed-only side or when a CPU-driven
trunk is acceptable); Plane 2 is `/interface bridge vlan` (bridge
VLAN filtering — hardware-offloaded VLAN switching for switch-class
RouterOS devices).  RouterOS overloads the L3 interface name as the
VLAN's user-visible name (e.g. `vlan100`), so a separate `name`
field for VLANs does not exist independent of the L3 interface.  No
VLAN-level `description` field; comments hang off the interface
record.  SVI addressing happens by adding `/ip address` to the
`/interface vlan` record.

## Cross-vendor mapping

* `vlans[].id`: Junos `set vlans <name> vlan-id N` -> RouterOS
  `/interface vlan add name=<name> vlan-id=N`.  Direct integer mapping.
* `vlans[].name`: Junos's named VLAN -> RouterOS L3 interface name.
  Lossy because Junos's name space (no underscores, no spaces, up to
  255 chars of `[A-Za-z0-9.-]`) and RouterOS's namespace
  (case-sensitive, `[A-Za-z0-9_-]`, conventionally `vlan<N>`) are
  similar but not identical, and RouterOS conflates the L3
  interface name with the VLAN name (per the MikroTik codec's
  `LossyPath` entry on `/vlans/vlan/name`).
* `vlans[].description`: Junos `set vlans <name> description "X"` ->
  no RouterOS field (drops on render or stamps as `comment=` on the
  `/interface vlan` record).
* `vlans[].tagged_ports` / `vlans[].untagged_ports`: Junos's per-
  interface `family ethernet-switching vlan members` lifts to the
  canonical VLAN-centric port lists; RouterOS render emits
  `/interface bridge vlan add tagged=...,untagged=...` (Plane 2).
  The MikroTik codec's bridge-VLAN parsing is partial in v1, so the
  rendered config may under-populate port lists in the inverse
  direction.
* `vlans[].ipv4_addresses` (SVI absorption): Junos's `irb.<unit>`
  binding -> RouterOS `/interface vlan` + `/ip address`.  Round-trip
  good when the canonical `vlan_id` matches and the L3 interface
  name follows the `vlan<id>` convention.
* `interfaces[].switchport_mode`, `access_vlan`, `trunk_allowed_vlans`,
  `trunk_native_vlan`: Junos's per-interface `family ethernet-
  switching` block round-trips through the canonical port-list /
  switchport state model, but RouterOS's two-plane bridge model
  means render emits a different shape (Plane 2 bridge VLAN
  filtering rather than per-interface mode/access/trunk fields).
  Native VLAN: Junos's parent-level `native-vlan-id` -> RouterOS
  `/interface bridge port set pvid=<N>`.

Disposition: **good** for VLAN id and SVI absorption; **lossy** for
name (namespace + L3-interface conflation) and port-membership
(Plane-2 partial wire-up); **lossy** for description (no RouterOS
first-class field).
