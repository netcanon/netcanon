# OpenConfig YANG scope — what the cisco_iosxe NETCONF source actually carries

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [OpenConfig project model index](https://openconfig.net/projects/models/)
Retrieved: 2026-05-01

## Why this section exists

The dominant fact for the `cisco_iosxe -> mikrotik_routeros` cross-pair
is that the source codec is a Phase-0.5 NETCONF/OpenConfig stub.  Its
`parse()` method only walks the `<interfaces>` subtree of the input
XML; every other OpenConfig namespace (system, vlan, network-instance,
lacp, snmp, ...) is silently ignored on parse.  The
`CapabilityMatrix.supported` list declares paths like `/system/hostname`,
`/snmp/community`, `/vlans/vlan/id`, and `/routing/static-route` for
cross-codec orchestration friendliness, but those declarations are
aspirational — the parser does not yet wire them through.

For this cross-pair this means: even when an OpenConfig device on the
wire carries hostname / DNS / NTP / VLAN / SNMP / static-route data,
the resulting `CanonicalIntent` produced by the cisco_iosxe codec
will have empty values for every non-interface field.  The MikroTik
RouterOS render then has nothing to emit on those surfaces regardless
of how feature-complete its render path is.

## The narrow OpenConfig subset that is actually parsed

The cisco_iosxe codec's `parse()` walks `<interfaces>/<interface>`
children and extracts:

* `<name>` (key) — opaque vendor-native identifier
* `<config><description>` — operator free text
* `<config><enabled>` — strict YANG boolean (`"true"` / `"false"`,
  case-insensitive; anything else raises `ParseError`)
* `<config><type>` — IANA interface-type ident
  (`iana-if-type:ethernetCsmacd`, `iana-if-type:softwareLoopback`,
  `iana-if-type:l2vlan`, `iana-if-type:ieee8023adLag`, `iana-if-type:tunnel`)
* `<subinterfaces>/<subinterface>/<index>`
* `<subinterfaces>/<subinterface>/<ipv4>/<addresses>/<address>` —
  `ip` + `<config><prefix-length>` (range-checked 0..32)
* `<subinterfaces>/<subinterface>/<ipv6>/<addresses>/<address>` —
  `ip` + `<config><prefix-length>` (range-checked 0..128, scope hard-
  coded `"global"`)

`<config><mtu>` is parsed into the intermediate dict but is NOT
carried into the canonical `CanonicalInterface.mtu` field — the
canonical-bridge helper drops it on the way through.  This is documented
as `LossyPath("/interfaces/interface/config/mtu")` on the codec's
capability matrix.

## What this means for the cross-pair

Mapping the parsed cisco_iosxe surface onto MikroTik RouterOS:

| Canonical field carried | MikroTik render disposition |
|---|---|
| `interfaces[].name` | good — RouterOS `/interface ethernet set [find default-name=...]` (with rename mesh translating Cisco names to RouterOS form) |
| `interfaces[].description` | good — RouterOS `comment="<text>"` |
| `interfaces[].enabled` | good — RouterOS `disabled=no` / `disabled=yes` (inverted) |
| `interfaces[].interface_type` | lossy — RouterOS doesn't expose IANA ifType natively; both codecs infer from name shape |
| `interfaces[].ipv4_addresses` | good — RouterOS `/ip address add address=A.B.C.D/N interface=...` |
| `interfaces[].ipv6_addresses` | lossy — scope discriminator hard-coded `"global"` on parse, link-local addresses mis-classified |

Everything else — hostname, DNS, NTP, syslog, timezone, vlans (top-
level definitions), static_routes, snmp, lags, local_users,
radius_servers, dhcp_servers, vxlan_vnis, evpn_type5_routes,
routing_instances — is structurally absent from the canonical tree
the source produces.  RouterOS render emits nothing for those
sections, regardless of `CapabilityMatrix` declarations.

## Disposition framing — `not_applicable` vs `unsupported`

For fields where the SOURCE has no parse-side data (every non-
interface field on the cisco_iosxe NETCONF stub), the disposition is
`not_applicable`: there is nothing to translate, and any "loss" is
upstream of the cross-pair render boundary.  This is structurally
different from a render-side wire-up gap — the codec INTENDS to
carry these surfaces eventually, but `not_applicable` correctly
captures the today-state where the source intent is empty.

For the IANA ifType inference asymmetry, the disposition is `lossy`
because both codecs do something approximate: the cisco_iosxe parser
faithfully passes through the source IANA ident; the MikroTik render
discards it (RouterOS has no native IANA-ident representation),
re-deriving from name shape on the next round-trip.
