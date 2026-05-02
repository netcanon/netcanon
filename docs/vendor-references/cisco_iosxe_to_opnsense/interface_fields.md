# Interface canonical-core fields — Cisco NETCONF source to OPNsense target

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
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
| `switchport_mode` | NO | parser doesn't walk `openconfig-vlan:switched-vlan` augment |
| `access_vlan` | NO | parser doesn't walk |
| `trunk_allowed_vlans` | NO | parser doesn't walk |
| `trunk_native_vlan` | NO | parser doesn't walk |
| `voice_vlan` | NO | parser doesn't walk |
| `lag_member_of` | NO | parser doesn't walk `openconfig-if-aggregate` |
| `dhcp_client` | NO | parser doesn't walk OpenConfig DHCP-client augment |
| `vrf` | NO | parser doesn't walk `openconfig-network-instance` |

## What the OPNsense target render emits

OPNsense models interfaces as zone-keyed elements inside
`<interfaces>`.  When the canonical tree carries an interface with
a name + description + enabled + ipv4_addresses, the OPNsense render
emits a `<wan>` / `<lan>` / `<optN>` block:

```xml
<opnsense>
  <interfaces>
    <wan>
      <if>em0</if>
      <descr>WAN uplink</descr>
      <enable/>
      <ipaddr>198.51.100.2</ipaddr>
      <subnet>30</subnet>
    </wan>
  </interfaces>
</opnsense>
```

Key shape facts:

- The CHILD TAG (`<wan>`, `<lan>`, `<optN>`) is the operator-facing
  zone label.  The `<if>` element carries the BSD device name
  (`em0`, `igb0`, `ix0`, `vlan0.10`).  Cisco's `GigabitEthernet0/0/0`
  doesn't survive — the port-rename mesh translates via the codec's
  `classify_port_name` / `format_port_identity` delegates.
- `<descr>` is free-form, no length constraint.
- `<enable/>` is an empty boolean tag; absent means disabled.
- IPv4 lives in `<ipaddr>` plus `<subnet>` (CIDR prefix length).
- IPv6 lives in `<ipaddrv6>` plus `<subnetv6>`.  The OPNsense render
  emits both when the canonical IPv6 list is populated.
- MTU is a simple `<mtu>` integer (when set).

OPNsense does NOT model:

- Switching constructs (no `switchport` concept; physical NICs are
  L3 zones or VLAN-trunk parents).
- VRFs (no `vrf` element in `config.xml`).
- Loopbacks beyond `lo0` (secondary loopbacks live in `<virtualip>`).
- Voice-VLAN / LLDP-MED.
- Per-port LAG declarations (LAGs live in their own `<laggs>`
  block; member-side has nothing on the interface).

## Per-field disposition (cisco_iosxe NETCONF -> opnsense)

| Field | Disposition | Reason |
|---|---|---|
| `interfaces[].name` | lossy | round-trips through rename mesh; Cisco speed-encoded shape doesn't match OPNsense zone label or BSD device name |
| `interfaces[].description` | good | free-text |
| `interfaces[].enabled` | good | YANG bool -> OPNsense `<enable/>` |
| `interfaces[].interface_type` | lossy | OPNsense doesn't surface a type field; canonical hint dropped on render |
| `interfaces[].mtu` | not_applicable | source parser doesn't carry through to canonical |
| `interfaces[].ipv4_addresses` | good | mechanical conversion via OPNsense `<ipaddr>`+`<subnet>` |
| `interfaces[].ipv6_addresses` | lossy | scope hard-coded global by source parser; see `ipv6_addresses.md` |
| `interfaces[].switchport_mode` | not_applicable | source parser doesn't walk; OPNsense target unsupported regardless |
| `interfaces[].access_vlan` | not_applicable | same as switchport_mode |
| `interfaces[].trunk_allowed_vlans` | not_applicable | same as switchport_mode |
| `interfaces[].trunk_native_vlan` | not_applicable | same as switchport_mode |
| `interfaces[].voice_vlan` | not_applicable | same as switchport_mode |
| `interfaces[].lag_member_of` | not_applicable | source parser doesn't walk LAG augment |
| `interfaces[].dhcp_client` | not_applicable | source parser doesn't walk |
| `interfaces[].vrf` | not_applicable | OPNsense has no VRF model regardless |

The fundamental router/firewall versus router/switch mismatch
combined with the cisco_iosxe parser's narrow scope means almost
every per-interface sub-field beyond name/description/enabled/IPv4
is structurally empty on this cross-pair.
