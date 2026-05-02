# Interfaces: OPNsense versus FortiGate FortiOS

Reverse direction of the FortiGate-to-OPNsense pair.  See the
forward-direction `fortigate_cli_to_opnsense/interfaces.md` for the
shared modelling backdrop; this file documents OPNsense-source-side
specifics and the asymmetric losses on this direction.

## OPNsense

Source: [OPNsense Interfaces
manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <interfaces>
    <wan>
      <if>em0</if>
      <descr>Internet</descr>
      <enable>1</enable>
      <ipaddr>dhcp</ipaddr>
      <ipaddrv6>track6</ipaddrv6>
      <track6-interface>wan</track6-interface>
      <mtu>1500</mtu>
    </wan>
    <lan>
      <if>em1</if>
      <descr>Lab</descr>
      <enable>1</enable>
      <ipaddr>10.0.10.1</ipaddr>
      <subnet>24</subnet>
    </lan>
    <opt2>
      <if>em1_vlan20</if>
      <descr>Voice</descr>
      <enable>1</enable>
      <ipaddr>10.10.20.1</ipaddr>
      <subnet>24</subnet>
    </opt2>
  </interfaces>
</opnsense>
```

OPNsense notes:

- The XML element name IS the operator-facing zone label
  (`<wan>` / `<lan>` / `<optN>`) — there are no separate `<name>`
  child elements.
- The BSD device name lives in `<if>`.  VLAN child devices are
  named `<parent>_vlan<tag>` by convention.
- `<ipaddr>` accepts non-IP keywords: `dhcp` / `pppoe` / `pptp` /
  `l2tp` (per-protocol acquisition).  The non-static branches
  populate `dhcp_client` (or extended state) on canonical when wire-up
  lands.
- `<ipaddrv6>` accepts `dhcp6` / `track6` / `slaac` / `6rd` / `6to4`
  in addition to a literal address; non-static branches do not
  populate `ipv6_addresses` on canonical.
- `<mtu>` is an explicit child element (576-9000).

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/interfaces.md` for the FortiGate
shape.  Key points relevant to this direction:

- FortiGate names are arbitrary edit strings (`port1`...`portN`,
  but operators rename to roles).
- `set ip <addr> <mask>` uses dotted-mask form.  Cross-pair
  prefix-to-mask conversion is mechanical.
- `set type` enumerates physical / vlan / aggregate / loopback /
  tunnel / hard-switch.
- `set alias` caps at 25 characters.
- `set status up` / `down` ↔ canonical `enabled`.

## Cross-vendor mapping (OPNsense -> FortiGate)

- `name`: **lossy** — OPNsense zone labels (`<wan>`, `<lan>`,
  `<opt2>`) do not survive on FortiGate's flat naming.  The
  port-rename mesh maps each source label to a FortiGate-shape name
  (`port1` / `internal` / `wan-edge` etc.).  Canonical preserves the
  source string verbatim.
- `description`: **lossy** — OPNsense `<descr>` is unbounded;
  FortiGate `set alias` caps at 25 characters.  Long OPNsense
  descriptions truncate on FortiGate render.  The OPNsense codec
  capability matrix declares
  `/interfaces/interface/config/description` lossy with this
  rationale.
- `enabled`: **good** — `<enable>1</enable>` ↔ `set status up`;
  element absence ↔ `set status down`.
- `interface_type`: **lossy** — OPNsense doesn't surface a type
  field; FortiGate has `set type` but the value is empty after
  OPNsense parse (canonical drops the inference).
- `mtu`: **good** — OPNsense `<mtu>1500</mtu>` ↔ FortiGate
  `set mtu-override enable / set mtu 1500`.  Mechanical pass-through.
- `ipv4_addresses`: **good** — OPNsense `<ipaddr>` + `<subnet>` ↔
  FortiGate `set ip` (mask-form synthesised from prefix-length).
  OPNsense's non-static keywords (`dhcp` / `pppoe`) skip this branch
  and would feed `dhcp_client` once wire-up lands.
- `ipv6_addresses`: **good** — OPNsense `<ipaddrv6>` + `<subnetv6>` ↔
  FortiGate `set ip6-address`.  OPNsense `track6` / `dhcp6` / `slaac`
  / `6rd` / `6to4` are non-static keywords that don't populate
  canonical (no destination on FortiGate either).
- `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan`: **not_applicable** —
  OPNsense never populates these on parse (no switching fabric).
  FortiGate target accepts hard-switch sub-feature on a few
  low-end models but the codec doesn't synthesise switchport state.
- `lag_member_of`: **lossy** — OPNsense `<laggs>/<lagg>/<members>`
  back-points members to `lagg<N>`; FortiGate aggregate uses
  `set type aggregate / set member` on the parent.  Member naming
  differs (BSD `em2` versus FortiGate `port3`); rename mesh
  canonicalises.
- `dhcp_client`: **lossy** — OPNsense `<ipaddr>dhcp</ipaddr>`
  (common on the WAN zone) ↔ FortiGate `set mode dhcp`.  Neither
  codec wires `dhcp_client` through canonical; cross-pair drops
  pending wire-up.
- `vrf`: **not_applicable** — OPNsense has no VRF schema (canonical
  field always empty on parse); FortiGate target accepts
  `set vrf <id>` but nothing to render.
