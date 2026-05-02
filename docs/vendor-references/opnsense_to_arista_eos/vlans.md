# VLANs: OPNsense versus Arista EOS

## OPNsense

Source: [OPNsense Devices manual — VLAN tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

```xml
<opnsense>
  <vlans>
    <vlan>
      <if>em1</if>
      <tag>10</tag>
      <pcp>0</pcp>
      <descr>USERS</descr>
      <vlanif>em1_vlan10</vlanif>
    </vlan>
    <vlan>
      <if>em1</if>
      <tag>100</tag>
      <pcp>0</pcp>
      <descr>TENANT_A_DATA</descr>
      <vlanif>em1_vlan100</vlanif>
    </vlan>
  </vlans>
</opnsense>
```

OPNsense VLAN model:

- Each `<vlan>` element carries `<if>` (parent NIC), `<tag>`
  (802.1Q ID, 1-4094), `<pcp>` (priority code point, default 0),
  `<descr>` (free-form description), `<vlanif>` (synthesised
  device name).
- A VLAN exists ONLY as a tagged sub-interface on ONE parent
  NIC.  There is no per-VLAN port-membership concept; untagged
  traffic is the parent NIC's native frames.
- The L3 address (where one exists) lives on a sibling `<optN>`
  zone interface that references the `<vlanif>` device name —
  not on the `<vlan>` element itself.

## Arista EOS

Source: [Arista EOS VLAN Configuration](https://www.arista.com/en/um-eos/eos-vlan-configuration)
Retrieved: 2026-05-01

```
vlan 10
   name USERS
!
vlan 100
   name TENANT_A_DATA
!
interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Ethernet3
   switchport mode trunk
   switchport trunk allowed vlan 10,100
!
interface Vlan100
   description "Tenant-A SVI"
   ip address 10.100.0.1/24
```

Arista VLAN model:

- `vlan <id>` stanza carries `name <X>` (32-character truncation).
- Per-port VLAN intent lives on each interface (`switchport
  access vlan` / `switchport trunk allowed vlan`); the
  arista_eos parser transposes this into `CanonicalVlan.
  tagged_ports` / `untagged_ports` lists.
- SVIs are first-class `interface Vlan<N>` records with their
  own L3 attributes.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields covered (`CanonicalVlan`).

- `vlans[].id`: **good** — OPNsense `<tag>N</tag>` ↔ Arista
  `vlan N`.  Both vendors share 1-4094.
- `vlans[].name`: **lossy** — OPNsense's `<descr>` is the only
  label field; canonical `name` and `description` both populate
  from it on parse, so both fields carry the same text.  Arista
  `name <X>` lands cleanly with no Arista-side loss; the loss is
  upstream (OPNsense never carried distinct fields).
- `vlans[].description`: **lossy** — same rationale as `name`.
- `vlans[].tagged_ports` / `untagged_ports`: **not_applicable** —
  OPNsense never populates per-VLAN port-membership lists on
  parse (no per-VLAN port concept).  Arista target render emits
  no `switchport access` / `trunk allowed` lines because the
  canonical lists are empty.  Operator must reconstruct trunk
  topology manually.
- `vlans[].ipv4_addresses` (SVI absorption): **lossy** —
  OPNsense doesn't have a first-class SVI concept; the closest
  equivalent is a zone interface (`<opt2>`) referencing the
  VLAN's `<vlanif>` device name with the IP on the zone.  The
  opnsense codec does not currently project the zone-side IP
  back onto a `CanonicalVlan.ipv4_addresses` record; cross-pair
  render emits no `interface Vlan<N>` SVI block on the Arista
  target.
