# Wanted: real-world config captures

The fastest way to make Netcanon better is to feed it real configs it
hasn't seen yet.  This page documents the **specific gaps** in the
real-fixture corpus so contributors can target high-value additions
rather than re-submitting things we already cover.

Before submitting, read [`BUG_REPORTING.md`](../../BUG_REPORTING.md)
for the sanitization workflow and license requirements.  Every file
here ships under a permissive license (Apache / MIT / BSD / CC0) with
documented provenance in [`NOTICE.md`](NOTICE.md).  Submissions
violating either constraint can't be accepted no matter how rich the
grammar.

---

## Current corpus snapshot

| Codec | Fixtures | OS versions covered | Notable gaps |
|---|---|---|---|
| **cisco_iosxe** | 12 | 15.x (IOSv) / 16.9 / 17.3 / 17.9 / 17.12 | 17.13+ branch; tag-VLAN trunk on physical with sub-interfaces |
| **arista_eos** | 4 | 4.21 / 4.22 / 4.23 / 4.26 | 4.27+ / 4.30+ (current GA train); MLAG + EVPN VxLAN-multihoming |
| **aruba_aoss** | 6 | WB.16.08 / WC.16.07-11 / KB.15.15 | YA / RA software branches; 8400 chassis class |
| **fortigate** | 3 | FortiOS 7.2.13 / 7.6.6 | 6.4.x (still common); 7.0.x / 7.4.x bridge versions; SD-WAN multi-link with health-check |
| **junos** | 7 | 15.1 / 17.3 / 18.4 / 25.4 | 19.x / 20.x / 21.x / 22.x bridge; SRX security platform; vJunos / cMX from CML |
| **mikrotik** | 4 | RouterOS 6.48.1 / 6.48.6 / 7.18.2 | RouterOS 7.0-7.10 (early v7); CHR (cloud-hosted router); CCR variants |
| **opnsense** | 5 | OPNsense 25.x | 22.x / 23.x / 24.x branches; high-availability (CARP) deployment |

---

## High-priority asks

### Junos 19-22.x bridge

We have Junos 15.1, 17.3, 18.4 (legacy), and 25.4 (current).  The
**4-year gap from 19.x → 24.x is unrepresented**.  Junos grammar
evolved meaningfully through that period — set-form behaviour
around `set vlans <name> vxlan vni`, MPLS-EVPN family expansion,
`set chassis network-services` defaults.  A capture from each of
19.x, 20.x, 21.x, or 22.x would close a real gap.

Realistic sources we'd love to ingest:
* Operator-contributed captures from production MX / EX / QFX in
  any of those versions, sanitized per `BUG_REPORTING.md`
* Public lab repos using Juniper Apstra freeform Jinja templates
  rendered against synthetic data
* CML / vrnetlab demos that boot a 19-22.x Junos image

### FortiOS bridge versions

Current corpus is 7.2.13 + 7.6.6.  The **7.0.x and 7.4.x branches**
are widely deployed and have grammar differences worth pinning:
* 7.0.x: `config system` stanza order has subtle differences
* 7.4.x: introduced `config system standalone-cluster` for native HA
  declaration that 7.2 lacks
* 6.4.x: still common at SMBs; legacy syntax for SD-WAN

A capture per major-minor would be high-impact.

### Arista EOS 4.27+ (current GA train)

We jump from 4.26 (karneliuk) to nothing on the modern side.  4.30+
brought significant changes to EVPN underlay grammar
(`router bgp / address-family evpn / no neighbor X activate` →
opt-in instead of opt-out in some sub-cases) and CloudVision
configuration handlers.  Anyone running an Arista DC fabric in
4.30+ would have a capture that would meaningfully expand coverage.

### MikroTik RouterOS 7.0-7.10 (early v7)

Existing v7 capture is 7.18.2 (recent).  The early v7 series
(7.0 → 7.10) had grammar quirks that got smoothed out — `/interface
bridge` defaults changed, IPv6 ND addressed-prefix syntax was
revised.  Captures from that period would surface migration
behaviours the current codec hasn't been tested against.

### Sub-aspects worth specifically targeting

* **OPNsense 24.x or 23.x `config.xml`** with VLAN tagging on parent
  interfaces (not 802.1Q sub-interfaces).  We have grammar for VLANs
  but no real-capture for that exact form.
* **Aruba 8400 chassis class** AOS-S running-config.  Current corpus
  is 2920 / 2930F / 2930M / 5406Rzl2 — all stackable / modular but
  not the larger 8400 chassis platforms.
