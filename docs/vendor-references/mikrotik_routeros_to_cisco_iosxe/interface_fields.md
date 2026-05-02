# Interface canonical-core fields — RouterOS source to cisco_iosxe NETCONF target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
Retrieved: 2026-05-01

Source: [Interface — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328068/Interface)
Retrieved: 2026-05-01

## Per-field disposition

This is the only canonical category where the cisco_iosxe NETCONF
target render DOES emit XML.  The MikroTik source carries a fully-
populated set of CanonicalInterface records, including switchport
membership / LAG membership / VRF / DHCP-client fields that the
target render does not walk.

| Canonical field | RouterOS source populates? | cisco_iosxe target emits? | Disposition |
|---|---|---|---|
| `name` | yes | yes | good (with rename mesh) |
| `description` | yes (`comment=`) | yes | good |
| `enabled` | yes (`disabled=` inverted) | yes | good |
| `interface_type` | yes (inferred from name) | yes (verbatim) | lossy |
| `mtu` | yes | no (canonical-bridge wire-through gap) | lossy |
| `ipv4_addresses` | yes (from `/ip address`) | yes | good |
| `ipv6_addresses` | yes (from `/ipv6 address`) | yes (scope dropped on render) | lossy |
| `switchport_mode` | partial (Plane-2 parsing only) | no (render gap) | unsupported |
| `access_vlan` | partial | no (render gap) | unsupported |
| `trunk_allowed_vlans` | partial | no (render gap) | unsupported |
| `trunk_native_vlan` | partial | no (render gap) | unsupported |
| `voice_vlan` | no | no | not_applicable |
| `lag_member_of` | yes (from `/interface bonding slaves=`) | no (render gap) | unsupported |
| `dhcp_client` | yes (from `/ip dhcp-client`) | no (render gap) | unsupported |
| `vrf` | no (RouterOS VRF parsing not yet wired) | no (matrix declares unsupported) | not_applicable |
| `default_name` | yes (RouterOS-specific) | no (RouterOS-only concept) | not_applicable |

## Naming bridge

RouterOS names are flat positional (`ether1`, `ether24`, `sfp-sfpplus1`,
`bond1`, `vlan10`).  Cisco IOS-XE OpenConfig names are speed-encoded
(`GigabitEthernet0/0/1`, `TenGigabitEthernet1/0/1`).  The cross-vendor
port-rename mesh translates each to a Cisco-conventional name; without
the mesh, the literal RouterOS name (e.g. `ether1`) lands on the wire,
and a real Cisco device would reject the edit-config because IOS-XE
interface names must match the hardware layout.

The `default_name` discriminator (RouterOS factory binding for the
`set [find default-name=...]` idiom) has no Cisco analogue and drops
to `not_applicable`.  Cisco does not have an equivalent two-name
model — the hardware position IS the name.

## Interface-type inference asymmetry

The MikroTik codec on parse infers `interface_type` from the
interface-name prefix:

* `etherN` -> `ethernetCsmacd`
* `vlanN` -> `l3ipvlan` (RouterOS-specific IANA-near ident)
* `bondN` -> `ieee8023adLag`
* empty bridge with `/ip address` -> `softwareLoopback` (loopback
  emulation pattern)

The cisco_iosxe target render emits this verbatim as the IANA ident
in `<config><type>`.  An asymmetry surfaces with the RouterOS `vlanN`
inference: the canonical record carries `l3ipvlan`, while OpenConfig
on Cisco devices conventionally uses `l2vlan` for SVI interfaces.
A downstream OpenConfig consumer might accept the literal but
classify the interface differently than expected.

Disposition: `lossy` for `interface_type` end-to-end because of this
inference / classification asymmetry.

## IPv6 link-local handling

RouterOS distinguishes link-local from global addresses via a
separate `link-local=yes` flag on `/ipv6 address`.  The MikroTik
parser sets `CanonicalIPv6Address.scope = "link-local"` for these
records and `"global"` otherwise.

The cisco_iosxe target render emits IPv6 addresses without examining
the scope field — every parsed address goes into the `<ipv6>` block
under the subinterface, with no `link-local` discriminator.  A
downstream OpenConfig consumer treats every emitted address as
global.

Disposition: `lossy` for `ipv6_addresses` because the scope flag is
discarded on render.

## MTU and DHCP-client deferred

`mtu`: the canonical-bridge wire-through is not yet implemented in the
cisco_iosxe codec — `intent.interfaces[].mtu` does not drive the
`<config><mtu>` emission.  This is documented as
`LossyPath("/interfaces/interface/config/mtu")` in the matrix.

`dhcp_client`: OpenConfig has a DHCP-client augment under
`openconfig-if-ip` but the cisco_iosxe render does not walk it.
Disposition: `unsupported` with reason "render-side wire-up gap".
