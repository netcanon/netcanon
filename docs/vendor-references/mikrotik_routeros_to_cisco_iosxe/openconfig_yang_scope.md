# OpenConfig YANG render scope — cisco_iosxe target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [OpenConfig project model index](https://openconfig.net/projects/models/)
Retrieved: 2026-05-01

## Why this section exists

The dominant fact for the `mikrotik_routeros -> cisco_iosxe` cross-
pair is that the target codec is a Phase-0.5 NETCONF/OpenConfig stub.
Its `_render_canonical()` method emits ONLY the `<interfaces>` subtree
of OpenConfig YANG; every other namespace (`<system>`, `<vlans>`,
`<network-instances>`, `<lacp>`, `<snmp>`, `<routing>`, ...) is left
out of the output XML regardless of canonical content.

The `CapabilityMatrix.supported` list declares paths like
`/system/hostname`, `/system/dns-server`, `/snmp/community`,
`/vlans/vlan/id`, and `/routing/static-route` for cross-codec
orchestration friendliness, but those declarations are aspirational —
the renderer does not yet wire them through.

For this cross-pair this means: even though the MikroTik RouterOS
source codec parses hostname / DNS / NTP / syslog / VLANs / SNMP
v1/v2c+v3 / static routes / DHCP / LAGs / local users / RADIUS into
a fully-populated `CanonicalIntent`, the cisco_iosxe NETCONF render
will silently drop everything except the interface list.  The
target-side gap dominates the disposition — this is "heavy
`unsupported`" with reasons citing render-side wire-up gaps.

## What the target render actually emits

The cisco_iosxe codec's `_render_canonical()` walks
`intent.interfaces` and emits exactly:

* `<interface>/<name>` (key) — opaque vendor-native identifier
* `<interface>/<config>/<name>` (mirror)
* `<interface>/<config>/<description>` — when non-empty
* `<interface>/<config>/<enabled>` — YANG boolean
* `<interface>/<config>/<type>` — IANA ident, when non-empty
* `<interface>/<subinterfaces>/<subinterface>/<index>` — fixed `0`
* `<interface>/<subinterfaces>/<subinterface>/<ipv4>/<addresses>/<address>` —
  per IPv4 address
* `<interface>/<subinterfaces>/<subinterface>/<ipv6>/<addresses>/<address>` —
  per IPv6 address

This is the entire surface area written to the output XML.  No
other intent fields drive XML emission on the render path.

## What gets dropped on render

The MikroTik source codec produces a fully-populated
`CanonicalIntent` for typical RouterOS `/export verbose` input:

* `intent.hostname` — from `/system identity / set name=...`
* `intent.dns_servers` — from `/ip dns / set servers=...`
* `intent.ntp_servers` — from `/system ntp client / set servers=...`
* `intent.timezone` — from `/system clock / set time-zone-name=...`
* `intent.syslog_servers` — from `/system logging`
* `intent.vlans[]` — from `/interface vlan` plus bridge VLAN
  filtering rows where Plane-2 parsing applies
* `intent.static_routes[]` — from `/ip route`
* `intent.dhcp_servers[]` — from the three-section
  `/ip pool` + `/ip dhcp-server network` + `/ip dhcp-server`
* `intent.snmp` — from `/snmp` and `/snmp community` (RouterOS
  overloads `/snmp community` for both v1/v2c and v3 USM users)
* `intent.lags[]` — from `/interface bonding`
* `intent.local_users[]` — from `/user` (without password material;
  RouterOS does not surface password hashes in /export)
* `intent.radius_servers[]` — from `/radius`

EVERY ONE of these is dropped on the cisco_iosxe NETCONF render.
The output XML carries no `<system>`, no `<snmp>`, no `<vlans>`, no
`<network-instances>`, no `<routing>`.

## Disposition framing — `unsupported` vs `not_applicable`

For fields where the SOURCE has data but the TARGET render silently
drops it: `unsupported` with reason citing the render-side wire-up
gap.  This is the dominant disposition on this cross-pair —
hostname, dns_servers, ntp_servers, syslog_servers, vlans,
static_routes, dhcp_servers, snmp, lags, local_users,
radius_servers all fall here.

For fields where neither side carries data (apply_groups,
group_content — Junos-only): `not_applicable`.

For fields where both codecs declare the path unsupported in their
matrices (vxlan_vnis, evpn_type5_routes, routing_instances):
`unsupported` with the matrix declarations as the cited reason.

The contrast with the sibling `mikrotik_routeros__cisco_iosxe_cli`
pair is sharp: that pair classifies most of these surfaces as
`lossy` because the cisco_iosxe_cli render DOES walk the full
canonical tree.  The NETCONF stub's narrow render scope is the
single biggest factor making this pair lossier than its CLI sibling.
