# Interfaces: FortiGate FortiOS versus OPNsense

Two firewall-class platforms with very different interface modelling
shapes — FortiGate uses an edit-table under `config system interface`,
OPNsense uses XML zone labels (`<wan>`, `<lan>`, `<optN>`) referencing
underlying BSD device names.

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Administration Guide — Interface
settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

```
config system interface
    edit "port1"
        set vdom "root"
        set ip 198.51.100.10 255.255.255.252
        set allowaccess ping https ssh
        set type physical
        set role wan
        set alias "Internet"
        set mtu-override enable
        set mtu 1500
        set status up
    next
    edit "internal"
        set vdom "root"
        set ip 10.0.10.1 255.255.255.0
        set type hard-switch
        set role lan
        set alias "Lab"
    next
    edit "port2.20"
        set vdom "root"
        set ip 10.10.20.1 255.255.255.0
        set type vlan
        set vlanid 20
        set interface "port2"
        set role lan
        set alias "Voice"
    next
end
```

FortiGate interface notes:

- Names are arbitrary strings (`port1` ... `portN` on most platforms,
  but operators often rename to roles like `internal` / `wan` / `dmz`).
- `set ip <addr> <mask>` carries the v4 primary as dotted-mask form;
  FortiOS also supports `set ipv6` blocks.
- `set type` enumerates `physical` / `vlan` / `aggregate` /
  `loopback` / `hard-switch` / `tunnel` (and others) — the canonical
  `interface_type` field is populated from this on parse.
- `set role` (lan / wan / dmz / undefined) is FortiGate-specific
  routing-and-policy hint with no canonical model.
- `set alias` caps at 25 characters and is the closest analogue to a
  description.
- VLAN sub-interfaces use `set type vlan / set vlanid N / set
  interface "<parent>"` plus a synthesised name like `port2.20`.
- LAGs use `set type aggregate / set member "port3" "port4" / set
  lacp-mode {active|passive|static}`.
- `set status up` ↔ canonical `enabled`.

## OPNsense

Source: [OPNsense Interfaces
manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-05-01

OPNsense identifies interfaces in two layers:

1. The BSD device — `em0`, `em1`, `igb0`, `vtnet0`, etc. — lives in
   `<if>` elements.
2. The OPNsense **zone label** — `<wan>`, `<lan>`, `<opt1>`,
   `<opt2>`... — is the operator-facing identifier; firewall rules,
   gateways, DHCP scopes all reference the zone label.

```xml
<opnsense>
  <interfaces>
    <wan>
      <if>em0</if>
      <descr>Internet</descr>
      <enable>1</enable>
      <ipaddr>198.51.100.10</ipaddr>
      <subnet>30</subnet>
      <ipaddrv6>2001:db8::10</ipaddrv6>
      <subnetv6>64</subnetv6>
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

OPNsense interface notes:

- The XML element name IS the operator-facing zone label.
- `<enable>1</enable>` (or absent) replaces FortiOS `set status up`.
- `<ipaddr>` + `<subnet>` use prefix-length, not dotted mask.
- VLAN sub-interfaces use a synthesised `<if>em1_vlan20</if>` BSD
  device name; the parent declaration in `<vlans>/<vlan>` carries the
  802.1Q tag and parent NIC.
- MTU is an explicit `<mtu>` child element (range 576-9000).
- No `role` field equivalent; the zone label is the implicit role.
- LAGs use `<laggs>/<lagg>` with members listed as a comma-separated
  string under a `lagg<N>` parent, then the lagg device shows up as
  `<if>laggN</if>` on the zone interface.

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

FortiGate -> OPNsense:

- `name`: **lossy** — FortiGate `port1` / `internal` does not survive
  on OPNsense.  The port-rename mesh maps each source name to a zone
  label (`<wan>` / `<lan>` / `<optN>`).  Canonical preserves the
  source string verbatim; the operator-facing zone label is invented
  by the rename mesh.
- `description`: **lossy** — FortiGate alias caps at 25 characters;
  OPNsense `<descr>` is unbounded.  The forward direction never
  truncates (25 chars fits in unbounded).  Marked lossy because
  `set comment` on a FortiGate static-route or interface block (a
  separate longer-string field) has no destination on OPNsense.
- `enabled`: **good** — FortiGate `set status up` / `down` ↔ OPNsense
  `<enable>1</enable>` / element absence.
- `interface_type`: **lossy** — FortiGate parse populates from `set
  type` (physical / vlan / aggregate / loopback / tunnel / hard-switch).
  OPNsense doesn't surface a type field; cross-pair drops the hint.
- `mtu`: **good** — FortiGate `set mtu-override enable / set mtu 1500`
  ↔ OPNsense `<mtu>1500</mtu>`.  Mechanical pass-through when
  mtu-override is set.  FortiGate-side default-MTU absence (no
  `set mtu` line) maps to no `<mtu>` element on OPNsense (both
  default-derived from interface speed).
- `ipv4_addresses`: **good** — FortiGate `set ip 10.0.10.1
  255.255.255.0` ↔ OPNsense `<ipaddr>10.0.10.1</ipaddr>` +
  `<subnet>24</subnet>`.  Mask-to-prefix conversion handled by codec
  helpers.  FortiGate secondary addresses (`set secondary-IP`) drop
  before reaching canonical (FortiGate parse only emits the primary).
- `ipv6_addresses`: **good** — FortiGate `set ip6-address 2001:db8::1/64`
  ↔ OPNsense `<ipaddrv6>` + `<subnetv6>`.  Link-local scope is FortiGate-
  side `set ip6-link-local-address` (rare); not currently modelled
  through canonical.
- `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan`: **unsupported** — neither vendor models a
  switching fabric beyond FortiGate's `hard-switch` sub-feature on
  low-end models, which the codec does not parse into switchport state.
- `voice_vlan`: **unsupported** — neither vendor has LLDP-MED voice-
  VLAN signalling in the canonical surface.
- `lag_member_of`: **lossy** — FortiGate aggregate uses `set type
  aggregate / set member "port1" "port2"` declared on the parent;
  members back-point to the aggregate name in canonical.  OPNsense
  `<laggs>/<lagg>` carries `<members>` and the parent shows up as
  `lagg<N>`.  Aggregate names differ (`agg1` ↔ `lagg0`) and the
  zero-vs-one-based numbering requires the rename mesh.
- `dhcp_client`: **lossy** — FortiGate `set mode dhcp` (rare on
  routed ports; common on the WAN edit when the ISP gives DHCP) ↔
  OPNsense `<ipaddr>dhcp</ipaddr>`.  Neither codec currently wires
  `dhcp_client` through canonical; cross-pair drops pending wire-up.
- `vrf`: **unsupported** — FortiGate `set vrf <id>` (FortiOS 7.x
  per-interface integer VRF) is not parsed by the codec into
  CanonicalInterface.vrf in v1; OPNsense has no VRF schema.
