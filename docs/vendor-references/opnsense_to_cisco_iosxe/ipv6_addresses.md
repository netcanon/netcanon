# IPv6 addresses — OPNsense source to Cisco NETCONF target

Source: [OPNsense Interfaces manual (IPv6)](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

## OPNsense source shape

OPNsense stores per-interface IPv6 addressing in two siblings of
the `<wan>`/`<lan>`/`<optN>` zone block:

```xml
<lan>
  <if>em1</if>
  <ipaddrv6>2001:db8::1</ipaddrv6>
  <subnetv6>64</subnetv6>
</lan>
```

`<ipaddrv6>` accepts the literal address OR one of these keywords
indicating non-static configuration: `dhcp6`, `track6`, `slaac`,
`6rd`, `6to4`.  These are NOT static address records and the
OPNsense codec parse-and-ignores them.

OPNsense does not model the `scope` discriminator — link-local
addresses on FreeBSD are auto-derived from the interface MAC and
not written to `config.xml`.

## OpenConfig target shape

Per `openconfig-if-ip`, IPv6 addresses live under
`/interfaces/interface[name]/subinterfaces/subinterface[index]/openconfig-if-ip:ipv6/addresses/address`.
Each address has an `<ip>` leaf and a `<config>` block with the
matching `<ip>` plus `<prefix-length>` (0..128).

The OpenConfig model carries an optional `<config><type>` enum
with values like `GLOBAL_UNICAST`, `LINK_LOCAL_UNICAST`,
`UNIQUE_LOCAL_UNICAST`.  The cisco_iosxe codec's
`_render_canonical()` does NOT emit this enum — every IPv6 address
is rendered with bare `<ip>` + `<prefix-length>`, with the address
type inferred (or not) downstream.

## Cross-pair disposition

`interfaces[].ipv6_addresses`: **lossy**.

Source carries `scope="global"` / `scope="link-local"` (the OPNsense
codec parses any literal address as global; FreeBSD-derived link-
locals don't appear in `config.xml` so the OPNsense canonical
record is always global).  Target renderer emits no scope/type
enum.  For typical "global address only" deployments (the common
case), the round-trip is clean.  For specialised cases the loss is
the canonical schema's own model gap (no scope discriminator on
the OpenConfig render side) rather than vendor-specific.

OPNsense's non-static IPv6 keywords (`dhcp6`, `track6`, `slaac`,
`6rd`, `6to4`) parse-and-ignore on the OPNsense side, so they
never reach this cross-pair.  Cisco IOS-XE has separate stanzas
for `ipv6 address dhcp` / `ipv6 address autoconfig` but these
aren't a CanonicalIPv6Address shape and the cross-pair drops them
silently regardless.
