# Arista EOS to MikroTik RouterOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/arista_eos__mikrotik_routeros.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This is a **DC-class enterprise switch -> SMB/WISP router** pair.
Arista EOS targets DC fabrics (DCS-7280SR / 7050X / 7060X / 7300
class) with rich VRF / EVPN / VXLAN / dynamic-routing support;
MikroTik RouterOS targets SMB / WISP / power-user markets with a
router-first model and optional bridge for switching.  The wire
formats differ greatly (Arista IOS-style stanza grammar versus
RouterOS `/export` section-and-set form), and the underlying
philosophy differs even more (Arista interface-centric switchport
model + first-class VRF/EVPN versus RouterOS L3-by-default with
optional bridge for switching and limited VRF support).

This direction is the asymmetrically harder one.  Arista's
DC-fabric data (EVPN, MAC-VRF, L3-VRF, EVPN-VXLAN bindings) has no
first-class home on RouterOS, while the basic-services surface
(hostname / DNS / NTP / IPv4-IPv6 addresses / static routes / SNMP
v1+v2c / local users / RADIUS) round-trips with documented losses.
The "richer-source-than-target" asymmetry concentrates loss on:

* `vxlan_evpn_unsupported.md` — Arista's rich VXLAN / EVPN /
  MAC-VRF / L3-VRF surface drops; RouterOS has no render path.
  Major asymmetric loss.
* `local_users.md` — RouterOS does not surface password material
  in /export; even if Arista's SHA-512 hash were storable, the
  round-trip would break.  Operator MUST re-key.
* `snmp_aaa.md` — Arista SHA-2 / AES-192/256 / 3DES collapse to
  RouterOS's narrower SHA1 + AES-128 + DES surface.  Plus
  engineID-salted USM keys require operator re-key regardless.
* `system_services.md` — Arista `clock timezone US/Pacific`
  (older Olson alias) versus RouterOS `time-zone-name=
  America/Los_Angeles` (modern form); both Olson but operator
  mapping needed.

The keyword-stable surface (hostname / DNS / NTP servers / CIDR
addressing / SNMP v1+v2c) tracks reasonably well — Arista derives
its CLI from Cisco IOS, but RouterOS's `/export` form is
structurally distinct and requires per-section translation.

| Topic | Summary |
|---|---|
| `system_services.md` | Hostname / DNS / NTP / timezone / syslog.  Arista `clock timezone US/Pacific` (older Olson alias) versus RouterOS `time-zone-name=America/Los_Angeles` (modern form).  `dns domain` -> RouterOS `/ip dns set domain=` per-resolver attribute. |
| `interfaces.md` | Arista `Ethernet1` (no speed prefix) versus RouterOS flat `etherN` / `sfp-sfpplus<N>`.  Loopback (Arista first-class) versus RouterOS empty-bridge.  Management1 (Arista OOB) drops.  SVI (Arista `interface Vlan<N>` first-class) versus RouterOS `/interface vlan` + `/ip address` two-section form. |
| `vlans.md` | Arista interface-centric `switchport access vlan N` + `interface Vlan<N>` versus RouterOS two-plane model (`/interface vlan` for L3 + bridge VLAN filtering for L2).  Plane-2 wire-up partial in v1. |
| `static_routes.md` | Arista `ip route X/N <gw>` versus RouterOS `/ip route add dst-address=X/N gateway=Y`.  CIDR preserved both ways.  Per-VRF and blackhole semantics deferred (canonical schema gaps). |
| `snmp_aaa.md` | Arista `snmp-server community/host/user` versus RouterOS `/snmp` + `/snmp community add v3=yes`.  Algorithm downgrade (SHA-2/AES-256 -> SHA1/AES-128).  USM passphrases re-key required.  RADIUS: `radius-server host` versus `/radius add address=`. |
| `local_users.md` | Arista `privilege + role + secret sha512` versus RouterOS `/user add group=full`.  RouterOS does not surface password material in /export; render emits no secret; operator MUST re-key. |
| `lags.md` | Arista `Port-Channel<N>` (capital 'C') + `channel-group N mode active` versus RouterOS `/interface bonding name=bond1 mode=802.3ad`.  Mode mapping (active/passive/on -> 802.3ad/balance-xor).  MLAG drops. |
| `vxlan_evpn_unsupported.md` | Arista has rich `interface Vxlan1` + `router bgp / address-family evpn` + per-VLAN/VRF EVPN bindings.  RouterOS has no VXLAN/EVPN render path.  Major asymmetric loss. |

Retrieved 2026-05-01.

See also:
- `../README.md` (citation cache layout)
- `../mikrotik_routeros_to_arista_eos/_INDEX.md` (the inverse pair)
- `../arista_eos_to_aruba_aoss/_INDEX.md` (sibling Arista-source enterprise->campus pair)
- `../cisco_iosxe_cli_to_mikrotik_routeros/_INDEX.md` (sibling RouterOS-target enterprise pair)
