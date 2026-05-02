# VLAN render gap — cisco_iosxe NETCONF source to RouterOS target

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
Retrieved: 2026-05-01

Source: [Basic VLAN switching (bridge VLAN filtering) — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)
Retrieved: 2026-05-01

## OpenConfig VLAN model

`openconfig-vlan` defines a top-level `<vlans>/<vlan>` list with
per-VLAN id / name / status, plus a per-interface `switched-vlan`
augment under `<ethernet>` that carries access / trunk / native /
trunk-vlans membership.

The cisco_iosxe codec's `CapabilityMatrix` declares `/vlans/vlan/id`
and `/vlans/vlan/name` under `supported`.  These declarations are
aspirational — the codec's `parse()` walks `<interfaces>/<interface>`
only and never reads the `<vlans>` subtree if it appears.  The
canonical `intent.vlans` list is always empty after a cisco_iosxe
NETCONF parse.

## What the source actually carries

Three relevant pieces of data live in the source XML's
`<interfaces>` walk:

1. `interfaces[].name` carrying VLAN-named interfaces (e.g. `Vlan10`,
   `Vlan100`) — these survive into `CanonicalIntent.interfaces` as
   first-class records.
2. `interfaces[].interface_type` carrying `iana-if-type:l2vlan` for
   SVI interfaces — survives.
3. `interfaces[].ipv4_addresses` / `interfaces[].ipv6_addresses` on
   those VLAN-named interfaces (the SVI L3 surface) — survives.

The top-level VLAN definitions (id, name, port lists) and per-port
trunk/access membership do NOT survive parse, regardless of how
they're expressed in the source XML.

## RouterOS render expectation

If the canonical `intent.vlans` were populated, the MikroTik render
would emit one of two forms:

1. Pure router-on-a-stick (`/interface vlan` plus `/ip address`):

   ```
   /interface vlan
   add interface=ether1 name=vlan10 vlan-id=10
   /ip address
   add address=10.10.10.1/24 interface=vlan10
   ```

2. Bridge VLAN filtering (Plane 2):

   ```
   /interface bridge
   add name=bridge1 vlan-filtering=yes
   /interface bridge port
   add bridge=bridge1 interface=ether1 pvid=10
   /interface bridge vlan
   add bridge=bridge1 vlan-ids=10 tagged=ether2 untagged=ether1
   ```

Since `intent.vlans` is empty after cisco_iosxe parse, the MikroTik
render emits NEITHER form; only the Vlan-named interface from the
canonical interfaces list survives, rendered as a `/interface vlan`
record with `interface=` defaulting to a synthetic bridge name.
SVI L3 addressing on `Vlan10` does land via `/ip address` on the
synthetic vlan interface.

## Disposition

`vlans`: `not_applicable` — the source codec produces no VLAN
records on parse, so there is nothing for the target render to
drop.  This is not a target-side gap; it is a source-side parse-
side absence.  When the cisco_iosxe codec grows `<vlans>` parse
support, this flips to `lossy` (the same disposition as the
sibling `cisco_iosxe_cli__mikrotik_routeros` pair).

`interfaces[].switchport_mode` / `access_vlan` /
`trunk_allowed_vlans` / `trunk_native_vlan` / `voice_vlan`:
`not_applicable` — same reason.  The cisco_iosxe codec does not
parse the `openconfig-vlan:switched-vlan` augment from interface
records.

## Direction-specific note

This is fundamentally an asymmetry: the cisco_iosxe NETCONF stub
is interface-only on parse, so anything VLAN-related that the
device is willing to expose via NETCONF is ignored.  The reverse-
direction pair (`mikrotik_routeros -> cisco_iosxe`) sees the
opposite asymmetry — RouterOS source carries full VLAN data but
the cisco_iosxe render emits only the synthesised SVI interfaces,
not the top-level `<vlans>` declarations.
