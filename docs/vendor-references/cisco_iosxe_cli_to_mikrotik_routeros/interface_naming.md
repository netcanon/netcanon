# Interface naming: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: [Cisco IOS Interface and Hardware Component Command Reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)

Cisco IOS-XE encodes media speed in the interface-name prefix:

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

The prefix carries operational-speed information (`Gigabit`,
`TenGigabit`) that the OS uses for default-MTU and licensing decisions.

## MikroTik RouterOS

Sources:
- [Ethernet ports — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
- [Bridge — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328088/Bridge)

Retrieved: 2026-04-30

RouterOS uses speed-agnostic, position-encoded names with optional
operator-renaming via the `/export` `set [ find default-name=X ]`
idiom.  Factory defaults follow port type:

```
ether1, ether2, ..., etherN              (electrical / SFP combos)
sfp-sfpplus1, sfp-sfpplus2, ...          (SFP+ 10G)
qsfpplus1-1, ..., qsfpplus<n>-<lane>     (QSFP+ break-out, 40G/100G)
wlan1, wlan2                             (wireless radios)
bridge1, bridge2                         (software bridges)
vlan10, vlan20                           (VLAN pseudo-interfaces)
bond1, bond2                             (bonding / LAG)
lo (loopback aliasing through bridge)    (no first-class loopback)
```

Operators almost always rename, e.g.

```
/interface ethernet
set [ find default-name=ether1 ] name="WAN uplink"
set [ find default-name=ether2 ] comment="LAN trunk"
```

The `default-name` survives in the export so the rename can be
re-applied to a factory-reset device by serial.

## Cross-vendor mapping

The canonical surface stores the operator-form name verbatim
(`CanonicalInterface.name`) plus a `default_name` discriminator that
MikroTik populates from the `find default-name=` lookup.  Cross-vendor
migration uses the rename mesh (the per-pane port-name override surface)
to map between schemes.

Two information-loss directions:

- **Cisco -> MikroTik**: Cisco's speed-encoded prefix
  (`GigabitEthernet0/0/1`, `TenGigabitEthernet0/0/49`) maps to
  MikroTik's flat `etherN` / `sfp-sfpplus<N>` numbering.  The speed
  hint is preserved on the canonical side via `interface_type`
  inference but the rendered MikroTik name does not carry the
  operational speed in-band.  Operators using the rename mesh can
  carry their own naming convention through.
- **MikroTik -> Cisco**: RouterOS's flat `etherN` does not encode
  speed — the codec defaults to a `GigabitEthernet` prefix when
  rendering, which can understate the link speed for SFP+ /
  QSFP+ ports.

Loopback is a shape mismatch: Cisco has a first-class `Loopback<N>`
interface family; RouterOS does not — operators emulate via a
`bridge` with no member ports + `/ip address` on it, which the
canonical model carries as `interface_type="softwareLoopback"`
but the MikroTik render emits as a bridge.

VLAN SVIs (`interface Vlan100` on Cisco) versus
`/interface vlan add name=vlan100 vlan-id=100 interface=bridge1`
on RouterOS — a structural difference that lives in the VLAN
plane, not the interface plane.  See `vlans.md` for the VLAN-side
treatment; the interface-name field is good enough on its own
(canonical-portable) but the surrounding semantic differs.

### Disposition

`interfaces[].name` is **lossy** in both directions because the
naming-scheme mismatch is not symmetric: speed-prefix info is lost
Cisco -> MikroTik, default-name binding is lost MikroTik -> Cisco
(Cisco has no `find default-name=` form to reconstitute renames
on a fresh chassis).

`interfaces[].interface_type` is **lossy** by both codecs'
capability matrices (each codec lists `/interfaces/interface/config/
type` under `lossy` with the rationale that the IANA ifType is
inferred from the name prefix, not declared on the wire).
