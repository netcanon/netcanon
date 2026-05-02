# Interfaces: OPNsense versus Junos

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense identifies interfaces in two layers:

1. The BSD device — `em0`, `em1`, `igb0`, `vtnet0`, `mvneta0`, etc.
   Lives in `<if>` elements; this is the kernel-side name.
2. The OPNsense **zone label** — `<wan>`, `<lan>`, `<opt1>`, `<opt2>`,
   …  This is the operator-facing identifier; firewall rules,
   gateways, DHCP scopes all reference the zone label rather than
   the BSD name.

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

OPNsense interface notes:

- The XML tag IS the operator-facing name; no separate naming key.
- `<enable>1</enable>` (or absent / `<enable/>`) replaces an
  enable/disable keyword model.
- IPv4 + IPv6 stack on the SAME element; CIDR is split into
  `<ipaddr>` + `<subnet>` (length).
- MTU is an explicit `<mtu>` child element (range 576-9000).
- VLAN sub-interfaces use a synthesised `<if>vlan0.20</if>` device
  name.
- Every OPNsense interface is L3 by definition; switching state is
  firmly absent.

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
set interfaces ge-0/0/9 disable
```

Junos interface naming:

- Physical port names embed media + slot/PIC/port:
  `ge-0/0/0` (gigabit), `xe-0/0/0` (10G), `et-0/0/48` (100G/400G).
- `ae<N>` for aggregated-Ethernet LAGs; `lo0`, `irb`, `em0`/`fxp0`.
- Per-unit families (`unit 0 family inet address X/N`) — every L3
  attribute lives under a unit.
- MTU at parent-interface scope (not per-unit).
- Disable via `disable` keyword.

## Cross-vendor mapping

OPNsense -> Junos:

- `name`: **lossy** — OPNsense `<wan>` / `<lan>` / `<optN>` zone
  labels do not survive on Junos; the port-rename mesh maps each
  source name to a Junos media-prefix form (`ge-0/0/0`).  Canonical
  preserves the source string verbatim.
- `description`: **good** — OPNsense `<descr>` ↔ Junos `description`
  (Junos quotes when whitespace present).  Round-trip preserves
  text.
- `enabled`: **good** — OPNsense `<enable>` element presence ↔
  Junos `disable` keyword presence (inverted polarity, codec
  normalises).
- `interface_type`: **lossy** — OPNsense doesn't surface a type
  field; Junos infers from media prefix (`ge-` → ethernetCsmacd).
  Cross-pair recovers a sensible inferred type from the renamed
  Junos interface but the source signal was empty.
- `mtu`: **good** — OPNsense `<mtu>` ↔ Junos parent-scope `mtu N`.
- `ipv4_addresses`: **good** — OPNsense `<ipaddr>` + `<subnet>` ↔
  Junos `unit 0 family inet address X/N`.  OPNsense's single-
  address-per-interface model is a strict subset of Junos's
  multi-address surface.
- `ipv6_addresses`: **good** — OPNsense `<ipaddrv6>` + `<subnetv6>`
  ↔ Junos `family inet6 address X/N`.  `scope` discriminator
  (global / link-local) preserved.
- `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan`: **not_applicable** on the
  OPNsense source — OPNsense never populates these on parse (no
  switchport concept), so the fields are structurally empty.
- `lag_member_of`: **lossy** — OPNsense reverse-links member
  interfaces to `lagg<N>` parent; Junos uses `gigether-options
  802.3ad ae<N>` form.  LAG name itself differs (`lagg0` ↔ `ae0`);
  port-rename mesh handles the substitution.
- `dhcp_client`: **lossy** — OPNsense `<ipaddr>dhcp</ipaddr>` ↔
  Junos `family inet dhcp`.  Neither codec currently wires
  `dhcp_client` through canonical; cross-pair drops pending wire-up.
- `vrf`: **not_applicable** — OPNsense has no VRF, so the field
  is always empty on parse from this source; Junos target supports
  it (GAP 6) but receives nothing to render.
