# VLANs (id, name, port-membership, SVI): MikroTik RouterOS versus Juniper Junos

How VLANs and per-VLAN L3 interfaces are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-05-01)

Citation ids: `mikrotik-vlan`, `mikrotik-bridge-vlan`,
`junos-vlans-statement`, `junos-bridging-overview`.

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

RouterOS has TWO VLAN planes:

* **Plane 1** — `/interface vlan` (router-on-a-stick — each VLAN
  becomes a separate L3 interface attached to a parent — typically
  used on the routed-only side or when CPU-driven trunking is
  acceptable).
* **Plane 2** — `/interface bridge vlan` (bridge VLAN filtering —
  hardware-offloaded VLAN switching for switch-class RouterOS
  devices).

RouterOS overloads the L3 interface name as the VLAN's user-visible
name (e.g. `vlan100`); a separate `name` field for VLANs does not
exist independent of the L3 interface.  No VLAN-level `description`
field; comments hang off the interface record.  SVI addressing
happens by adding `/ip address` to the `/interface vlan` record.

The mikrotik_routeros codec parses Plane 1 fully; Plane 2 (bridge
VLAN filtering) parsing is partial in v1 — port lists may
under-populate on parse.

## Junos form

```
set vlans USERS vlan-id 10
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
`irb` interface unit (`irb.100`) plus a `set vlans <name> l3-
interface irb.<unit>` binding.  Trunk / access mode + member VLANs
are configured under each interface's `unit 0 family ethernet-
switching` hierarchy; `native-vlan-id` lives at the parent-interface
level.

## Cross-vendor mapping

* `vlans[].id`: RouterOS `/interface vlan ... vlan-id=N` -> Junos
  `set vlans <name> vlan-id N`.  Direct integer mapping.
* `vlans[].name`: RouterOS L3 interface name (e.g. `vlan100`) ->
  Junos VLAN name.  Lossy because of the namespace differences and
  the L3-interface conflation: RouterOS source's `vlan100` becomes
  the Junos VLAN name, but typical Junos style favours descriptive
  names (`USERS`, `TENANT_A_DATA`) — operator may want to override.
  Junos rejects underscores; RouterOS allows underscores — codec
  sanitises `_` -> `-` on render with banner.
* `vlans[].description`: RouterOS has no native field (uses
  `comment=` on the `/interface vlan` record).  Junos render emits
  `set vlans <name> description X` if the canonical
  `description` is non-empty (from `comment=` parsed value).
* `vlans[].tagged_ports` / `vlans[].untagged_ports`: RouterOS Plane 2
  (`/interface bridge vlan`) port lists -> canonical port lists ->
  Junos per-interface `family ethernet-switching vlan members`.
  Lossy because Plane-2 parser is partial in v1, so canonical port
  lists may under-populate on RouterOS parse.
* `vlans[].ipv4_addresses` (SVI): RouterOS's `/ip address ...
  interface=vlan100` -> Junos's `irb.<vlan-id>` interface unit +
  `set vlans <name> l3-interface irb.<unit>` binding.

Disposition: **good** for VLAN id and SVI absorption; **lossy** for
name (namespace + L3-interface conflation, `_` -> `-` sanitisation)
and port-membership (Plane-2 partial wire-up); **not_applicable** for
description (no RouterOS first-class field — empty after parse).
