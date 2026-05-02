# Cisco IOS-XE OpenConfig NETCONF to FortiGate FortiOS CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__fortigate_cli.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This is the **Cisco IOS-XE OpenConfig NETCONF source -> FortiGate
FortiOS CLI target** direction.  Distinct from the sibling pair
`../cisco_iosxe_cli_to_fortigate_cli/`: the source codec here is the
`cisco_iosxe` codec (OpenConfig NETCONF YANG XML), NOT
`cisco_iosxe_cli` (operator-paste running-config text).  The two Cisco
codecs target the same device family (Catalyst 9K / ISR / ASR) but
different wire formats:

| Source codec | Wire format | Certification |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | `certified` |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `best_effort` (Phase-0.5 stub) |

## Direction-specific framing

The dominant fact for this pair is that the `cisco_iosxe` source
codec's `parse()` only populates a NARROW subset of the canonical
intent — the `intent.interfaces` list with name / description /
enabled / interface_type / IPv4 addresses / IPv6 addresses.  The
parser walks `<interfaces>` only and does NOT read the OpenConfig
`<system>` (hostname, DNS, NTP, syslog), `<network-instances>`
(VRF, static-routes, VLANs), `<snmp>`, `<aaa>` (local-users, RADIUS),
`<openconfig-if-aggregate>` (LAGs), or DHCP subtrees that a real
device's `<get-config>` reply would carry.

Combined with the firewall-target asymmetry (FortiGate's primary
product surface — firewall policy / NAT / VPN / UTM — has no
canonical representation), this pair shows two structurally distinct
categories of loss:

1. **`not_applicable`** — fields the canonical model holds but the
   `cisco_iosxe` parser never populates.  These dominate the surface:
   hostname, domain, dns_servers, ntp_servers, syslog_servers, vlans,
   static_routes, snmp, lags, local_users, radius_servers, dhcp_servers,
   routing_instances are all empty after parse.  Nothing reaches the
   FortiGate render to drop.  Disposition is `not_applicable` (source
   structurally absent) rather than `lossy` (would imply data was
   dropped).
2. **`unsupported`** — FortiGate-side product surfaces (firewall
   policy, NAT, VIP, UTM, VDOM) that have no canonical representation.
   Aspirational from the operator's perspective ("after migrating
   the OpenConfig surface, configure these manually") but not
   modelled.

The pair is appropriate ONLY for the narrow case where the upstream
orchestrator has already gathered system / VLAN / static-route /
SNMP / users / RADIUS data via a separate channel (e.g. the
device's `cisco_iosxe_cli` running-config) and is using
`cisco_iosxe` -> `fortigate_cli` for the interface-only sub-step.
For a full Cisco router/switch -> FortiGate edge migration, route
through `cisco_iosxe_cli` instead — that pair is `certified` on
the source side and emits the full canonical surface.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig_yang_scope.md` | What the `cisco_iosxe` parser populates from a NETCONF reply | The narrow `<interfaces>`-only walk, with structural framing |
| `interface_fields.md` | Per-field disposition for the interface canonical core | The only fields with `good` disposition on this direction |
| `ipv6_addresses.md` | OpenConfig IPv6 augment -> FortiOS `set ip6-address` | Link-local scope mismatch is the only nuance |
| `vlan_render_gap.md` | NETCONF source carries no VLAN intent -> FortiGate VLAN render | `not_applicable` dispositions across the board |
| `snmp_render_gap.md` | NETCONF parser doesn't read `<snmp>` -> FortiGate SNMP render | Doubly-deferred: both v1/v2c and v3 |
| `vxlan_evpn_gap.md` | VXLAN / EVPN / VRF — both codecs decline | Matrix-declared unsupported on both sides |
| `firewall_unsupported.md` | FortiGate firewall / NAT / UTM with no canonical analogue | Forward direction: source carries no firewall, target has no canonical hook |

## Re-fetch notes

OpenConfig models cited here live at
`https://openconfig.net/projects/models/`; specific YANG modules are
mirrored on GitHub at
`https://github.com/openconfig/public/tree/master/release/models`.
FortiOS CLI Reference is sourced from
`https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/`
(7.4 train).  Cisco IOS-XE Programmability Configuration Guide for
NETCONF/OpenConfig is sourced from `https://www.cisco.com/c/en/us/td/`.

See also: `../fortigate_cli_to_cisco_iosxe/_INDEX.md` (reverse
direction) and `../README.md` (citation cache layout).
