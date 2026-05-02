# Cisco IOS-XE OpenConfig NETCONF to OPNsense — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__opnsense.yaml`
per-field expectations.  See `tests/fixtures/cross_vendor_expectations/
README.md` for the canonical schema definition.

This pair is the **Cisco OpenConfig NETCONF source -> OPNsense XML
target** direction.  Distinct from the sibling pair
`../cisco_iosxe_cli_to_opnsense/`: the source codec here is
`cisco_iosxe` (NETCONF YANG / OpenConfig), NOT `cisco_iosxe_cli`
(text-CLI).

The two Cisco codecs target the same device family but the parse
surface is sharply different:

| Source codec | Wire format | Parse coverage |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | Full canonical surface (certified) |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `<interfaces>` only (best_effort stub) |

## Direction-specific framing

The dominant fact for this pair is that the `cisco_iosxe` SOURCE
codec's `parse()` walks `<interfaces>` and ignores `<system>`,
`<vlans>`, `<network-instances>`, `<snmp>`, `<routing>`, `<routing-
policy>`, `<aaa>`, etc.  Even when a real device's `<get-config>`
reply carries those subtrees, the parser drops them silently.
`intent.hostname`, `intent.dns_servers`, `intent.snmp`,
`intent.vlans`, `intent.local_users`, `intent.radius_servers`,
`intent.lags`, `intent.routing_instances`, `intent.static_routes`
are all empty / None after parse, regardless of input content.

Add the OPNsense target's own modelling boundaries on top of that:
no switchport / VLAN-membership concept, no VRF, no VXLAN.  The
shared canonical surface is consequently very narrow — the
interface core (name, description, enabled, IPv4, IPv6) and not
much else.

This direction skews heavily to `not_applicable` (parser produces
nothing) with a sprinkle of `unsupported` where the OPNsense target
also lacks the model.  Almost no `lossy`, because `lossy` requires
the canonical tree to actually carry data that gets degraded — and
the canonical tree is structurally empty here for non-interface
fields.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig_yang_scope.md` | What the `cisco_iosxe` parser walks vs declares | parse() is `<interfaces>` only; matrix entries for `<system>`, `<vlans>`, `<routing>`, `<snmp>` are aspirational |
| `interface_fields.md` | Canonical interface core through to OPNsense `<wan>`/`<lan>`/`<optN>` | name / description / enabled / IPv4 round-trip; type / mtu / IPv6 link-local lossy |
| `ipv6_addresses.md` | IPv6 address rendering on both sides | scope hard-coded global by source parser; OPNsense `<ipaddrv6>`+`<subnetv6>` form |
| `vlan_render_gap.md` | VLAN handling on OPNsense target | OPNsense has no VLAN-centric port-membership; source parser doesn't read `<vlans>` either |
| `snmp_render_gap.md` | SNMP on both sides | source parser doesn't read `<snmp>`; OPNsense v3 USM lives in plugin's `snmpd.conf` |
| `vxlan_evpn_gap.md` | VXLAN / EVPN | unsupported on source codec matrix AND on OPNsense target |
| `dhcp_render_gap.md` | DHCP server pools | source parser doesn't read DHCP XML; OPNsense `<dhcpd>` is interface-keyed |

## Re-fetch notes

OpenConfig models cited live at `https://openconfig.net/projects/models/`
and `https://github.com/openconfig/public/`.  OPNsense manuals are
at `https://docs.opnsense.org/manual/` (current 25.x train).

Retrieved 2026-05-01.

## See also

- `../README.md` — citation cache layout (top-level index).
- `../opnsense_to_cisco_iosxe/_INDEX.md` — reverse direction.
- `../cisco_iosxe_cli_to_opnsense/_INDEX.md` — text-CLI Cisco source variant.
- `../../../tests/fixtures/cross_vendor_expectations/README.md` — schema spec.
