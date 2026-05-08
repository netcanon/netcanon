# OpenConfig YANG scope — what the cisco_iosxe target codec actually emits

Source: [Native, IETF, OpenConfig... Why so many YANG models? (Cisco Blogs)](https://blogs.cisco.com/developer/which-yang-model-to-use)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: `netconfig.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec._render_canonical`
(in-tree code; the authoritative source of "what the render emits")
Retrieved: 2026-05-01

## Three YANG model families on Cisco IOS-XE

Cisco IOS-XE devices expose three coexisting YANG model families on
the NETCONF datastore:

* **OpenConfig YANG** — vendor-neutral models (`openconfig-interfaces`,
  `openconfig-vlan`, `openconfig-network-instance`,
  `openconfig-system`).  Cross-vendor stable surface.  Maintained at
  `https://openconfig.net/projects/models/`.
* **IETF YANG** — RFC-standardised models (`ietf-interfaces`,
  `ietf-system`).  Less commonly used in operator workflows.
* **Cisco-IOS-XE-native YANG** — the Cisco-proprietary models
  mirroring `running-config` 1:1 (`Cisco-IOS-XE-native`,
  `Cisco-IOS-XE-snmp`, `Cisco-IOS-XE-bgp`).  Mirrored on GitHub at
  `https://github.com/YangModels/yang/tree/main/vendor/cisco/xe/`.

The `cisco_iosxe` codec in Netcanon targets the **OpenConfig** branch
exclusively.  It does NOT bridge into Cisco-IOS-XE-native YANG.  This
is a deliberate scoping choice — OpenConfig gives cross-vendor
portability that native YANG would sacrifice.

## What the cisco_iosxe codec's render emits

The `_render_canonical()` body walks `intent.interfaces` only.  For
each `CanonicalInterface` it emits exactly:

* `<interface><name>` (key)
* `<config><name>` (mandatory copy of the key)
* `<config><description>` (when non-empty)
* `<config><enabled>` (always — YANG boolean)
* `<config><type>` (when non-empty — IANA interface-type ident)
* `<subinterfaces><subinterface><index>0</index>` (only when there
  are addresses)
* `<ipv4><addresses><address>` per IPv4 address (`openconfig-if-ip`
  namespace)
* `<ipv6><addresses><address>` per IPv6 address (same namespace)

Notably absent:

* No `<vlans>` (top-level OpenConfig VLAN list)
* No `<network-instances>` (VRFs, static routes, BGP, EVPN)
* No `<system>` (hostname, DNS, NTP, syslog, AAA users)
* No `<snmp>` (community, location, contact, v3 users)
* No `openconfig-vlan:switched-vlan` augment under `<ethernet>`
  (interface switchport state)
* No `openconfig-if-aggregate:aggregate-id` leaf (LAG membership)
* No `<config><mtu>` leaf (parsed lossily; render path drops it)

## Why the matrix declares more than the render emits

The codec's CapabilityMatrix lists `/system/hostname`, `/system/dns-server`,
`/system/ntp-server`, `/vlans/vlan/id`, `/vlans/vlan/name`,
`/routing/static-route`, `/snmp/community`, `/snmp/location`,
`/snmp/contact`, `/snmp/trap-host` under `supported`.  These
declarations are **aspirational**: they exist so cross-codec mesh
translations don't classify the paths as `unsupported` on the target
side, allowing the orchestration layer's drift matrix to distinguish
"this path is supported but the codec hasn't wired up its render yet"
from "this path is genuinely unsupported on this vendor".

For per-pair fidelity expectations (this YAML), honesty beats
matrix-deference: when the render path doesn't actually walk the
canonical field, the disposition here is `unsupported` with a reason
calling out the render-side wire-up gap.

## Operator implication

For Arista EOS sources targeting a Cisco IOS-XE device, the typical
campus / DC migration workflow wants the full `running-config` (with
hostname, VLANs, RADIUS, SNMP, local users, EVPN/VXLAN if applicable)
and should route through `cisco_iosxe_cli` (the certified CLI codec).
Use this NETCONF pair only when the downstream consumer is a
programmable orchestrator that takes OpenConfig and applies
non-interface state out-of-band.

## Disposition

For the interfaces subtree fields that DO survive: see
`interface-fields.md`.  For everything else: `unsupported` with the
render-gap reason.
