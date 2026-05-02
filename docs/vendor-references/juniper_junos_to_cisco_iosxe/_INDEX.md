# Juniper Junos to Cisco IOS-XE OpenConfig NETCONF — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/juniper_junos__cisco_iosxe.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This is the **Juniper Junos source-rich -> Cisco OpenConfig NETCONF
target** direction.  Distinct from the sibling pair
`../juniper_junos_to_cisco_iosxe_cli/`: the target codec here is the
`cisco_iosxe` codec (NETCONF/OpenConfig YANG XML, Phase-0.5 stub),
NOT `cisco_iosxe_cli` (operator-paste running-config, certified).

The two Cisco codecs target the same device family but the render
surface is sharply different:

| Target codec | Wire format | Render coverage |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | Full canonical surface (certified) |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `<interfaces>` only (best_effort stub) |

## Direction-specific framing

The dominant fact for this pair is that the `cisco_iosxe` TARGET
codec's `_render_canonical()` only walks `intent.interfaces`.  Even
when the canonical tree from the Junos parser carries a populated
`hostname`, `dns_servers`, `ntp_servers`, `syslog_servers`,
`timezone`, `vlans`, `vxlan_vnis`, `routing_instances`,
`evpn_type5_routes`, `snmp` (community + v3_users), `local_users`,
`radius_servers`, `lags`, `static_routes`, the render emits NOTHING
for those subtrees.  The cisco_iosxe codec walks `intent.interfaces`
and emits a bare `<interfaces>` element with the openconfig
namespace — that's it.

This direction is the mirror of `../cisco_iosxe_to_juniper_junos/`:

* Forward (cisco_iosxe -> juniper_junos): parse-side gap dominates
  -> `not_applicable` skew on cross-pair.
* Reverse (juniper_junos -> cisco_iosxe): render-side gap dominates
  -> `unsupported` skew on cross-pair.

Schematically different, operationally identical (data not in
output).  The labelling distinction is load-bearing: "fix the
cisco_iosxe render to walk intent.snmp" is mechanically different
from "wait for Junos source to grow VXLAN" (which already happened
— Junos source is fully wired, the gap is purely on Cisco render).

The Junos source codec is among the richest in the repo: it
populates hostname, DNS, NTP, syslog, timezone, full L2 (VLANs,
VXLAN VNIs, MAC-VRF), L3 (L3-VRF instance-type, route-distinguisher,
RT import/export, EVPN Type-5 via routing-instance.l3_vni),
SNMPv1/v2c + v3 USM, local users with $1/$5/$6 hash families,
static routes, LAGs (`ae<N>` form), apply-groups inheritance (GAP
9b two-pass parse).  All of this lands on the canonical tree; almost
none of it survives the cisco_iosxe render.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig-yang-scope.md` | What the cisco_iosxe render actually emits | `<interfaces>` only; everything else dropped |
| `interface-fields.md` | Per-field disposition for the canonical interface core | The only fields with `good` disposition |
| `ipv6-addresses.md` | IPv6 link-local scope hard-code on render | Same hard-code on `_iface_dict_to_canonical` parse path; render respects scope |
| `vlan-render-gap.md` | VLANs and SVIs | `unsupported` (cisco_iosxe render doesn't walk intent.vlans) |
| `snmp-render-gap.md` | SNMP v1/v2c + v3 USM | `unsupported` (render-side gap; v3 doubly-blocked) |
| `vxlan-evpn-gap.md` | VXLAN, EVPN-VXLAN, MAC-VRF | `unsupported` (cisco_iosxe matrix declares unsupported explicitly) |
| `vrf-render-gap.md` | VRF / routing-instances / L3-VRF | `unsupported` (render-side gap) |
| `apply-groups-unsupported.md` | Junos-only configuration inheritance | `unsupported` (no Cisco analogue at all) |

## Re-fetch notes

Juniper TechLibrary docs live at `https://www.juniper.net/documentation/`.
OpenConfig models cited live at `https://openconfig.net/projects/models/`.
Cisco YANG vendor models live at
`https://github.com/YangModels/yang/tree/main/vendor/cisco/xe/`.

See also: `../cisco_iosxe_to_juniper_junos/_INDEX.md` (forward direction)
and `../README.md` (citation cache layout).