* **FortiGate physical-appliance VPN/IPsec heavy config** from any
  OS version.  Current FortiGate fixtures are SD-WAN / firewall
  focussed; an IPsec-heavy capture (multiple phase1-interface /
  phase2-interface stanzas) would exercise different code paths.

---

## How to submit

* **Sanitize first.**  Use `netcanon sanitize` (CLI or web UI) per
  [`BUG_REPORTING.md`](../../BUG_REPORTING.md).  Real WAN IPs,
  password hashes, RADIUS secrets, hostnames, and personal-identifier
  usernames must be replaced.
* **Confirm license.**  Permissive (Apache / MIT / BSD) or CC0 for
  your own contributions.  Configs you don't have the right to share
  (employer-confidential, customer-deployed-but-not-yours) cannot
  be accepted.
* **Open a Fixture Submission issue** via the `fixture_submission.yml`
  template.  Include the OS version, platform model, sanitization
  notes, and the source provenance.
* **Or open a PR directly.**  Drop the file into
  `tests/fixtures/real/<vendor>/`, add a row to
  [`NOTICE.md`](NOTICE.md) with origin URL + license + what the file
  exercises, and update [`RESULTS.md`](RESULTS.md) if the new fixture
  changes a per-codec coverage tier.

---

## Tier-D — entirely-new codec opportunities

These are vendor / platform classes Netcanon doesn't model yet.
Real-capture donations for these have **double value**: they
demonstrate the platform is worth modelling AND they become the
parser regression fixture once the codec ships.

