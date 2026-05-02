# VLANs and switchport membership: OPNsense versus Junos

How VLAN definitions, port membership, and SVI L3 are declared on
each platform.

Sources:
- OPNsense: https://docs.opnsense.org/manual/other-interfaces.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-05-01)

## OPNsense form

OPNsense models VLANs as per-tag sub-interfaces on a parent NIC.
A VLAN exists only AS a tagged sub-interface — there is NO
VLAN-centric port-membership model:

```xml
<vlans>
  <vlan uuid="...">
    <if>em1</if>
    <tag>100</tag>
    <pcp>0</pcp>
    <descr>USERS VLAN</descr>
    <vlanif>vlan0.100</vlanif>
  </vlan>
</vlans>
```

To consume the VLAN's traffic, the operator assigns the synthesised
`vlan0.100` interface to a zone in `<interfaces>`:

```xml
<interfaces>
  <opt2>
    <if>vlan0.100</if>
    <descr>USERS gateway</descr>
    <enable>1</enable>
    <ipaddr>192.168.10.1</ipaddr>
    <subnet>24</subnet>
  </opt2>
</interfaces>
```

OPNsense VLAN notes:

- A VLAN belongs to ONE parent NIC (`<if>em1</if>`) — no trunking
  concept where a VLAN appears on multiple ports.
- Untagged traffic is the parent NIC's native frames; not a per-port
  toggle.
- The L3 SVI lives on the zone (`<opt2>`) that consumes the
  `vlan0.100` interface, not on the VLAN itself.
- VLAN names are free-form text in `<descr>`; no character-set
  restrictions.

## Junos form

Name-keyed VLAN definitions; per-interface membership lives on the
`family ethernet-switching` surface:

```
set vlans USERS vlan-id 100
set vlans USERS description "User VLAN"
set vlans USERS l3-interface irb.100

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS

set interfaces ge-0/0/24 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/24 unit 0 family ethernet-switching vlan members [ USERS VOICE ]
set interfaces ge-0/0/24 native-vlan-id 1

set interfaces irb unit 100 family inet address 192.168.10.1/24
```

VLAN names allow letters, digits, hyphens, periods only (no
underscores, up to 255 chars).

## Cross-vendor mapping

OPNsense -> Junos:

* `vlans[].id`: **good** — OPNsense `<tag>` ↔ Junos `vlan-id`.  Both
  share the 1-4094 range.
* `vlans[].name`: **lossy** — OPNsense `<descr>` (free-form) maps
  to Junos `set vlans NAME` where NAME is restricted to letters,
  digits, hyphens, periods.  Codec sanitises (`underscore` →
  `hyphen`, spaces stripped).  Two canonical fields (`name` and
  `description`) share OPNsense's single `<descr>` slot, so the
  source-side collapse predates the cross-vendor render.
* `vlans[].description`: **lossy** — same source-side collapse.
* `vlans[].tagged_ports` / `untagged_ports`: **not_applicable** —
  OPNsense never populates these (no port-membership model on
  parse).  Junos target accepts per-interface `vlan members`
  declarations but receives nothing to render.
* `vlans[].ipv4_addresses` (SVI absorption): **lossy** — OPNsense's
  pattern (zone with VLAN sub-interface) doesn't populate
  `CanonicalVlan.ipv4_addresses`; the L3 address lives on the
  zone's CanonicalInterface entry.  Junos target's `irb.<N>`
  synthesis from `CanonicalVlan.ipv4_addresses` therefore receives
  nothing — operators rebuild the SVI mapping manually.

Disposition: tag round-trips cleanly; everything else degrades
because OPNsense's parse path doesn't populate the VLAN-centric
canonical fields.
