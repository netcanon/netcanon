# VLAN + switchport state — OpenConfig NETCONF source to Arista target

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [Arista EOS VLAN Configuration (4.35.2F)](https://www.arista.com/en/um-eos/eos-vlan-configuration)
Retrieved: 2026-05-01

## Why this is a parse-side gap, not a render-side gap

Unlike the forward direction (`arista_eos -> cisco_iosxe`) where the
target render silently drops VLAN data, on this reverse direction the
source PARSER never populates VLAN data.  The arista_eos target codec
is fully wired to render `intent.vlans` and per-interface switchport
state; it just receives an empty canonical tree.

## What the cisco_iosxe parser does NOT extract

Even when the source NETCONF XML carries:

```xml
<vlans xmlns="http://openconfig.net/yang/vlan">
  <vlan>
    <vlan-id>10</vlan-id>
    <config><vlan-id>10</vlan-id><name>USERS</name></config>
  </vlan>
</vlans>
```

and per-interface `openconfig-vlan:switched-vlan` augment under
`<ethernet>`:

```xml
<ethernet>
  <switched-vlan>
    <config>
      <interface-mode>ACCESS</interface-mode>
      <access-vlan>10</access-vlan>
    </config>
  </switched-vlan>
</ethernet>
```

The cisco_iosxe parser ignores both subtrees.  `intent.vlans` is
empty; per-interface `switchport_*` fields stay None.

## What the arista_eos target render does

The arista_eos codec's render walks `intent.vlans` and emits:

```
vlan <id>
   name <name>
```

Plus per-interface switchport state (`switchport mode access`,
`switchport access vlan N`, `switchport mode trunk`, `switchport
trunk allowed vlan ...`, `switchport trunk native vlan N`).

When `intent.vlans` is empty and per-interface switchport fields
are None, the Arista render emits nothing in the VLAN-related
sections.  The output contains the L3 SVI interfaces (`interface
Vlan10`) IF the source's `<interfaces>` walk produced them — those
pass through the interface walk independently of `<vlans>` — but
without a top-level `vlan 10` declaration, the Arista device
treats VLAN 10 as undefined when it commits the `interface Vlan10`
stanza.

## Concrete demonstration

For a Cisco source with a VLAN 10 declaration, an Ethernet2 in
access mode on VLAN 10, and a Vlan10 SVI:

* The cisco_iosxe parser produces a `CanonicalIntent` with:
  * `interfaces[]` containing `Ethernet2` (no switchport state) and
    `Vlan10` (with the L3 address).
  * `vlans[]` empty.
* The arista_eos render produces:
  * `interface Ethernet2` with no switchport directive (the port
    defaults to `no switchport` on EOS, putting it in routed mode
    instead of access).
  * `interface Vlan10` with the L3 address — but no preceding `vlan 10
    / name USERS` declaration.

A device commit on the Arista output succeeds for the L3 piece (EOS
auto-creates VLAN 10 from the SVI declaration in some configurations),
but the access-port assignment is silently lost.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vlans` | not_applicable | Parse-side gap: cisco_iosxe parser doesn't walk `<vlans>` |
| `vlans[].id` | not_applicable | Same |
| `vlans[].name` | not_applicable | Same |
| `vlans[].tagged_ports` | not_applicable | Same |
| `vlans[].untagged_ports` | not_applicable | Same |
| `vlans[].ipv4_addresses` | partially survives | When source `<interfaces>` includes `Vlan*` entries with addresses, they pass through the interfaces walk and the Arista SVI declaration emits — the VLAN definition itself is missing |
| `interfaces[].switchport_mode` | not_applicable | Parse-side gap: `switched-vlan` augment ignored |
| `interfaces[].access_vlan` | not_applicable | Same |
| `interfaces[].trunk_allowed_vlans` | not_applicable | Same |
| `interfaces[].trunk_native_vlan` | not_applicable | Same |
| `interfaces[].voice_vlan` | not_applicable | Same |

## When this flips

Once the cisco_iosxe parser walks `<vlans>` and the
`switched-vlan` augment, these `not_applicable` rows flip to:

* `good` for `vlans[].id`, `vlans[].name` (canonical-stable surface;
  Arista accepts both fields).
* `lossy` for `vlans[].name` if Arista's name constraints differ
  from OpenConfig (Arista allows underscores; OpenConfig accepts
  any string).
* `good` for switchport fields (Arista deliberately mirrors Cisco
  CLI; canonical maps cleanly).
