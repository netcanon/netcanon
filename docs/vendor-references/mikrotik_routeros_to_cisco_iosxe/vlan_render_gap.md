# VLAN render gap — RouterOS source to cisco_iosxe NETCONF target

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
Retrieved: 2026-05-01

Source: [Basic VLAN switching (bridge VLAN filtering) — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)
Retrieved: 2026-05-01

## RouterOS VLAN modelling

RouterOS exposes VLAN configuration in two distinct planes:

1. **Plane 1: routed sub-interfaces** via `/interface vlan`:

   ```
   /interface vlan
   add interface=ether1 name=vlan10 vlan-id=10 comment="Users"
   /ip address
   add address=10.10.10.1/24 interface=vlan10
   ```

   This is "router on a stick" — every VLAN is a layer-3 endpoint.

2. **Plane 2: bridge VLAN filtering** for true layer-2 switching:

   ```
   /interface bridge
   add name=bridge1 vlan-filtering=yes
   /interface bridge port
   add bridge=bridge1 interface=ether1 pvid=10
   /interface bridge vlan
   add bridge=bridge1 vlan-ids=10 tagged=ether2 untagged=ether1
   ```

The MikroTik codec parser populates `intent.vlans[]` from both planes
where it has wire-up coverage; Plane-2 parsing is partial in v1
(documented in the codec README).

## What the cisco_iosxe target emits

Nothing for top-level VLAN definitions.  The
`_render_canonical()` method walks `intent.interfaces` only — it
does NOT walk `intent.vlans[]`.  No `<vlans>` element is emitted in
the output XML.

What DOES survive:

* `intent.interfaces[name="vlan10"]` records (Plane-1 routed sub-
  interfaces) — the SVI interface itself, with its IPv4 / IPv6
  addresses.  These emit as standard `<interface>` elements with
  `interface_type="l3ipvlan"` (the RouterOS-side inference).
* `intent.interfaces[name="bridge1"]` records (Plane-2 bridges) —
  same; the bridge itself emits as a standard interface, but its
  `vlan-filtering` and per-port pvid configuration are dropped.

What does NOT survive:

* Top-level `<vlans>/<vlan>` declarations (`id`, `name`, `status`).
* Per-port `<switched-vlan>` augment (access / trunk / native /
  trunk-vlans).
* The bridge's PVID-per-port mapping.
* The `tagged=` / `untagged=` port lists on bridge VLANs.

## Disposition

`vlans`: `unsupported` with reason citing the render-side wire-up
gap.  When the cisco_iosxe codec grows `<vlans>` render support,
this flips to `lossy` (the same disposition as the sibling
`mikrotik_routeros__cisco_iosxe_cli` pair, which has full canonical
surface coverage on its target render).

`interfaces[].switchport_mode` / `access_vlan` /
`trunk_allowed_vlans` / `trunk_native_vlan`: `unsupported` —
the cisco_iosxe codec does not emit the
`openconfig-vlan:switched-vlan` augment.

`interfaces[].voice_vlan`: `not_applicable` — RouterOS has no
voice-VLAN concept; the canonical field is always empty on this
direction.

## Reference: what the sibling CLI target does emit

For comparison, the sibling `mikrotik_routeros__cisco_iosxe_cli`
target render walks `intent.vlans[]` and emits:

```
vlan 10
 name USERS
!
interface GigabitEthernet0/0/1
 switchport mode access
 switchport access vlan 10
!
interface Vlan10
 description Users
 ip address 10.10.10.1 255.255.255.0
```

None of this lands via the cisco_iosxe NETCONF target render.