| Platform | Why it's missing | Highest-value capture source |
|---|---|---|
| Cisco NX-OS | Data center switches with completely distinct grammar from IOS-XE | **Concrete seed corpus available** in [batfish/lab-validation](https://github.com/batfish/lab-validation) under Apache-2.0: `snapshots/nxos_hsrp/configs/{nxos1,nxos2}` (HSRP on SVI, the classic L3 redundancy pattern), `snapshots/nxos_evpn_l3vni/configs/{NX-1,NX-2}` (EVPN L3VNI with VRF + nve1 VTEP — distinct from IOS-XE's `interface nveN / member vni`), `snapshots/nxos_evpn_l2vni/configs/{NX-1,NX-2}` (L2VNI variant), plus `nxos_hsrp` + `nxos_ebgp_loop_prevention` + several others.  Together would cover hostname / vlan / vrf-context / interface Vlan SVI / nve1 VTEP / hsrp / fabric forwarding / router bgp address-family l2vpn evpn. |
| Cisco IOS classic | Pre-IOS-XE; still in production at SMB | NTC-templates `tests/cisco_ios/`, NAPALM IOS fixtures |
| Juniper SRX | Security platform; distinct from EX/QFX/MX grammar | Juniper Day One Books PDFs (CC-BY), Junos Genius |
| Aruba AOS-CX | Modern Aruba replacing AOS-S | `arubanetworks/` GitHub org, NAPALM AOS-CX |
| Cisco IOS-XR | Service provider routing | **Concrete seed corpus available** in [batfish/lab-validation](https://github.com/batfish/lab-validation) under Apache-2.0: `snapshots/cisco_xr_ios_vpnv4/configs/` (XR-XE VPNv4 interop), `snapshots/iosxr_ebgp_basic/configs/`, `snapshots/iosxr_ibgp_rr_over_ospf/configs/`.  Together exercise the IOS-XR `router bgp address-family vpnv4 unicast` + `route-policy in/out` + `vrf` grammar that differs sharply from IOS-XE. |
| VyOS | OSS Vyatta successor (LGPL caveat — careful licensing) | `vyos/vyos-build` examples |
| pfSense | BSD-similar to OPNsense; could share codec layer | pfSense forum captures |

If you're a maintainer at any of these vendors and would like to
collaborate on bringing your platform into Netcanon's matrix, open
an issue and we'll work the details.

---

## Cross-vendor canonical-model enrichment (v0.2.0+)

These aren't fixture gaps — they're **canonical-model gaps** in the
existing codecs.  A real capture exercising the surface already
exists in the corpus (or is one of the Tier-D batfish snapshots
above), but the canonical intent tree has no place to put the
parsed value, so it parses-and-ignores today.

### VRRP / HSRP / anycast-gateway (highest leverage)

**Shipped in v0.2.0: commits `c5da044` (Wave A schema) + `e542b49`
(Waves B + C, 7-codec wire-up).**  See
[`docs/v0.2.0-planning/01-vrrp-canonical/IMPLEMENTED.md`](../../../docs/v0.2.0-planning/01-vrrp-canonical/IMPLEMENTED.md)
and [`docs/v0.2.0-planning/02-anycast-gateway/IMPLEMENTED.md`](../../../docs/v0.2.0-planning/02-anycast-gateway/IMPLEMENTED.md)
for the closure stubs + deferral notes.  The per-vendor grammar
tables below remain useful reference for future codec additions
(NX-OS HSRP / IOS-XR VRRP land alongside their codecs in v0.3.0+).

The universal Layer-3 redundancy primitive.  Every shipped codec
has a vendor-native grammar for it.

| Vendor | Grammar | Where in corpus | Wire-up state |
|---|---|---|---|
| Cisco IOS-XE | `interface ... / vrrp N ip X / vrrp N priority P` | `batfish_iosxe_basic_vrrp.txt` | shipped (classic + modern AF group-id shell, lossy on AF priority) |
| Cisco NX-OS | `interface Vlan10 / hsrp N { preempt; ip X }` | (Tier-D — see above) | queued (lands with NX-OS codec, v0.3.0) |
| Arista EOS | `interface Vlan10 / ip address virtual X/Y` (VARP) | indirectly in `batfish_labval_dc1_leaf2a_eos4230.txt` + `batfish_eos_evpn_vlan_based_leaf.txt` | shipped (classic + modern multi-line + VARP) |
| Juniper Junos | `set interfaces irb unit N family inet address X virtual-gateway-address Y` (anycast) **or** `vrrp-group N virtual-address X` (classic) | `ksator_labmgmt_qfx10k2_junos173.set` (anycast form) | shipped (classic + anycast + per-unit MAC overrides) |
| Aruba AOS-S | `ip vrrp vrid N / virtual-ip-address X / enable` | not in corpus | shipped (parse + render; fixture still wanted) |
| FortiGate | `config router vrrp / edit N / set vrip X` | not in corpus | shipped (parse + render with implicit `set version 3` on vrip6; fixture still wanted) |
| MikroTik | `/ip address vrrp` (older) or `/ip vrrp` | not in corpus | shipped (two-stage `/interface vrrp` + `/ip address` correlation; fixture still wanted) |
| OPNsense (CARP) | `<virtualip><vip><mode>carp</mode>...` | not in corpus | shipped (CARP variant via `mode="carp"` discriminator; fixture still wanted) |

Canonical surface as shipped: **HYBRID resolution** (per
`docs/v0.2.0-planning/README.md` § "Cross-task synthesis").  Classic
FHRP lives on `CanonicalInterface.vrrp_groups: list[CanonicalVRRPGroup]`
with `mode in {"vrrp", "hsrp", "carp"}` discriminator; anycast lives
on `CanonicalIPv4Address.virtual_gateway_address` /
`CanonicalIPv6Address.virtual_gateway_address` per-IP plus a
chassis-wide `CanonicalIntent.anycast_gateway_mac` — NOT merged into
the VRRP group.  Total: 6079 insertions, +180 tests across Wave A
schema (31) + Waves B+C codec wire-up (149).

### Anycast gateway (Tier-2 enrichment, after VRRP/HSRP)

**Shipped in v0.2.0 across 3 codecs: commit `e542b49`.**  Distinct
from VRRP in semantics — anycast-gateway has no group ID, just a
stable IP that's present on every leaf and never moves on host
migration.  The DC-fabric audience cares most.

| Vendor | Grammar | Wire-up state |
|---|---|---|
| Arista EOS | `ip address virtual X/Y` (VARP) | shipped (system MAC + IPv4/IPv6 VARP + `secondary` trailer) |
| Juniper Junos | `family inet address X virtual-gateway-address Y` + `virtual-gateway-v4-mac Z` | shipped (per-unit MAC overrides, IRB-to-VLAN fold preserves new fields) |
| Cisco NX-OS | `fabric forwarding anycast-gateway-mac X` (system) + per-SVI `ip address X anycast` + `fabric forwarding mode anycast-gateway` | queued (lands with NX-OS codec, v0.3.0) |
| Cisco IOS-XE | `fabric forwarding mode anycast-gateway` (SD-Access) | shipped (per-SVI mirror semantics + system anycast-gateway-mac in 3 MAC formats) |

Resolution: independent per-address fields (NOT merged with VRRP)
— see `docs/v0.2.0-planning/02-anycast-gateway/IMPLEMENTED.md`.
The remaining 4 codecs (cisco_iosxe NETCONF stub, aruba_aoss,
fortigate_cli, mikrotik_routeros, opnsense) declare anycast
`unsupported` — their grammar doesn't model anycast natively.
