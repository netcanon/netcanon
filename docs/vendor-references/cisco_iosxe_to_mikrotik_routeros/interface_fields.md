# Interface canonical-core fields — cisco_iosxe (NETCONF) source to RouterOS target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet)
Retrieved: 2026-05-01

Source: [Interface — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328068/Interface)
Retrieved: 2026-05-01

## Per-field disposition

This is the only canonical category where the cisco_iosxe NETCONF
source carries non-trivial data.  Per-field dispositions mirror the
sibling `cisco_iosxe_cli__mikrotik_routeros` pair where the field
is parsed, and degrade to `not_applicable` where the NETCONF stub's
parser does not extract the field.

| Canonical field | Parsed by cisco_iosxe? | Disposition |
|---|---|---|
| `name` | yes | good (with rename mesh) |
| `description` | yes | good |
| `enabled` | yes | good |
| `interface_type` | yes (IANA ident verbatim) | lossy (RouterOS infers from name) |
| `mtu` | parsed into dict, dropped at canonical bridge | lossy (deferred wire-through) |
| `ipv4_addresses` | yes | good |
| `ipv6_addresses` | yes (scope hard-coded global) | lossy (link-local mis-classified) |
| `switchport_mode` | no | not_applicable |
| `access_vlan` | no | not_applicable |
| `trunk_allowed_vlans` | no | not_applicable |
| `trunk_native_vlan` | no | not_applicable |
| `voice_vlan` | no | not_applicable |
| `lag_member_of` | no | not_applicable |
| `dhcp_client` | no | not_applicable |
| `vrf` | no | not_applicable |
| `default_name` | no | not_applicable |

## Naming bridge

Cisco IOS-XE names are speed-encoded
(`GigabitEthernet0/0/1`, `TenGigabitEthernet1/0/1`,
`HundredGigE0/0/0`, `FortyGigE0/0/0`).  RouterOS names are flat
positional with optional default-name binding (`ether1`, `ether24`,
`sfp-sfpplus1`, `qsfp-1-1`).  The cross-vendor port-rename mesh
canonicalises the Cisco `<name>` element through to a RouterOS
`default-name=` selector for the `set [find default-name=...]`
idiom, plus a free-form `name=` if the operator wants to preserve
some hint of the Cisco naming.

When the rename mesh is not consulted (raw end-to-end render), the
literal Cisco name reaches the RouterOS render as-is and the device
will accept the configuration but the operator-visible interface name
will look incongruous (e.g. `GigabitEthernet0/0/1` set as a RouterOS
interface name).

## Interface-type inference asymmetry

The cisco_iosxe codec on parse populates `interface_type` from the
IANA ident text in `<config><type>`.  The MikroTik render does NOT
emit a corresponding directive — RouterOS has no IANA-ident concept;
its parser re-derives the type from the interface-name prefix
(etherN -> ethernetCsmacd, vlanN -> l3ipvlan, bondN -> ieee8023adLag,
empty bridge with /ip address -> softwareLoopback).

For most types this round-trip is harmless: `ethernetCsmacd` is the
default for ethN names; `softwareLoopback` is correctly inferred for
loopback-named interfaces; `ieee8023adLag` is correctly inferred for
bond-named interfaces.  The asymmetry surfaces when the original
cisco_iosxe source uses a name that does not match the RouterOS
inference table — e.g. a Loopback-typed interface named
`Loopback0` becomes a RouterOS interface called `Loopback0` whose
type is then re-inferred as `ethernetCsmacd` (because RouterOS has
no Loopback-prefix rule).  This forces the operator to either
rename the interface to a RouterOS-conventional pattern or accept
the type misclassification.

Disposition: `lossy` for `interface_type` end-to-end.

## IPv6 link-local handling

Per `openconfig_yang_scope.md`: the cisco_iosxe parser hard-codes
`scope="global"` on every parsed IPv6 address.  RouterOS treats
link-local addresses (`fe80::/10`) under a separate `link-local=yes`
flag on `/ipv6 address`; if the canonical record arrives flagged
`global` for an `fe80::` literal, the RouterOS render emits a
contradictory configuration that may be rejected.

In practice this is rarely triggered — IPv6 link-local addresses are
auto-derived per RFC 4291 from the interface MAC, and rarely declared
explicitly in source configuration.  But operators carrying explicit
`fe80::` addresses in source XML should set them aside for manual
review on the cross-pair migration.

Disposition: `lossy` for `ipv6_addresses` because of the scope-flag
hard-coding upstream of this cross-pair.

## MTU deferred

The cisco_iosxe codec parses `<config><mtu>` into the intermediate
dict but does not carry it through to `CanonicalInterface.mtu`.
Even though `<config><mtu>` is well-formed YANG and the MikroTik
codec accepts MTU on its `/interface ethernet set mtu=...` directive,
the cross-pair MTU value drops because it never reaches the canonical
tree.  Disposition: `lossy` with reason "deferred — cisco_iosxe
canonical-bridge wire-through gap".
