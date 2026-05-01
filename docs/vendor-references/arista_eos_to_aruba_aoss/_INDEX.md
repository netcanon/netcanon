# Arista EOS to Aruba AOS-S — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/arista_eos__aruba_aoss.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the
canonical schema definition.

This pair is the **inverse** of `aruba_aoss_to_arista_eos/`.
This is the asymmetrically harder direction — Arista EOS is a
DC-class switch with rich VRF / EVPN / VXLAN / dynamic routing
support; Aruba AOS-S is a campus L2/basic-L3 platform that
doesn't model any of those.  The "richer-source-than-target"
asymmetry concentrates the loss on:

* `vrf_unsupported.md` — Arista carries fully-modelled VRFs
  including L3 VNIs; Aruba has no concept.
* `vxlan_unsupported.md` — Arista's VXLAN/EVPN data has no
  Aruba target; entire surface drops.
* `routing_protocols_unsupported.md` — Arista's BGP / OSPF /
  IS-IS already parse-and-ignore on the canonical layer; Aruba
  has no render path either.
* `local_users.md` — Arista's `secret sha512 $6$...` (the
  modern default) requires re-keying on Aruba's SHA-1/bcrypt
  target.
* `system_services.md` — Arista's `clock timezone US/Pacific`
  zoneinfo form requires curated lookup to Aruba's
  `time timezone <minute-offset>`.

The good news: the keyword-stable surface (vlans / switchport /
static routes / SNMP v1+v2c / hostname / DNS / radius-server /
CIDR addressing) tracks closely because both vendors derive
their CLI lineage from Cisco IOS.

| Topic | Summary |
|---|---|
| `vlans.md` | Arista port-centric `switchport access vlan N` + `interface Vlan<N>` -> Aruba VLAN-centric `untagged 1-24 / ip address X/N`.  CIDR preserved. |
| `port_naming.md` | Arista `Ethernet1` (no speed) -> Aruba bare-numeric `1`; `Port-Channel<N>` (capital 'C') -> Aruba `Trk<N>`. |
| `ip_addressing.md` | CIDR preserved both ways; `mtu` not parsed by Aruba codec. |
| `static_routes.md` | CIDR preserved; per-VRF `ip route vrf X` drops on canonical (no VRF field on `CanonicalStaticRoute`); IPv6 routes drop on Aruba (codec gap). |
| `snmp.md` | v1/v2c clean (community / location / contact / trap_hosts); v3 USM SHA-256+ / AES-192+ collapses to Aruba's narrower SHA-1 + AES-128 + engineID re-key required. |
| `local_users.md` | Arista `privilege + role + secret sha512` -> Aruba two-role + `sha1 / bcrypt`; SHA-512 dominant case requires re-keying. |
| `lags.md` | Arista `Port-Channel<N>` (capital 'C') -> Aruba `Trk<N>`; MLAG drops; LACP active/passive/static round-trip. |
| `system_services.md` | Hostname (bare -> quoted) / DNS (flat -> priority-tagged) / NTP -> SNTP keyword change / zoneinfo timezone -> minute-offset timezone. |
| `vrf_unsupported.md` | Arista has rich VRF surface; Aruba has no VRF concept.  Major asymmetric loss. |
| `vxlan_unsupported.md` | Arista has rich VXLAN/EVPN surface; Aruba has no VXLAN concept.  Major asymmetric loss. |
| `routing_protocols_unsupported.md` | BGP/OSPF/IS-IS already parse-and-ignore on canonical; Aruba has no render path. |
| `radius.md` | Both vendors share Cisco-derived `radius-server host` form; round-trips cleanly. |

Retrieved 2026-04-30 to 2026-05-01.

See also: `../README.md` (citation cache layout),
`../aruba_aoss_to_arista_eos/_INDEX.md` (the inverse pair).
