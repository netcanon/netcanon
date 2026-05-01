# AOS-S source content NOT carried through the OpenConfig render

Source: [Aruba ArubaOS-Switch 16.11 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: `netconfig.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec._render_canonical`
(in-tree code; the authoritative source of "what the render emits")
Retrieved: 2026-05-01

## Summary

The AOS-S source codec is a `certified`-grade parser that populates
substantially the full `CanonicalIntent` surface.  The cisco_iosxe
target codec is a `best_effort` Phase-0.5 stub whose render emits
ONLY `openconfig-interfaces` XML.  Every category below is populated
by the AOS-S parser and dropped silently by the cisco_iosxe render.

| Canonical category | AOS-S source coverage | OpenConfig target render |
|---|---|---|
| `hostname` | parsed (quoted -> bare) | dropped (not in render) |
| `domain` | not parsed (no AOS-S directive) | n/a |
| `dns_servers` | parsed from `ip dns server-address priority N` | dropped |
| `ntp_servers` | parsed from `sntp server priority N` | dropped |
| `timezone` | not parsed (codec gap) | n/a |
| `syslog_servers` | parsed from `logging <addr>` | dropped |
| `vlans` | parsed (VLAN-centric incl. SVI absorption) | dropped |
| `static_routes` | parsed (CIDR + dotted-mask forms, plus `ip default-gateway`) | dropped |
| `dhcp_servers` | not parsed (AOS-S is relay-only) | n/a |
| `snmp` (v1/v2c) | parsed (community / location / contact / trap-host) | dropped |
| `snmp.v3_users` | parsed (USM + group bindings) | dropped (target also lists `/snmp/v3-user` `unsupported`) |
| `lags` | parsed (`trunk N-M trkX <mode>`) | dropped |
| `local_users` | parsed (manager / operator + sha1 / bcrypt / plaintext) | dropped |
| `radius_servers` | parsed (`radius-server host` + global key) | dropped |
| `vxlan_vnis` | not parsed (target also `unsupported`) | n/a |
| `evpn_type5_routes` | not parsed (target also `unsupported`) | n/a |
| `routing_instances` | not parsed (no AOS-S VRF concept) | n/a |

## Why the gap is render-side, not model-side

The target `cisco_iosxe` codec's CapabilityMatrix declares a much
larger `supported` list than the render actually walks.  The
declarations are aspirational: they exist so that cross-codec mesh
translations don't classify the paths as `unsupported` on the target
side.  But `_render_canonical()` only reads `intent.interfaces` —
nothing else.

Concretely, the matrix declares these `supported` while render
ignores them:

* `/system/hostname`, `/system/dns-server`, `/system/ntp-server`
* `/vlans/vlan/id`, `/vlans/vlan/name`
* `/routing/static-route`
* `/snmp/community`, `/snmp/location`, `/snmp/contact`, `/snmp/trap-host`

The disposition for these fields on this cross-pair is `unsupported`
with reason citing the render-side wire-up gap (NOT `lossy`, because
the target render doesn't even attempt — there's no partial emission).

## Operator implication

For a real campus refresh from an Aruba 2930M to a Catalyst 9300, the
recommended path is **NOT** AOS-S -> cisco_iosxe NETCONF.  Use AOS-S
-> cisco_iosxe_cli (the certified CLI codec) instead and let the
operator paste the rendered CLI into the device.  The NETCONF target
is appropriate ONLY for the narrow case where a downstream
orchestrator consumes only `openconfig-interfaces` data and the
operator accepts that everything else needs to be applied separately.

## Disposition

All categories above: **unsupported** on this cross-pair, with the
reason citing the render-side wire-up gap in the cisco_iosxe codec
combined with the matrix-declared `unsupported` for VXLAN / EVPN /
SNMPv3.
