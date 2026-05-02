# Interface canonical-core fields — Cisco NETCONF source to Junos target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4/IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Junos Protocol Family and Interface Address Properties](https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html)
Retrieved: 2026-05-01

Source: `netconfig.migration.codecs.cisco_iosxe.codec._iface_dict_to_canonical`
(in-tree code documenting what the parser carries through)
Retrieved: 2026-05-01

## What the parser actually carries through

The cisco_iosxe NETCONF parser walks `<interfaces>` and produces a
`CanonicalInterface` with these fields populated:

| Canonical field | Populated? | Source XML element |
|---|---|---|
| `name` | yes | `<interface><name>` |
| `description` | yes | `<config><description>` |
| `enabled` | yes | `<config><enabled>` (strict YANG bool) |
| `interface_type` | yes | `<config><type>` (IANA ident) |
| `mtu` | NO | `<config><mtu>` (parsed but NOT carried to canonical) |
| `ipv4_addresses` | yes | `<subinterfaces><subinterface><ipv4><addresses>` |
| `ipv6_addresses` | yes | `<subinterfaces><subinterface><ipv6><addresses>` (scope hard-coded global) |
| `switchport_mode` | NO | parser doesn't walk `openconfig-vlan:switched-vlan` |
| `access_vlan` | NO | parser doesn't walk |
| `trunk_allowed_vlans` | NO | parser doesn't walk |
| `trunk_native_vlan` | NO | parser doesn't walk |
| `voice_vlan` | NO | parser doesn't walk |
| `lag_member_of` | NO | parser doesn't walk `openconfig-if-aggregate` |
| `dhcp_client` | NO | parser doesn't walk OpenConfig DHCP-client augment |
| `vrf` | NO | parser doesn't walk `openconfig-network-instance` |

## What the Junos target render emits

The juniper_junos codec is rich on the render side: it advertises
`/interfaces/interface/config/vrf` (GAP 6), `/vlans/vlan/{id,name}`,
SNMP v1/v2c/v3, full L3-VRF and MAC-VRF instance types, VXLAN VNIs,
apply-groups, local users, static routes.

When the canonical tree carries an interface with name + description +
enabled + ipv4_addresses, the Junos render emits:

```
set interfaces ge-0/0/0 description "WAN uplink"
delete interfaces ge-0/0/0 disable
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24
```

If the source's name is `GigabitEthernet0/0/0`, the port-rename mesh
translates it to Junos form (typically `ge-0/0/0` for 1G,
`xe-0/0/0` for 10G, `et-0/0/0` for 40G+).  See `interface-naming.md`.

But the cisco_iosxe parser does NOT populate `intent.vlans`,
`intent.snmp`, `intent.routing_instances`, etc., so the Junos
render's full-feature surface has only the synthesised SVI side
of the interface walk to work with.  Tagged / untagged port lists
are empty, no `set vlans` blocks emit, no `set routing-instances`,
no `set snmp`.

## Per-field disposition

| Field | Disposition | Reason |
|---|---|---|
| `interfaces[].name` | good | round-trips through rename mesh |
| `interfaces[].description` | good | free-text |
| `interfaces[].enabled` | good | YANG bool -> Junos `disable` toggle |
| `interfaces[].interface_type` | lossy | inference asymmetry — Junos infers from name shape |
| `interfaces[].mtu` | not_applicable | source parser doesn't carry through |
| `interfaces[].ipv4_addresses` | good | Junos accepts CIDR via `family inet` |
| `interfaces[].ipv6_addresses` | lossy | scope hard-coded global by source parser |
| `interfaces[].switchport_mode` | not_applicable | source parser doesn't walk |
| `interfaces[].access_vlan` | not_applicable | source parser doesn't walk |
| `interfaces[].trunk_allowed_vlans` | not_applicable | source parser doesn't walk |
| `interfaces[].trunk_native_vlan` | not_applicable | source parser doesn't walk |
| `interfaces[].voice_vlan` | not_applicable | source parser doesn't walk |
| `interfaces[].lag_member_of` | not_applicable | source parser doesn't walk LAG augment |
| `interfaces[].dhcp_client` | not_applicable | source parser doesn't walk |
| `interfaces[].vrf` | not_applicable | source parser doesn't walk `<network-instances>` |

## Interface-type inference

OpenConfig source carries IANA ident strings like
`iana-if-type:ethernetCsmacd`.  Junos has no ifType concept on the
wire — its codec infers type from the name prefix (`ge-` / `xe-` /
`et-` / `lo` -> ethernetCsmacd / softwareLoopback / etc.).  When the
cisco source's IANA ident says `ethernetCsmacd` and the name
translates to `ge-0/0/0`, both sides agree.  But if the IANA ident is
`ieee8023adLag` (for a Cisco Port-channel sub-interface) and the name
is a literal `Port-channel1`, the Junos rename target (`ae1`) is
inferred from the name shape rather than from the explicit type.
Disposition: lossy with reason "inference asymmetry"; this is a
long-standing canonical-model gap, not introduced by this pair
specifically.

## MTU collapse

OpenConfig's single `mtu` leaf doesn't distinguish link-MTU from
`ip mtu` / `ipv6 mtu` / `mpls mtu` (which are separate CLI
directives on Cisco).  Even if the parser were extended to carry
`<config><mtu>` through to `CanonicalInterface.mtu`, the Junos
render's `set interfaces X mtu N` is a parent-interface link-MTU,
matching the OpenConfig single-leaf semantic — so the render side is
fine; the loss is upstream of this codec pair (in the device
OpenConfig translation layer).
