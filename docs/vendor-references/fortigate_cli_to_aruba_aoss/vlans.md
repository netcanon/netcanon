# VLAN configuration: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/vlans.md`](../aruba_aoss_to_fortigate_cli/vlans.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate Cookbook — VLAN configuration](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) (`config system interface / set type vlan`).
Retrieved: 2026-04-30

FortiGate models VLANs as **child interfaces** hanging off a
parent (physical or aggregate); there is no first-class `vlan`
global object:

```
config system interface
    edit "agg1.100"
        set alias "data-vlan-100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
        set ip6-address 2001:db8:100::1/64
        set status up
    next
    edit "VL_200"
        set alias "voice-vlan-200"
        set vlanid 200
        set interface "agg1"
        set ip 10.200.0.1 255.255.255.0
        set status up
    next
end
```

Notable FortiOS specifics:

- **No global VLAN object.**  VLAN identity is carried by the
  child-interface edit ID + `set vlanid` numeric.
- **No port list per VLAN.**  L2 trunking is expressed by
  configuring multiple VLAN child interfaces on the same parent.
  The parent encodes membership through its edit name only, NOT
  through a port list.
- **VLAN name = edit ID** by convention.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
vlan 100
   name "data-vlan-100"
   tagged 23-24
   ip address 10.100.0.1/24
   exit
vlan 200
   name "voice-vlan-200"
   tagged 23-24
   ip address 10.200.0.1/24
   exit
```

Membership is **VLAN-centric**: the VLAN stanza enumerates the
port lists with `tagged` / `untagged` directives.  See
[`../aruba_aoss_to_fortigate_cli/vlans.md`](../aruba_aoss_to_fortigate_cli/vlans.md)
for full Aruba specifics.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalVlan(BaseModel):
    id: int
    name: str = ""
    description: str = ""
    tagged_ports: list[str]
    untagged_ports: list[str]
    ipv4_addresses: list[CanonicalIPv4Address]
```

- **id** — `good` when the FortiGate source carries an explicit
  `set type vlan / set vlanid <N>` child interface.  Direct
  preservation.
- **name** — `lossy`.  FortiGate uses the edit ID as identity
  (`agg1.100` / `VL_200`); Aruba renders `vlan 100 / name "VL_200"`
  which is mechanical but not operator-readable.
- **description** — `lossy`.  FortiGate carries no per-VLAN
  description (only `set alias` on the child interface, which
  lands on `CanonicalInterface.description`, not
  `CanonicalVlan.description`).
- **tagged_ports / untagged_ports** — `unsupported`.  This is
  the hard model-translation gap on this direction: FortiGate's
  child-interface model encodes membership via the parent's
  identity, NOT as a port list per VLAN.  FortiGate parse leaves
  `CanonicalVlan.tagged_ports` / `untagged_ports` empty.  Aruba
  render emits VLAN stanzas with empty port lists, so the
  operator must manually populate `tagged <port-list>` /
  `untagged <port-list>` post-migration.
- **ipv4_addresses (SVI absorption)** — `good`.  FortiGate VL-iface
  `set ip` populates canonical; Aruba renders as
  `ip address X/N` inside the VLAN stanza
  (`absorbs_svi_into_vlan = True`).

Disposition: **lossy**.  Reason: FortiGate's parent-interface VLAN
model carries no canonical port-membership intent, so Aruba render
emits structurally incomplete VLAN stanzas.
