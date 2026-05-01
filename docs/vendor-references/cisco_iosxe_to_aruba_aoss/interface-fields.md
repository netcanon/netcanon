# Interface canonical-core fields — Cisco NETCONF source to AOS-S CLI target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
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

## What the AOS-S target render emits

The aruba_aoss codec is `certified` and renders the full canonical
surface.  When the canonical tree carries an interface with name +
description + enabled + ipv4_addresses, the AOS-S render emits:

```
interface 1
   name "WAN uplink to upstream carrier"
   enable
   exit
```

If the source's name is `GigabitEthernet0/0/0`, the port-rename
mesh translates it to AOS-S form (typically a bare-numeric `1` or
letter-port `A1`).

For a synthesised SVI (e.g. `Vlan10` from cisco source), the AOS-S
render emits a VLAN stanza with absorbed L3:

```
vlan 10
   ip address 10.10.10.1/24
   exit
```

But — and this is the critical asymmetry — the cisco_iosxe parser
does NOT populate `intent.vlans`, so the AOS-S render's
`vlan-vs-interface` correlation has only the synthesised SVI side
to work with.  Tagged / untagged port lists are empty.

## Per-field disposition

| Field | Disposition | Reason |
|---|---|---|
| `interfaces[].name` | good | round-trips through rename mesh |
| `interfaces[].description` | good | free-text |
| `interfaces[].enabled` | good | YANG bool -> AOS-S `enable`/`disable` |
| `interfaces[].interface_type` | lossy | inference asymmetry — AOS-S doesn't model IANA ifType |
| `interfaces[].mtu` | not_applicable | source parser doesn't carry through |
| `interfaces[].ipv4_addresses` | good | AOS-S accepts dotted-mask or CIDR |
| `interfaces[].ipv6_addresses` | lossy | scope hard-coded global by source parser |
| `interfaces[].switchport_mode` | not_applicable | source parser doesn't walk |
| `interfaces[].access_vlan` | not_applicable | source parser doesn't walk |
| `interfaces[].trunk_allowed_vlans` | not_applicable | source parser doesn't walk |
| `interfaces[].trunk_native_vlan` | not_applicable | source parser doesn't walk |
| `interfaces[].voice_vlan` | not_applicable | source parser doesn't walk |
| `interfaces[].lag_member_of` | not_applicable | source parser doesn't walk LAG augment |
| `interfaces[].dhcp_client` | not_applicable | source parser doesn't walk |
| `interfaces[].vrf` | not_applicable | AOS-S has no VRF concept regardless |

## IPv6 link-local

The `cisco_iosxe._iface_dict_to_canonical()` helper hard-codes
`scope="global"` on every IPv6 address.  When the source XML carries
a `fe80::1` link-local address (legitimate per OpenConfig and per
RFC 4291), the parser miscategorises it as global.  AOS-S would
then emit a global IPv6 address declaration for what should be
link-local.  Disposition: lossy with reason citing the parser
hard-code.

## Interface-type inference

OpenConfig source carries IANA ident strings like
`iana-if-type:ethernetCsmacd`.  AOS-S has no ifType concept — the
codec infers type from name shape (bare numeric -> ethernet,
`Trk<N>` -> LAG, `Vlan<N>` -> SVI).  When the cisco source's IANA
ident says `ethernetCsmacd` but the name is `Trk1` (which on AOS-S
should infer LAG), the round-trip is consistent because both sides
agree on ethernet.  But if the IANA ident is `ieee8023adLag` while
the name is a bare numeric (legitimate on Cisco for Port-channel
sub-interfaces), the AOS-S inference would produce `ethernet` from
the name shape.  Disposition: lossy with reason "inference
asymmetry"; this is a long-standing canonical-model gap, not
introduced by this pair specifically.
