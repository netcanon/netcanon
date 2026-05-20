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
| Cisco NX-OS | Data center switches with completely distinct grammar from IOS-XE | `datacenter/nxos-examples` (Apache 2.0) or operator Nexus 9000/3000 captures |
| Cisco IOS classic | Pre-IOS-XE; still in production at SMB | NTC-templates `tests/cisco_ios/`, NAPALM IOS fixtures |
| Juniper SRX | Security platform; distinct from EX/QFX/MX grammar | Juniper Day One Books PDFs (CC-BY), Junos Genius |
| Aruba AOS-CX | Modern Aruba replacing AOS-S | `arubanetworks/` GitHub org, NAPALM AOS-CX |
| Cisco IOS-XR | Service provider routing | NAPALM IOS-XR fixtures, containerlab `clab-topo` repos |
| VyOS | OSS Vyatta successor (LGPL caveat — careful licensing) | `vyos/vyos-build` examples |
| pfSense | BSD-similar to OPNsense; could share codec layer | pfSense forum captures |

If you're a maintainer at any of these vendors and would like to
collaborate on bringing your platform into Netcanon's matrix, open
an issue and we'll work the details.
