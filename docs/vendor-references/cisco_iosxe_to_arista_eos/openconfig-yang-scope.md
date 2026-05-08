# OpenConfig YANG scope — what the cisco_iosxe source codec actually parses

Source: [Native, IETF, OpenConfig... Why so many YANG models? (Cisco Blogs)](https://blogs.cisco.com/developer/which-yang-model-to-use)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: `netcanon.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec.parse`
(in-tree code; the authoritative source of "what the parser populates")
Retrieved: 2026-05-01

## What the cisco_iosxe codec's parse extracts

The codec's `parse()` method finds the `<interfaces>` element under
either a NETCONF `<rpc-reply><data>` envelope or a bare OpenConfig
fragment.  For each `<interface>` child it builds a
`CanonicalInterface` record from:

* `<name>` — the list key.
* `<config><description>` — operator free text.
* `<config><enabled>` — strict YANG boolean parsing (`true` / `false`
  case-insensitive; anything else raises ParseError).
* `<config><type>` — IANA interface-type ident (verbatim).
* `<subinterfaces><subinterface>` walk:
  * `<ipv4><addresses><address>` — populates
    `CanonicalInterface.ipv4_addresses`.
  * `<ipv6><addresses><address>` — populates
    `CanonicalInterface.ipv6_addresses` with `scope="global"`
    hard-coded.

The `<config><mtu>` leaf is parsed into the intermediate dict but
NOT carried through to `CanonicalInterface.mtu` in the canonical
bridge — the parser's intermediate dict has `mtu` but
`_iface_dict_to_canonical()` drops it.

## What the cisco_iosxe codec's parse does NOT extract

The parser does NOT walk:

* `<system>` — hostname / domain / DNS / NTP / syslog / clock / AAA
  users.  None of these populate the canonical tree.
* `<vlans>` — the top-level OpenConfig VLAN list.
  `intent.vlans` is empty regardless of source content.
* `<network-instances>` — VRFs / routing-instances, static routes
  (modelled as a per-instance protocol), BGP, OSPF.
  `intent.routing_instances`, `intent.static_routes` are empty.
* `<snmp>` — community / location / contact / trap-host / v3 users.
  `intent.snmp` is None.
* `openconfig-vlan:switched-vlan` augment under `<ethernet>` —
  per-interface switchport mode / access-vlan / trunk-vlans /
  native-vlan.  `intent.interfaces[].switchport_*` fields stay
  None / empty.
* `openconfig-if-aggregate:aggregate-id` augment — LAG membership.
  `intent.interfaces[].lag_member_of` stays empty;
  `intent.lags` stays empty.
* OpenConfig DHCP-client augment — `intent.interfaces[].dhcp_client`
  stays False.
* `openconfig-evpn` — `intent.vxlan_vnis`, `intent.evpn_type5_routes`
  stay empty.

## Why the matrix declares more than the parser extracts

The codec's CapabilityMatrix lists a much larger `supported` set:
`/system/hostname`, `/system/dns-server`, `/system/ntp-server`,
`/vlans/vlan/id`, `/vlans/vlan/name`, `/routing/static-route`,
`/snmp/community`, `/snmp/location`, `/snmp/contact`,
`/snmp/trap-host`.  These declarations are aspirational — they
exist for cross-codec mesh friendliness so that orchestration-layer
drift matrices don't classify these paths as `unsupported` on the
target side.

For per-pair fidelity expectations (this YAML), honesty beats
matrix-deference: when the parser doesn't populate the canonical
field, the disposition here is `not_applicable` because the source
wire format already lost the information before the codec saw it.

## Why `not_applicable` rather than `unsupported`

There's a meaningful schema distinction between:

* `not_applicable`: the field is structurally absent on the source
  vendor's wire format (or the parser doesn't extract it).  No data
  reaches the canonical tree; nothing reaches the target render to
  lose.
* `unsupported`: the source has data; the canonical tree carries it;
  the target codec semantically declines to emit it.

For the cisco_iosxe (NETCONF) source on this direction, every
non-interface field falls into the first bucket: the parser never
populates them, so they're structurally absent before they reach
the Arista target codec's render.  The Arista target codec is
fully capable of rendering hostname / VLANs / SNMP / VRF / VXLAN
/ etc — it just receives an empty canonical tree for those fields.

## When this YAML's classifications flip

Once the cisco_iosxe parser is wired to walk `<system>`, `<vlans>`,
`<network-instances>`, `<snmp>`, etc., the `not_applicable` rows in
the YAML flip to `good` or `lossy` per the underlying canonical-model
fidelity (which the Arista target supports for most surfaces).
This wire-up is the highest-value next step for the cisco_iosxe
NETCONF codec — it would convert this entire pair from a narrow
interface-only translation to a full-fidelity migration path.

## Disposition

For the interfaces subtree fields that DO populate: see
`interface-fields.md`.  For everything else: `not_applicable` with
the source-side parse gap reason.
