# Interfaces and IP addressing: MikroTik RouterOS versus Arista EOS

## MikroTik RouterOS

Sources:
- [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
- [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-05-01

```
/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink to ISP" disabled=no mtu=1500
set [ find default-name=ether2 ] comment="LAN trunk - bridge member" disabled=no mtu=1500

/interface bridge
add comment="Primary LAN bridge" name=bridge1
add comment="Loopback emulation" name=loopback-bridge

/interface vlan
add comment="Users VLAN" interface=bridge1 name=vlan100 vlan-id=100

/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.0.0.1/24 interface=bridge1
add address=10.255.0.1/32 interface=loopback-bridge
add address=10.100.0.1/24 interface=vlan100

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
```

RouterOS interface naming is **flat without a speed prefix**:
`ether1` / `ether2` for copper, `sfp-sfpplus1` for SFP+, etc.
The `default-name=` lookup uses the factory binding to address
ports without affecting their operator-renamed name.

Operator-friendly free-form names are stored in the `comment=`
attribute — NOT the `name=` attribute.  The `name=` attribute is
the wire identity (e.g. `ether1`, `bond1`, `vlan100`) and is
constrained to RouterOS's naming rules.

Loopback emulation: RouterOS has no first-class loopback
concept.  Conventional form is an empty `/interface bridge` with
no port members, plus `/ip address add address=10.255.0.1/32
interface=loopback-bridge`.

VLAN sub-interfaces use `/interface vlan name=vlanN
interface=<parent> vlan-id=N`.

PPPoE / wireless / hotspot / virtual-ethernet / WireGuard /
OVPN / L2TP / PPP interfaces are RouterOS-rich; they have no
canonical scope and no Arista analogue.

## Arista EOS

Source: [Arista EOS — Interface Configuration](https://www.arista.com/en/um-eos/eos-interface-configuration)
Retrieved: 2026-05-01

```
interface Ethernet1
   description "WAN uplink to ISP"
   no switchport
   mtu 1500
   ip address 198.51.100.2/30
   ipv6 address 2001:db8:0:1::2/64
   ipv6 address fe80::1 link-local
!
interface Loopback0
   description "Loopback emulation"
   ip address 10.255.0.1/32
!
interface Vlan100
   description "Users VLAN"
   ip address 10.100.0.1/24
!
```

Arista interface naming is **flat without a speed prefix**:
`Ethernet1` is the bare wire name regardless of port speed.
Stack / chassis members use `Ethernet<unit>/<slot>/<port>`.
Loopback / Management / SVI interfaces are first-class with
explicit role-bearing names (`Loopback<N>`, `Management<N>`,
`Vlan<N>`).

L3 routed mode is opt-in via `no switchport` — a port defaults
to L2 access mode unless explicitly converted.

IPv4 / IPv6 addressing is **on-interface** (Arista does not have
the decoupled `/ip address` section RouterOS has).  Multiple
addresses per interface are supported.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.interfaces:
list[CanonicalInterface]` with name / default_name / description
/ enabled / interface_type / mtu / ipv4_addresses /
ipv6_addresses / switchport_* / vrf etc.

RouterOS -> Arista round-trip:

* RouterOS `[ find default-name=ether1 ] comment="WAN uplink"`
  populates `name="ether1"`, `default_name="ether1"`,
  `description="WAN uplink"`.  Cross-vendor port-name mesh maps
  `ether1` -> `Ethernet1`; the codec emits `interface Ethernet1
  / description "WAN uplink"`.
* RouterOS operator-friendly free-form names (e.g. `name="WAN
  uplink"` on a renamed port) cannot survive on Arista —
  Arista's interface names are fixed by hardware layout.  Cross-
  vendor migration converts the operator name to an Arista
  `description` and replaces the in-band name with the rename-
  mesh-chosen Arista identity.
* `default_name=ether1` discriminator drops on Arista render
  (Arista has no factory-default-name concept).
* RouterOS `mtu=1500` -> Arista `mtu 1500`.
* RouterOS `/ip address add address=198.51.100.2/30
  interface=ether1` -> Arista `ip address 198.51.100.2/30` on
  the `interface Ethernet1` block.
* RouterOS `/ipv6 address add address=fe80::1/64 interface=
  ether1 advertise=no` (link-local) -> Arista `ipv6 address
  fe80::1 link-local`.  The `scope=link-local` discriminator is
  preserved through the canonical model.

**Loopback emulation:**

RouterOS empty-bridge form (`/interface bridge add name=
loopback-bridge` + `/ip address add interface=loopback-bridge`)
lifts cleanly to Arista's first-class `interface Loopback<N>`
via interface_type inference.  The codec recognises the empty-
bridge-with-loopback-address pattern and emits Arista's native
form.

**VLAN sub-interfaces:**

RouterOS `/interface vlan name=vlan100 interface=bridge1
vlan-id=100` + `/ip address add address=10.100.0.1/24
interface=vlan100` -> Arista `interface Vlan100 / ip address
10.100.0.1/24`.  SVI absorption handles both directions; the
Arista form is more compact (single block) but semantic-
equivalent.

**RouterOS-rich interfaces:**

PPPoE / wireless / hotspot / WireGuard / OVPN / L2TP / PPP
interfaces have no Arista analogue.  These drop from the
canonical scope on RouterOS parse (the codec does not populate
them) and are absent from the Arista render.  See
`firewall_unsupported.md` for the full itemisation of RouterOS-
only surfaces.

Disposition: **lossy** — see the YAML for the per-field
breakdown.  Loopback and VLAN-SVI lift cleanly via the parser/
renderer's pattern-matching; physical-Ethernet attributes round-
trip cleanly; RouterOS-only interface kinds drop.
