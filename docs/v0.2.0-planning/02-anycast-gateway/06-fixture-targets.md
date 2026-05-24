# 06 — Fixture targets

For each anycast-supporting vendor that lacks dedicated fixture
coverage today, this document lists URLs and sanitization needs.
Mirrors the format in
[`../../../tests/fixtures/real/WANTED.md`](../../../tests/fixtures/real/WANTED.md).

---

## Current coverage snapshot

| Vendor | Anycast fixture? | Anycast coverage details |
|---|---|---|
| **Juniper Junos** | yes | `tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set` — 7 IRB units (2021-2025, 2031) × v4 + v6 anycast + per-unit v4/v6 MAC overrides. Comprehensive for Junos. **No fixture work needed.** |
| **Arista EOS** | partial | Two Batfish fixtures cover VARP: `tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt` (6 SVIs, incl. secondary trailer on Vlan110, + system-wide MAC) and `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt` (8 SVIs + system-wide MAC). **Missing: IPv6 VARP** (`ipv6 address virtual` is EOS 4.30+ grammar; no fixture exercises it). |
| **Cisco IOS-XE CLI** | none | No SD-Access fabric-mode fixture in the corpus. The 12 existing IOS-XE fixtures are all classic non-fabric configs. **Highest-value gap.** |
| **Cisco NX-OS DAG** | none (Tier-D) | Covered under sibling task [`03-nxos-codec/05-fixture-targets.md`](../03-nxos-codec/05-fixture-targets.md) (the NX-OS codec doesn't exist yet — fixtures land with the codec). |
| **Aruba AOS-CX** | none (Tier-D) | Codec doesn't exist; fixtures land with the codec. |
| **FortiGate / MikroTik / OPNsense** | n/a | No native grammar — no fixture needed. |

---

## High-priority asks

### Cisco IOS-XE SD-Access fabric-mode config

**Why it matters:** the canonical anycast surface declares
`cisco_iosxe_cli` supports the path, but no real-capture fixture
exercises it. Without coverage, the round-trip invariant
(`parse(render(parse(raw))) == parse(raw)`) is only verified on
synthetic snippets. Real configs reveal edge cases like:

* line order (e.g. `fabric forwarding mode anycast-gateway` BEFORE
  `ip address` line — synthetic tests cover this but real configs
  may exercise other orderings)
* interaction with `vrf forwarding` declarations on the SVI
* the system-wide `fabric forwarding anycast-gateway-mac` line
  position in the rendered top-level (real configs often place it
  between `ip routing` and the static-route block)

**Provenance sources (in preference order):**

1. **Cisco DevNet Sandbox** — Catalyst 9300 / 9500 SD-Access
   sandbox at
   [`devnetsandbox.cisco.com`](https://devnetsandbox.cisco.com/RM/Topology).
   Free, no-NDA access; pull a `show running-config` from a
   fabric edge node, sanitize per
   [`../../../BUG_REPORTING.md`](../../../BUG_REPORTING.md), submit
   via `fixture_submission.yml`.
2. **Cisco Modeling Labs (CML)** — paid Cisco CML licenses include
   Catalyst-9000 SD-Access images. Operators with a CML license
   can boot a fabric edge node, configure 2-3 SVIs in anycast
   mode, dump the config. Same sanitization workflow.
3. **Public Catalyst-9000 SD-Access labs** — GitHub repos like
   [`solutionsanz/sda-deploy-as-code`](https://github.com/solutionsanz/sda-deploy-as-code)
   carry Apache-2.0-licensed Jinja2 templates rendered against
   synthetic data. Confirm license before submission.
4. **NTC-templates / NAPALM IOS-XE fixtures** — check
   [`networktocode/ntc-templates`](https://github.com/networktocode/ntc-templates)
   for an SDA snippet.
5. **Cisco DevNet learning labs** — the
   [SDA Sandbox Lab Guide](https://developer.cisco.com/learning/lab/sda-sandbox-fast-start/step/1)
   tutorials sometimes link to sanitized example configs.

**Sanitization needs:**

* Real WAN IPs (every `ip address`, `next-hop`, RADIUS / TACACS+
  shared-secret recipient) — replace per the existing
  fixtures' RFC-1918 / TEST-NET-2 convention.
* Hostnames containing customer / org names — replace with
  `c9300-edge-01` / similar.
* `enable secret` / `username privilege ... secret`
  hashes — leave as `$1$....$....` opaque hashes (the hash-
  portability policy preserves these). Do NOT replace with
  recognisable test hashes — the codec's hash-comparison logic
  has to see real hash shapes.
* `radius-server host KEY` shared secrets — replace per
  BUG_REPORTING.md convention (existing fixtures use
  `<7>054C2F3F2D` placeholders).
* Public SNMP community strings — replace with `public` if it
  isn't already.
* TACACS+ server addresses inside the management VRF — replace
  with TEST-NET-2 addresses.

**Filename convention:**
`<contributor-slug>_<platform-model>_<role>_iosxe<version>.txt`
— e.g. `devnetsandbox_c9300_sdaedge_iosxe1712.txt` (matches the
existing fixture naming convention in
`tests/fixtures/real/cisco_iosxe/`).

**Anycast lines that MUST survive sanitization:**

* `fabric forwarding anycast-gateway-mac <MAC>` (system-wide,
  top-level) — replace the MAC with `0001.c73a.0000` (the
  Cisco-documented test MAC); KEEP the line itself.
* `interface Vlan<N> / fabric forwarding mode anycast-gateway` —
  KEEP verbatim (no sensitive content).
* `interface Vlan<N> / ip address X MASK` — replace IPs with
  RFC-1918 / TEST-NET-2; KEEP the lines.

### Arista EOS IPv6 VARP (4.30+)

**Why it matters:** the canonical model declares
`/interfaces/interface/ipv6/address/virtual-gateway-address`
supported on `arista_eos`, but the two existing Batfish fixtures
are EOS 4.21 / 4.23 — pre-IPv6-VARP. Without an IPv6-VARP
real-capture, the codec's IPv6 path is only verified by synthetic
tests.

**Provenance sources:**

1. **EOS 4.30+ DC fabric capture** from an operator running
   dual-stack EVPN-VXLAN. Sanitize per
   `BUG_REPORTING.md`.
2. **Arista cEOS-lab + ContainerLab** — cEOS-lab on EOS 4.30.x can
   reproduce IPv6 VARP in a free, license-permissive way.
   `topology/leaf2.cfg` from a public ContainerLab dual-stack EVPN
   demo:
   * [`arista-netdevops-community/avd-eos-cli-lab`](https://github.com/arista-netdevops-community/avd-eos-cli-lab)
   * [`ContainerLab examples`](https://containerlab.dev/lab-examples/srl-evpn-mh/)
3. **Arista AVD-generated configs** — Arista's AVD (Ansible Validate
   Designs) project renders Apache-2.0 reference designs that
   include IPv6 VARP when the topology uses dual-stack overlays.
   [`arista-netdevops-community/ansible-avd-cloudvision-demo`](https://github.com/arista-netdevops-community/ansible-avd-cloudvision-demo).

**Sanitization needs:** same pattern as the existing Arista
fixtures (RFC-1918 / TEST-NET-2 for v4; `2001:db8::/32` for v6
documentation prefix; fake hashes; `public` community string).

**Anycast / VARP lines that MUST survive:**

* `ipv6 address virtual <2001:db8:X::1>/<prefix>` lines on each
  Vlan SVI.
* `ip virtual-router mac-address` (system-wide IPv4 MAC) AND, if
  applicable, the IPv6-MAC declaration if EOS introduces a
  separate one in newer releases (current 4.30 documentation
  shares the IPv4 MAC across families).
* `vrf <name>` declarations on the SVI when present (cross-vendor
  tests need to see VRF + anycast on the same record).

### Cisco NX-OS DAG seed (Tier-D — depends on NX-OS codec landing)

Covered in sibling task
[`../03-nxos-codec/05-fixture-targets.md`](../03-nxos-codec/05-fixture-targets.md);
the seed corpus is the Batfish
[`snapshots/nxos_evpn_l3vni/configs/`](https://github.com/batfish/lab-validation/tree/master/snapshots/nxos_evpn_l3vni/configs)
config pair (Apache-2.0 licensed). When the NX-OS codec lands, the
DAG fixtures land alongside; this anycast task's wiring (already
declared `supported` on the canonical paths once both codecs land)
just needs the round-trip assertion plumbed through
`test_real_captures.py`.

### Aruba AOS-CX (Tier-D — depends on AOS-CX codec landing)

Same pattern — AOS-CX codec doesn't exist yet. Provenance sources
documented in WANTED.md § Tier-D:
* [`arubanetworks/`](https://github.com/arubanetworks) GitHub org.
* NAPALM AOS-CX driver test fixtures.

---

## Specific URLs to ingest (concrete)

### Cisco DevNet — Catalyst-9000 SD-Access sandbox

URL: <https://devnetsandbox.cisco.com/RM/Topology?c=80c9bce5-6361-4ec9-b3cb-ebde7b1ad4cf>
(specific topology IDs change; check
<https://developer.cisco.com/site/sandbox/> for current SDA
sandbox).

Steps to capture:

1. Reserve the SDA sandbox (free; requires Cisco.com account, no
   NDA).
2. SSH to a fabric edge node (per the reservation email).
3. Run `show running-config` and copy the output.
4. Run `netcanon sanitize` (CLI or web UI) on the captured text.
5. Submit via `fixture_submission.yml` with the filename
   `devnetsandbox_c9300_sdaedge_iosxe<version>.txt`.

### Cisco SD-Access example configs (GitHub, Apache-2.0)

* <https://github.com/solutionsanz/sda-deploy-as-code/tree/main/example_outputs>
  — sanitized fabric-edge running-configs; confirm anycast lines
  present before submission.

### Arista AVD demo configs (GitHub, Apache-2.0)

* <https://github.com/arista-netdevops-community/avd-eos-cli-lab/tree/main/configs>
  — AVD-rendered configs that include VARP on each leaf.
* <https://github.com/aristanetworks/avd/tree/devel/ansible_collections/arista/avd/examples/single-dc-l3ls/intended/configs>
  — Arista's official AVD example output. Check for IPv6 VARP
  variants in the dual-stack examples.

### Cisco NX-OS DAG seed (handed off to T3)

* <https://github.com/batfish/lab-validation/tree/master/snapshots/nxos_evpn_l3vni/configs>
  (Apache-2.0; sanitized; the NX-1 / NX-2 pair exercises `ip
  address X anycast` + `fabric forwarding anycast-gateway-mac`).

---

## Submission workflow recap

Per [`../../../tests/fixtures/real/WANTED.md`](../../../tests/fixtures/real/WANTED.md)
§ "How to submit":

1. **Sanitize first.** Use `netcanon sanitize` (CLI or web UI)
   per [`../../../BUG_REPORTING.md`](../../../BUG_REPORTING.md).
2. **Confirm license.** Permissive (Apache / MIT / BSD) or CC0
   for your own contributions. Configs from a Cisco DevNet
   sandbox / Arista cEOS-lab / NX-OS Batfish snapshots are
   already permissively licensed.
3. **Open a Fixture Submission issue** via
   `fixture_submission.yml`.
4. **Or open a PR directly** dropping the file into
   `tests/fixtures/real/<vendor>/`, adding a row to
   [`NOTICE.md`](../../../tests/fixtures/real/NOTICE.md) with
   origin URL + license + what the file exercises, and updating
   [`RESULTS.md`](../../../tests/fixtures/real/RESULTS.md) if the
   new fixture changes a per-codec coverage tier.

---

## Summary of fixture work needed for this feature

| Priority | Vendor | Need | Provenance |
|---|---|---|---|
| **P1** | Cisco IOS-XE CLI | First-ever SDA-mode fixture | DevNet Sandbox or solutionsanz repo |
| **P2** | Arista EOS | IPv6 VARP (4.30+) | cEOS-lab + ContainerLab dual-stack EVPN demo |
| **P3** | Cisco NX-OS | DAG fixture pair | Batfish `nxos_evpn_l3vni` (sibling task) |
| **P4** | Aruba AOS-CX | First-ever fixture | `arubanetworks/` GitHub org (depends on AOS-CX codec) |

P1 is blocking for the cross-vendor migration tests in
[`04-test-plan.md`](04-test-plan.md) § "Cross-vendor" tests
involving `cisco_iosxe_cli` as source or target — without a
fixture, the `test_real_capture_anycast_invariant` assertion
can't include an IOS-XE check, and the round-trip metric for
this codec drops to "synthetic-only" certification level.

P2 is a soft-block — synthetic tests cover the IPv6 path, but the
EOS codec's certification tier in
[`tests/fixtures/real/RESULTS.md`](../../../tests/fixtures/real/RESULTS.md)
won't include IPv6 VARP until a real-capture exercises it.

P3 and P4 are deferred to their respective Tier-D codec tasks.
