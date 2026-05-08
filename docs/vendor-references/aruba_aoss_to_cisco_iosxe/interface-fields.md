# Interface canonical-core fields — AOS-S source to OpenConfig NETCONF target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 IPv4 / IPv6 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

## Field-by-field disposition

This is the surface where the cisco_iosxe NETCONF target codec
DOES emit XML output, so the dispositions here are the most
detailed and the highest-confidence.

| Canonical field | AOS-S parse | NETCONF render | Disposition |
|---|---|---|---|
| `interfaces[].name` | bare-numeric / letter-port / Trk* | emitted as `<name>` text verbatim | good (with rename mesh) |
| `interfaces[].description` | parsed from `name "<text>"` | emitted as `<description>` | good |
| `interfaces[].enabled` | `enable` / `disable` (default enabled) | emitted as YANG bool | good |
| `interfaces[].interface_type` | inferred from name shape on parse | emitted as `<type>` IANA ident | lossy (inference asymmetry — see below) |
| `interfaces[].mtu` | not parsed (codec gap) | not emitted (no source data) | lossy (deferred) |
| `interfaces[].ipv4_addresses` | parsed from VLAN SVI absorption | emitted as v4 augment | good |
| `interfaces[].ipv6_addresses` | parsed from VLAN SVI absorption | emitted as v6 augment, scope=global | lossy (link-local discriminator dropped) |
| `interfaces[].switchport_mode` | parsed from VLAN port-membership | not emitted (target render gap) | unsupported |
| `interfaces[].access_vlan` | parsed | not emitted | unsupported |
| `interfaces[].trunk_allowed_vlans` | parsed | not emitted | unsupported |
| `interfaces[].trunk_native_vlan` | parsed | not emitted | unsupported |
| `interfaces[].voice_vlan` | not parsed (codec gap) | not emitted | unsupported |
| `interfaces[].lag_member_of` | parsed (Trk number assignments) | not emitted | unsupported |
| `interfaces[].dhcp_client` | not parsed (codec gap) | not emitted | unsupported |
| `interfaces[].vrf` | always empty (no AOS-S VRF concept) | not emitted | not_applicable |

## Interface type inference

The aruba_aoss parser infers `interface_type` from the name shape:

* Bare numeric (`1`, `A2`) -> `ethernetCsmacd`
* `Trk<N>` -> `ieee8023adLag`
* `Vlan<N>` (synthesised SVI) -> `l2vlan`
* `Loopback<N>` (rare) -> `softwareLoopback`

This inference is also what the cisco_iosxe parser does on the
reverse direction (the IANA ident comes from the OpenConfig source,
but the render side maps name-prefix to type).  The asymmetry: when
AOS-S source emits a `Trk1` LAG, the canonical record carries
`ieee8023adLag` which the NETCONF render emits — but the OpenConfig
consumer downstream of NETCONF won't have any LAG-member binding
information, so the LAG is a stub.  The inference is preserved but
its operational meaning is hollow.

## IPv6 link-local

The cisco_iosxe codec hard-codes `scope="global"` on every
parsed IPv6 address (see
`netcanon.migration.codecs.cisco_iosxe.codec._iface_dict_to_canonical`).
The AOS-S parser does NOT yet populate link-local addresses
explicitly either (the source codec also defaults to global), so on
this direction the asymmetry is in the canonical model, not
introduced by the codec pair.  Disposition: lossy with reason citing
the canonical-model gap rather than codec-specific drift.

## MTU

Aruba AOS-S has a `mtu` directive (`interface 1 / mtu 1500`) but
the aruba_aoss parser does NOT extract it (codec gap).  The
canonical `interfaces[].mtu` field stays None, the NETCONF render
never emits the `<mtu>` leaf, and operators don't get an MTU
declaration in the rendered XML.  Disposition: lossy with reason
citing the AOS-S parse-side wire-up gap (deferred).

## Disposition summary

* good: name, description, enabled, ipv4_addresses
* lossy: interface_type (with note about inference), ipv6_addresses
  (link-local scope), mtu (deferred)
* unsupported: switchport_mode, access_vlan, trunk_allowed_vlans,
  trunk_native_vlan, voice_vlan, lag_member_of, dhcp_client
* not_applicable: vrf
