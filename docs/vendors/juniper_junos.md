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

## L3 redundancy: VRRP + virtual-gateway-address anycast

**New in v0.2.0** (Waves B + C — VRRP and anycast-gateway wire-up).

Junos's grammar is distinctive: every redundancy sub-command nests
under a parent `family inet address <X>/<prefix>` line, so the
address acts as the binding anchor.  The canonical model uses
interface-scope (`vrrp_groups` on `CanonicalInterface`), so the
parser records the binding-address anchor for round-trip; render-
side re-attaches the group to the primary address.  Exercised by the
QFX10K2 fixture (`ksator_labmgmt_qfx10k2_junos173.set`).

### Classic vrrp-group grammar

```text
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 virtual-address 10.1.1.1
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 priority 200
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 no-preempt
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 description "core-gw"
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 authentication-type simple
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 authentication-key "OPAQUE-KEY"
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 track interface ge-0/0/1
```

Sub-commands handled: `virtual-address`, `priority`, `preempt` /
`no-preempt`, `description`, `authentication-type` +
`authentication-key` (merged into the canonical
`<scheme>:<value>` form), `track interface` (per-iface `priority-cost`
decrement is lossy), `fast-interval` (sub-second; drops to lossy as
canonical `advertisement_interval` is integer-seconds).  Multiple
groups can attach to the same address.

### Anycast-gateway (virtual-gateway-address)

DC-fabric anycast on the IRB unit — both halves of the surface
arrive on one `set` line:

```text
set interfaces irb unit 2021 family inet address 10.221.0.5/16 virtual-gateway-address 10.221.0.1
set interfaces irb unit 2021 family inet6 address fd20:2021::5/64 virtual-gateway-address fd20:2021::1
set interfaces irb unit 2021 family inet6 address fe80:2021::1/64
set interfaces irb unit 2021 virtual-gateway-v4-mac 02:00:21:00:00:01
set interfaces irb unit 2021 virtual-gateway-v6-mac 02:00:21:06:00:01
```

Canonical mapping:

- `family inet address X/M virtual-gateway-address Y` populates
  `CanonicalIPv4Address(ip=X, prefix_length=M,
  virtual_gateway_address=Y)` — both halves on the same record.
- `family inet6 address X/M virtual-gateway-address Y` mirrors the
  IPv4 path onto `CanonicalIPv6Address`.  The auto-emitted
  `fe80::/10` link-local lives on a SEPARATE record with
  `scope="link-local"` and no anycast companion.
- `virtual-gateway-v4-mac <MAC>` / `-v6-mac <MAC>` are per-IRB-unit
  (one MAC per address-family per unit) and apply to every
  global-scope address on the unit.  They land on
  `CanonicalIP{v4,v6}Address.virtual_gateway_mac`; the MAC line can
  come BEFORE or AFTER the address lines (order-independent parse).

### Known limitations

- **No system-wide anycast-gateway MAC.**  Junos models MAC per IRB
  unit / per family.  `CanonicalIntent.anycast_gateway_mac`
  (Arista's `ip virtual-router mac-address` / Cisco's
  `fabric forwarding anycast-gateway-mac`) is silently dropped on
  render — operator must distribute the value across every IRB
  unit's per-address MAC on the receiving Junos side.  The
  capability matrix declares `/anycast-gateway-mac` `unsupported`
  on the Junos codec.
- **Per-address binding round-trip.**  Junos binds the group to the
  address; the canonical model is interface-scope.  Parser picks
  the source address as the anchor; render re-attaches to the
  primary address.  If multiple addresses on the same unit each
  carry a vrrp-group in the source, the cross-vendor round-trip
  through interface-scope may consolidate them onto the primary
  (lossy when both addresses are present).
- **Track priority-cost decrement is lossy** (mirror of IOS-XE
  decrement / Arista decrement — only the interface name survives).
- **Sub-second `fast-interval`** drops to canonical
  `advertisement_interval=1` (lossy).

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model; see `02-per-vendor-grammar.md` §
  "Juniper Junos" for the per-address-binding rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (`01-canonical-model.md` covers the
  decision to keep per-IP virtual_gateway_mac despite no other
  vendor having it).

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
