# Juniper Junos — What works for me?

If you operate Juniper Junos devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

- **`juniper_junos`** — `set`-form CLI parse + render.
  **Certification: certified.**  Bidirectional.

The codec works against `show configuration | display set` output
across Junos majors from 15.1 through 25.4.  Fixtures cover QFX,
EX, and vMX-style platforms; the set-form grammar is consistent
across Junos platform families, so SRX / MX would parse + render
through the same pipeline (insofar as the surfaces overlap with
Tier 1+2; SRX firewall / NAT / VPN are Tier-3 deferred regardless).
SRX-platform fixtures aren't in the corpus yet — operator captures
welcome.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname` (via `set system host-name`), `domain`, DNS / NTP /
  syslog servers
- Interfaces — `set interfaces <name> unit <N> family inet address`
  CIDR form; IPv4 + IPv6; per-unit and bare-interface forms
- VLANs (`set vlans <name> vlan-id <id>`) with VLAN-centric
  membership projection
- Static routes (`set routing-options static route ...`)
- LAGs (`ae<N>` aggregated-ethernet, reconciled with cross-vendor
  names like `Port-channel<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 USM — `set snmp v3 usm local-engine user`
  authentication-key + privacy-key forms; VACM mappings via
  `security-to-group`
- RADIUS — `set system radius-server`
- DHCP server pools (where present)
- Local users with hashed passwords — `$1$` / `$5$` / `$6$` / `$9$`
  form-preserving migration
- **`apply-groups`** + group content — preserved byte-for-byte
  through round-trip (Junos-specific structural primitive)
- Routing instances + VRFs

## Lossy paths

- **`/routing-instances/instance`** — VRFs translate cleanly between
  Junos and Arista EOS; sub-field drift exists when targeting
  Cisco IOS-XE (per-VRF static-route VRF discriminator drops on
  round-trip).
- EVPN Type-5 routes — schema shipped, codec wire-up in progress;
  ship-before-wire path.

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall filters** — `set firewall family inet filter ...`
- **NAT** — `set security nat source rule-set ...`
- **IPsec VPN** — `set security ipsec ...`
- **QoS / CoS** — `set class-of-service ...`
- **Routing protocols** — BGP / OSPF / IS-IS / MPLS / LDP stanzas
  (informational only)
- **PKI / crypto material**

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`buraglio_netlab_junos184.set`** — Junos 18.4R1-S1.1 from a
  public ES.net netlab-ns demo (Nick Buraglio, BGP / IS-IS / MPLS
  parse-tolerance)
- **`ksator_labmgmt_qfx5100_junos173.set`** — Junos 17.3R1.10 on
  QFX5100 (DC access leaf with `apply-groups POC_Lab`, ae0/ae1 LAGs,
  16 VLANs)
- **`ksator_labmgmt_ex4550_junos151.set`** — Junos 15.1R6.7 on
  EX4550 (oldest Junos major in corpus; xe-0/0/0-2 trunk ports
  with `vlan members`)
- **`batfish_evpntype5_router1_junos2541.set`** — Junos 25.4R1.12
  EVPN Type-5 lab snapshot (4 IRB sub-interfaces, VRRP, VXLAN VNIs)
- **`batfish_l3vpn_pe1_junos2541.set`** — Junos 25.4R1.12 MPLS L3VPN
  PE (VRF + iBGP `family inet-vpn unicast` + LDP)

Five real captures covering four distinct Junos majors: 15.1, 17.3,
18.4, 25.4 (the 25.4 captures are two scenario-distinct EVPN-Type-5
and MPLS L3VPN snapshots).

## Common gotchas

- **`apply-groups` content** is preserved byte-for-byte but is
  **opaque to translation** — group content stays in source-vendor
  syntax; the renaming operation (port / VLAN / user-name etc.)
  doesn't descend into `set groups ...` content.  When migrating
  TO Junos from a non-Junos source, configs come out flat (no
  apply-groups inheritance).
- **Root authentication** (`set system root-authentication
  encrypted-password`) is parse-and-ignore — root auth is
  distinct from user accounts and not in the canonical
  `local_users` model.
- **Bare-interface forms** (interface declared via `unit 0 family
  ethernet-switching ...` only) used to be dropped on render until
  the placeholder-line fix landed; now preserved with empty unit
  attributes.
- **Set-form vs hierarchical** — Netcanon parses `set`-form only.
  If your captured config is in hierarchical form (curly-brace
  nesting), pipe through `display set` first.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) — when something
  doesn't translate cleanly
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
