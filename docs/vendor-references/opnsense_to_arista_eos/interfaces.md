# Interfaces: OPNsense versus Arista EOS

## OPNsense

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

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
  </interfaces>
</opnsense>
```

OPNsense interface layering:

- The XML tag IS the operator-facing name (`<wan>` / `<lan>` /
  `<opt2>`); the underlying BSD device lives in `<if>`.
- Every interface is L3 (firewall / router role); no `switchport`
  state is modelled.
- IPv4 address + mask use `<ipaddr>` + `<subnet>` (CIDR length).
  IPv6 uses `<ipaddrv6>` + `<subnetv6>`.
- DHCP client mode: `<ipaddr>dhcp</ipaddr>` (a literal string
  rather than an explicit address).

## Arista EOS

Source: [Arista EOS User Manual — Ethernet Ports](https://www.arista.com/en/um-eos/eos-ethernet-ports)
Retrieved: 2026-05-01

```
interface Ethernet1
   description "Spine uplink (L3 routed)"
   no switchport
   mtu 9214
   ip address 10.0.0.1/31
   ipv6 address 2001:db8:0:1::1/64
   ipv6 address fe80::1 link-local
!
interface Loopback0
   description "VTEP / router-id"
   ip address 10.255.0.1/32
!
interface Vlan100
   description "Tenant-A SVI"
   vrf TENANT_A
   ip address 10.100.0.1/24
```

Arista interface naming conventions:

- Physical: `Ethernet1`, `Ethernet48`; QSFP breakout
  `Ethernet50/1`.
- Logical: `Loopback0`, `Vlan100` (SVI), `Port-Channel10` (LAG;
  capital-C `Port-Channel`), `Management1`, `Vxlan1`.
- `no switchport` promotes a physical port to L3.
- Per-interface `vrf <name>` declares VRF membership.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields covered (`CanonicalInterface`).

- `name`: **lossy** — OPNsense `<wan>` / `<lan>` / `<opt2>` does
  not survive on Arista.  Port-rename mesh maps each source name
  to an Arista physical / logical name.
- `description`: **lossy** — OPNsense `<descr>` (no length
  limit) versus Arista 240-char limit (CLI parser truncates on
  re-apply).  OPNsense codec capability matrix declares
  `/interfaces/interface/config/description` lossy with this
  rationale.
- `enabled`: **good** — OPNsense `<enable>` element ↔ Arista `no
  shutdown` / `shutdown`.
- `interface_type`: **lossy** — OPNsense doesn't surface a type
  field; Arista codec defaults to `gig` speed-hint for unknown
  speeds (capability matrix lossy entry).  Cross-pair drops the
  hint.
- `mtu`: **good** — OPNsense `<mtu>` ↔ Arista `mtu N`.
- `ipv4_addresses`: **good** — OPNsense `<ipaddr>` + `<subnet>`
  ↔ Arista CIDR.  OPNsense's non-static keywords (`dhcp`,
  `pppoe`) skip this branch.
- `ipv6_addresses`: **good** — OPNsense `<ipaddrv6>` +
  `<subnetv6>` ↔ Arista `ipv6 address X/N`.  `scope`
  discriminator preserved.
- `switchport_mode` / `access_vlan` / `trunk_allowed_vlans` /
  `trunk_native_vlan` / `voice_vlan`: **not_applicable** —
  OPNsense never populates switchport state on parse.  Arista
  target accepts switchport-equivalent state but on this
  direction there is nothing to render.
- `lag_member_of`: **lossy** — OPNsense `<laggs>/<lagg>/<members>`
  back-points to `lagg<N>` on each member; Arista
  `channel-group N mode active` declares the back-pointer as
  `Port-Channel<N>`.  Both round-trip the back-pointer but the
  LAG name itself differs (zero-based `lagg0` ↔ one-based
  `Port-Channel1`); port-rename mesh canonicalises.
- `dhcp_client`: **lossy** — OPNsense `<ipaddr>dhcp</ipaddr>`
  (common on the WAN zone) ↔ Arista `ip address dhcp`.  Neither
  codec currently wires `dhcp_client` through.
- `vrf`: **not_applicable** — OPNsense `config.xml` has no VRF
  schema, so the field is always empty on OPNsense parse.  See
  `vrf_unsupported.md`.
