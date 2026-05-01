# Interface naming: MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Sources:
- [Ethernet ports — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
- [Bridge — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328088/Bridge)

Retrieved: 2026-04-30

RouterOS factory defaults:

```
ether1, ether2, ..., etherN              (electrical / SFP combos)
sfp-sfpplus1, sfp-sfpplus2, ...          (SFP+ 10G)
qsfpplus1-1, ..., qsfpplus<n>-<lane>     (QSFP+ break-out, 40G/100G)
wlan1, wlan2                             (wireless radios)
bridge1, bridge2                         (software bridges)
vlan10, vlan20                           (VLAN pseudo-interfaces)
bond1, bond2                             (bonding / LAG)
```

`/export` of a renamed interface preserves the factory default-name
binding so the rename can be re-applied to a fresh chassis:

```
/interface ethernet
set [ find default-name=ether1 ] name="WAN uplink"
set [ find default-name=ether2 ] comment="LAN trunk"  disabled=no
```

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)

Cisco encodes media speed in the prefix:

```
interface GigabitEthernet0/0/1
interface TenGigabitEthernet0/0/49
interface TwentyFiveGigE0/0/49
interface FortyGigE0/0/49
interface HundredGigE0/0/49
interface Loopback0
interface Vlan100
interface Port-channel10
```

The prefix is operator-immutable (you cannot rename `Gigabit
Ethernet0/0/1` to `WAN`); description fields carry operator notes.

## Cross-vendor mapping

The canonical surface is `CanonicalInterface.name` plus a
`default_name` discriminator that MikroTik populates from the
`find default-name=` lookup.  `default_name` is empty for vendors
that don't have the concept (Cisco, Arista, Junos).

### MikroTik -> Cisco direction

The structural loss is one-way:

- The operator-friendly free-form name `"WAN uplink"` cannot
  survive on Cisco — Cisco interface names are fixed by the
  hardware layout.  Cross-vendor migration converts the operator
  name to a description (`description WAN uplink`) and replaces
  the in-band name with `GigabitEthernet0/0/1` (or whatever the
  rename mesh chooses).
- The `default_name=ether1` binding is meaningless to Cisco — it
  drops on render.  Round-tripping back to RouterOS would rebuild
  the binding from the rename mesh's declared mapping, NOT the
  parsed input.

For position-stable renames (Cisco-name to RouterOS-name) operators
configure the rename mesh; the canonical model preserves the
operator-form name verbatim so the override surface has a stable
input.

### Loopback

RouterOS has no first-class loopback; operators emulate via a
zero-member `bridge` with an `/ip address` on it.  The MikroTik
codec parses such bridges as `interface_type="softwareLoopback"`
when the operator-form name suggests it (e.g. `loopback`,
`Loopback0`).  On Cisco render this lands as `interface
Loopback<N>` cleanly.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `interfaces[].name` | lossy (free-form RouterOS name -> Cisco hardware-fixed prefix; rename mesh handles, semantic preserved as `description`) |
| `interfaces[].interface_type` | lossy (codec inference from name prefix; both codecs flag) |
| `interfaces[].default_name` | not_applicable (Cisco does not model the binding) |
