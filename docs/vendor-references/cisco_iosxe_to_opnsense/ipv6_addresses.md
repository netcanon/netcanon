# IPv6 addresses — Cisco NETCONF source to OPNsense target

Source: [openconfig-if-ip YANG schema docs (IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [OPNsense Interfaces manual (IPv6)](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-05-01

Source: `netcanon.migration.codecs.cisco_iosxe.codec._iface_dict_to_canonical`
(in-tree code with the scope hard-coding)
Retrieved: 2026-05-01

## OpenConfig source shape

Per `openconfig-if-ip`, IPv6 addresses live under
`/interfaces/interface[name]/subinterfaces/subinterface[index]/openconfig-if-ip:ipv6/addresses/address`.
Each address has an `<ip>` leaf and a `<config>` block with the
matching `<ip>` plus `<prefix-length>` (0..128).

The OpenConfig model carries optional `<config><type>` enum on the
address (`GLOBAL_UNICAST`, `LINK_LOCAL_UNICAST`, etc.) — the
cisco_iosxe parser does NOT read this enum and instead hard-codes
`scope="global"` on every parsed address (see
`_iface_dict_to_canonical`).  When the source XML carries a
`fe80::1` link-local address, the parser miscategorises it as
global.

## OPNsense target shape

OPNsense stores per-interface IPv6 addressing in two siblings of
the `<wan>`/`<lan>`/`<optN>` zone block:

```xml
<lan>
  <if>em1</if>
  <ipaddr>10.0.0.1</ipaddr>
  <subnet>24</subnet>
  <ipaddrv6>2001:db8::1</ipaddrv6>
  <subnetv6>64</subnetv6>
</lan>
```

`<ipaddrv6>` accepts the literal address OR one of these keywords
indicating non-static configuration:

- `dhcp6` — DHCPv6 client.
- `track6` — track-interface (assign from upstream PD).
- `slaac` — SLAAC autoconfig.
- `6rd`, `6to4` — tunnel-derived.

These keywords are NOT a static address record and don't fit the
`CanonicalIPv6Address` shape.  The OPNsense codec parse-and-ignores
those on the parse side.

OPNsense does not model the `scope` discriminator separately —
link-local addresses on FreeBSD interfaces are auto-derived from
the interface MAC and never written to `config.xml`.  Operators
who need an explicit link-local don't get it here.

## Cross-pair disposition

`interfaces[].ipv6_addresses`: **lossy**.

Two sources of loss:

1. The cisco_iosxe parser hard-codes `scope="global"` on every
   IPv6 address.  A genuine `fe80::1` link-local from OpenConfig
   reaches the OPNsense render as a global address.
2. OPNsense doesn't model link-local separately anyway — `<ipaddrv6>`
   takes one address, and FreeBSD auto-generates the link-local.
   Even if the canonical model carried `scope="link-local"`, the
   OPNsense render would either emit it as a regular address or
   skip it.

The composite effect: cross-pair degrades for any non-global IPv6
address.  For typical "global address only" deployments (the common
case), the round-trip is clean.
