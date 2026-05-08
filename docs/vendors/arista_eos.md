# Arista EOS — What works for me?

If you operate Arista EOS devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

- **`arista_eos`** — EOS CLI parse + render.  **Certification:
  certified.**  Bidirectional.

The codec covers EOS 4.21 through 4.30+ across DCS-7150S, DC1-LEAF
(vEOS EVPN/MLAG), and DuplicatePrivate-style fixtures.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname`, `domain`, DNS / NTP / syslog servers
- Interfaces — `Ethernet<N>` and QSFP-breakout `Ethernet<N>/<M>`,
  Loopback, Management1; descriptions, IPv4 + IPv6, VRF binding
- VLANs — ID, name, tagged/untagged member lists
- Static routes
- LAGs (`Port-Channel<N>` reconciled with cross-vendor `ae<N>` /
  `Po<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 — community, contact, location, traps; v3 USM
  with auth + priv per user
- RADIUS — `radius-server host`
- Local users with hashed passwords — `secret sha512 $6$` and
  `secret 5 $1$` form-preserving cross-vendor migration
- MLAG — peer link + per-Port-Channel `mlag <id>` mapping
- VRF definitions (`vrf instance ...`)
- VXLAN — `interface Vxlan1` + `vxlan vlan <id> vni <vni>` mappings
  (ship-before-wire path stabilised)
- Routing instances (`/routing-instances/instance` declared
  supported on Arista — VRF + EVPN paths translate cleanly)

## Lossy paths

- See per-codec `CapabilityMatrix.lossy` declarations.  Most fields
  parse + render cleanly within the documented surface; lossy paths
  surface only when translating to vendors with sub-field drift
  (e.g. Arista → Cisco IOS-XE per-VRF static-route discriminator).

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall ACLs**
- **NAT**
- **IPsec VPN**
- **QoS**
- **Routing protocols** — `router bgp`, `router ospf`, EVPN
  redistribution policies (`address-family evpn`, route-map in/out
  filters) are parse-tolerant but not auto-rendered to other
  vendors
- **`management api http-commands`** / `daemon TerminAttr` —
  parse-tolerant
- **PKI / crypto material**

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`ksator_dcs_7150s64_eos4224.txt`** — DCS-7150S-64-CL on
  EOS 4.22.4M-2GB (256 lines; first Arista fixture); 5 local users
  mixing `nopassword` / `secret sha512 $6$` / `secret 5 $1$`;
  spanning-tree mstp, parse-and-ignore `router bgp` / `daemon
  TerminAttr` / `transceiver qsfp default-mode 4x10G`
- **`batfish_labval_dc1_leaf2a_eos4230.txt`** — vEOS DC1-LEAF2A
  EVPN leaf on EOS 4.23.0.1F (429 lines); MLAG peer link + 5
  Port-Channels, VXLAN1 overlay, 15 tenant VLANs, router bgp 65102,
  VRF definitions, Vlan3009 with VARP virtual-router MAC
- **`batfish_duplicateprivate_eos4211.txt`** — vEOS DuplicatePrivate
  on EOS 4.21.1.1F; private-ASN scenario (router bgp 65001 +
  neighbor remote-as 65001)
- **`karneliuk_a_eos1_eos4260.txt`** — vEOS on EOS-4.26.0.1F; full
  EVPN/VXLAN kitchen-sink (route-maps, BGP EVPN address-family,
  VLAN VNI mappings)

Spans 4 distinct EOS majors (4.21 + 4.22 + 4.23 + 4.26).

## Common gotchas

- **MLAG peer-link** — the parser correctly identifies `mlag` per
  Port-Channel and round-trips the peer-link mapping; cross-vendor
  rename surfaces correctly.
- **`channel-group` emission on member Ethernets** — render-side
  bug fixed early in the codec history (`channel-group N mode
  <mode>` on member Ethernet interfaces was missing); regression
  test pinned in `tests/unit/migration/test_arista_eos.py`.
- **EVPN/VXLAN ship-before-wire** — schema shipped early; render
  + parse for `interface Vxlan1` and per-VLAN VNI mappings stabilised
  in Wave 10β-B.
- **`service routing protocols model multi-agent`** — preserved as
  raw section; not in canonical model.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
