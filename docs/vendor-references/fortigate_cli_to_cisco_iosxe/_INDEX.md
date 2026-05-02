# FortiGate FortiOS CLI to Cisco IOS-XE OpenConfig NETCONF — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/fortigate_cli__cisco_iosxe.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This is the **FortiGate FortiOS CLI source -> Cisco IOS-XE OpenConfig
NETCONF target** direction.  Distinct from the sibling pair
`../fortigate_cli_to_cisco_iosxe_cli/`: the target codec here is the
`cisco_iosxe` codec (OpenConfig NETCONF YANG XML), NOT
`cisco_iosxe_cli` (operator-paste running-config text).  The two Cisco
codecs target the same device family (Catalyst 9K / ISR / ASR) but
different wire formats:

| Target codec | Wire format | Certification |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | `certified` |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `best_effort` (Phase-0.5 stub) |

## Direction-specific framing

This direction has the OPPOSITE asymmetry from the forward direction:

* **Forward (`cisco_iosxe -> fortigate_cli`)**: source parser is the
  bottleneck; Cisco NETCONF parser walks `<interfaces>` only, so
  most canonical fields are empty after parse and disposition is
  `not_applicable`.
* **Reverse (this pair, `fortigate_cli -> cisco_iosxe`)**: target
  renderer is the bottleneck; FortiGate parser populates the full
  canonical surface (hostname, DNS, NTP, VLANs, static_routes,
  SNMP v1/v2c/v3, RADIUS, local users, LAGs, DHCP server pools),
  but the cisco_iosxe NETCONF render only walks `intent.interfaces`
  and emits the openconfig-interfaces subtree.  Everything else is
  silently dropped on render.

The result: the FortiGate source typically carries 5-10x more
content than the cisco_iosxe target can re-emit.  Disposition for
those fields is `unsupported` (with reason citing render-side
wire-up gap), NOT `not_applicable` — the source codec produces
data, and the canonical layer carries it; the loss happens at the
cisco_iosxe render boundary.

Plus: FortiGate's primary product surface — firewall policy / NAT /
VIP / UTM — has no canonical representation in v1 and no Cisco
target equivalent (Cisco IOS-XE ACL / ZBF / NAT model semantically
different).  This is `not_applicable` (canonical schema gap; not
a render-side decision) but called out for operator awareness.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig_yang_scope.md` | What the cisco_iosxe target render emits (the narrow subset) | Same render boundary as the forward direction's parser-side gap |
| `interface_fields.md` | Per-field disposition for the interface canonical core | Some lossy classifications mirror the forward direction |
| `ipv6_addresses.md` | FortiOS `set ip6-address` -> OpenConfig IPv6 augment | Link-local scope mismatch is the only nuance |
| `vlan_render_gap.md` | FortiGate VLAN child interfaces -> NETCONF VLAN render | All FortiGate VLAN intent dropped on cisco_iosxe render |
| `snmp_render_gap.md` | FortiGate SNMP intent -> cisco_iosxe SNMP render | All v1/v2c + v3 dropped on render |
| `vxlan_evpn_gap.md` | VXLAN / EVPN / VRF — both codecs decline | Matrix-declared unsupported on both sides |
| `firewall_unsupported.md` | FortiGate firewall / NAT / UTM as source intent with no canonical | Reverse direction has the data, but canonical is silent |

## Re-fetch notes

OpenConfig models cited here live at
`https://openconfig.net/projects/models/`; specific YANG modules are
mirrored on GitHub at
`https://github.com/openconfig/public/tree/master/release/models`.
FortiOS CLI Reference is sourced from
`https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/`
(7.4 train).  Cisco IOS-XE Programmability Configuration Guide for
NETCONF/OpenConfig is sourced from `https://www.cisco.com/c/en/us/td/`.

See also: `../cisco_iosxe_to_fortigate_cli/_INDEX.md` (forward
direction) and `../README.md` (citation cache layout).
