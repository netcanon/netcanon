# OPNsense to Cisco IOS-XE OpenConfig NETCONF — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/opnsense__cisco_iosxe.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is the **OPNsense XML source -> Cisco OpenConfig NETCONF
target** direction.  Distinct from the sibling pair
`../opnsense_to_cisco_iosxe_cli/`: the target codec here is
`cisco_iosxe` (NETCONF YANG / OpenConfig), NOT `cisco_iosxe_cli`
(text-CLI).

The two Cisco codecs target the same device family but the render
surface is sharply different:

| Target codec | Wire format | Render coverage |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | Full canonical surface (certified) |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `<interfaces>` only (best_effort stub) |

## Direction-specific framing

The dominant fact for this pair is that the `cisco_iosxe` TARGET
codec's `_render_canonical()` only emits `<interfaces>` shapes —
no `<system>`, `<vlans>`, `<network-instances>`, `<snmp>`,
`<routing>`.  Even when the canonical tree carries hostname /
domain / DNS / NTP / VLANs / static-routes / SNMP / local-users /
RADIUS (which OPNsense parse genuinely populates for several of
these), the render emits a bare `<interfaces>` document.

Add OPNsense's own modelling boundaries on the SOURCE side:
OPNsense parser doesn't surface DNS / NTP / syslog / timezone /
static-routes into the canonical tree (codec-implementation gaps,
not vendor gaps — the data IS in `config.xml`); OPNsense has no
switchport, no VRF, no VXLAN.

The composite effect: every Tier-1 / Tier-2 field beyond per-
interface name/description/enabled/IPv4/IPv6 is `unsupported` on
this pair (target render side).  The forward direction
(`cisco_iosxe__opnsense.yaml`) skews `not_applicable` (parser
gap); this reverse direction skews `unsupported` (render gap).
Schematically different, operationally identical.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig_yang_scope.md` | What the `cisco_iosxe` target render emits vs declares | render emits `<interfaces>` only; matrix entries for hostname/dns/snmp/vlan are aspirational |
| `interface_fields.md` | OPNsense `<wan>`/`<lan>`/`<optN>` source through to OpenConfig YANG NETCONF | name / description / enabled / IPv4 round-trip |
| `ipv6_addresses.md` | IPv6 address rendering on both sides | OPNsense `<ipaddrv6>`+`<subnetv6>` -> OpenConfig `openconfig-if-ip:ipv6` |
| `vlan_render_gap.md` | VLAN handling on Cisco target | target render emits no `<vlans>` element; OPNsense source already lossy |
| `snmp_render_gap.md` | SNMP on both sides | target render emits no `<snmp>` element; OPNsense source v3 lives in plugin's `snmpd.conf` |
| `vxlan_evpn_gap.md` | VXLAN / EVPN | unsupported on target codec matrix AND on OPNsense source |
| `firewall_unsupported.md` | OPNsense firewall / NAT / VPN | not in canonical scope; parse-and-ignored on OPNsense side |
| `dhcp_render_gap.md` | DHCP server pools | OPNsense parses `<dhcpd>` into canonical; target render emits nothing |

## Re-fetch notes

OpenConfig models cited live at `https://openconfig.net/projects/models/`
and `https://github.com/openconfig/public/`.  OPNsense manuals are
at `https://docs.opnsense.org/manual/` (current 25.x train).

Retrieved 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../cisco_iosxe_to_opnsense/_INDEX.md` — reverse direction.
- `../opnsense_to_cisco_iosxe_cli/_INDEX.md` — text-CLI Cisco target variant.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
