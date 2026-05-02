# Interfaces: Junos versus OPNsense

## Junos

Source: [Junos Understanding Interface Naming Conventions (QFX)](https://www.juniper.net/documentation/en_US/junos12.3/topics/concept/interfaces-naming-conventions-qfx-series.html)
Source: [Junos Protocol Family and Interface Address Properties](https://www.juniper.net/documentation//us/en/software/junos/interfaces-fundamentals/topics/topic-map/protocol-family-interface-address-properties.html)
Retrieved: 2026-05-01

```
set interfaces ge-0/0/0 description "Uplink to spine"
set interfaces ge-0/0/0 mtu 9000
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64
set interfaces lo0 unit 0 family inet address 172.16.0.1/32
set interfaces lo0 unit 0 family inet6 address fe80::1/64
set interfaces ge-0/0/9 disable
```

Junos interface naming notes:

- Physical port names embed media + slot/PIC/port:
  `ge-0/0/0` (gigabit), `xe-0/0/0` (10G), `et-0/0/48` (100G/400G),
  `mge-0/0/0` (multi-gigabit copper).
- `ae<N>` for aggregated-Ethernet LAGs (zero-based).
- `lo0`, `irb` (integrated routing and bridging — VLAN SVIs),
  `em0`/`fxp0` (management).
- Per-unit families (`unit 0 family inet address X/N`) — every L3
  attribute lives under a unit.  Unit 0 is the canonical case.
- MTU lives at the parent-interface scope (not per-unit).
- Disable via `set interfaces X disable` (mirrors Cisco shutdown
  semantic).

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense identifies interfaces in two layers:

1. The BSD device — `em0`, `em1`, `igb0`, `vtnet0`, `mvneta0`, etc.
   This is the kernel-side name and lives in `<if>` elements.
2. The OPNsense **zone label** — `<wan>`, `<lan>`, `<opt1>`, `<opt2>`,
   …  This is the operator-facing identifier; firewall rules,
   gateways, DHCP scopes all reference the zone label rather than the
   BSD name.

```xml
<opnsense>
  <interfaces>
    <wan>
      <if>em0</if>
      <descr>WAN uplink</descr>
      <enable>1</enable>
      <ipaddr>198.51.100.10</ipaddr>
      <subnet>30</subnet>
      <ipaddrv6>2001:db8::10</ipaddrv6>
      <subnetv6>64</subnetv6>
      <mtu>1500</mtu>
    </wan>
    <lan>
      <if>em1</if>
      <descr>Internal</descr>
      <enable>1</enable>
      <ipaddr>10.0.10.1</ipaddr>
      <subnet>24</subnet>
    </lan>
  </interfaces>
</opnsense>
```

Key shape differences from Junos:

- The XML tag IS the operator-facing name; no separate naming key.
- `<enable>1</enable>` (or absent / `<enable/>`) replaces Junos's
  enable-by-default + `disable` keyword model.
- IPv4 + IPv6 stack on the SAME element (no `unit` / `family`
  hierarchy).  CIDR is split into `<ipaddr>` + `<subnet>` (length).
- MTU is an explicit `<mtu>` child element (range 576-9000).
- VLAN sub-interfaces use a synthesised `<if>vlan0.20</if>` device
  name; the parent `<vlans>/<vlan>` element carries the 802.1Q tag
  and the parent NIC.
- No L3-promotion concept — every OPNsense interface is L3 by
  definition; switching state is firmly absent.

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalInterface:
  name, description, enabled, interface_type, mtu,
  ipv4_addresses, ipv6_addresses,
  switchport_mode, access_vlan, trunk_allowed_vlans,
  trunk_native_vlan, voice_vlan, lag_member_of,
  dhcp_client, vrf
```

Junos -> OPNsense:

- `name`: **lossy** — Junos `ge-0/0/0` / `xe-0/0/47` / `ae0` / `irb`
  do not survive on OPNsense.  The port-rename mesh maps each source
  name to a zone label (`<wan>` / `<lan>` / `<optN>`); canonical
  preserves the source string verbatim.
- `description`: **good** — Junos `description` (quoted when
  whitespace) ↔ OPNsense `<descr>`.  Round-trip preserves text content.
- `enabled`: **good** — Junos `disable` keyword presence ↔ OPNsense
  `<enable>` element presence (inverted polarity, codec normalises).
- `interface_type`: **lossy** — Junos infers from media prefix
  (`ge-` → ethernetCsmacd, `lo` → softwareLoopback).  OPNsense doesn't
  surface a type field; cross-pair drops the type hint.
- `mtu`: **good** — Junos parent-interface `mtu N` ↔ OPNsense
  `<mtu>N</mtu>` — both render explicitly when set.
- `ipv4_addresses`: **good** — Junos `unit 0 family inet address X/N`
  ↔ OPNsense `<ipaddr>` + `<subnet>` (CIDR split).  Junos secondary
  addresses (multiple `set address` lines) collapse to the primary on
  OPNsense (`<ipaddr>` is single-valued; canonical takes one address
  per interface boundary).
- `ipv6_addresses`: **good** — Junos `family inet6 address X/N` ↔
  OPNsense `<ipaddrv6>` + `<subnetv6>`.  `scope` discriminator
  (global / link-local) preserved.
- `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan`: **unsupported** on OPNsense —
  see `firewall_role_mismatch.md`.
- `lag_member_of`: **lossy** — Junos `gigether-options 802.3ad ae0`
  back-points to `ae0`.  OPNsense `<laggs>/<lagg>/<members>` lists
  members in a comma-separated string under a `lagg<N>` parent.  Both
  codecs round-trip the back-pointer but the LAG name itself differs
  (`ae0` ↔ `lagg0`); port-rename mesh canonicalises.
- `dhcp_client`: **lossy** — Junos `family inet dhcp` ↔ OPNsense
  `<ipaddr>dhcp</ipaddr>`.  Neither codec currently wires
  `dhcp_client` through canonical; cross-pair drops pending wire-up.
- `vrf`: **unsupported** — Junos populates `CanonicalInterface.vrf`
  from `set routing-instances <name> interface <iface>` (GAP 6),
  but OPNsense has no VRF model — see `vrf_unsupported.md`.
