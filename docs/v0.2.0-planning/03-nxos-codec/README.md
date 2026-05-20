# T3 — Cisco NX-OS bidirectional codec (design artifacts)

Status: **research / design only**. No production source code modified
by this planning pass. When the codec lands, individual PRs reference
the files in this folder by relative path.

Target release: **v0.3.0+** (gates on T1 VRRP/HSRP + T2 anycast-gateway
canonical-model landings; see `../README.md` dependency graph).

---

## 1. Executive summary

Cisco NX-OS is Cisco's data-center NOS shipping on the Nexus 3000 /
5000 / 7000 / 9000 series.  It is a **completely different CLI grammar
from IOS-XE** — same vendor, different parser.  NX-OS dominates the
modern enterprise DC and EVPN-VXLAN fabric build-out; adding a
bidirectional codec is the largest Tier-D opportunity in the Netcanon
backlog by far.

This folder breaks the codec into **four landable PRs**, each ~400-900
LOC, that an implementor can review and merge independently.  Each
PR builds on the last; the corpus + capability declarations sharpen
at every phase.

Total estimated LOC across the four PRs: **~2,400-3,200**, plus
**~1,800-2,400 LOC of tests** (~60% LOC ratio mirrors the existing
codecs).

---

## 2. NX-OS grammar surface this codec must handle

Sourced from the batfish/lab-validation seed corpus (Apache-2.0;
see `05-fixture-targets.md` for per-file inventory).  All grammar
samples below were extracted from real configs fetched via curl.

**Top-level commands** the codec needs to recognise:

| Stanza | Frequency in corpus | Phase |
|---|---|---|
| `!Command: show running-config` (banner) | every file | 1 (probe) |
| `version <N.N(N)>` | every file | 1 |
| `hostname <name>` | every file | 1 |
| `vdc <name> id N / limit-resource ...` | every file | 1 (preserve raw) |
| `feature <name>` | every file (variable list) | 1 |
| `username <name> password <hash-type> <hash> role <r>` | every file | 2 |
| `vlan <N>` / `vlan <id-list>` | every file | 2 |
| `vlan <N> / vn-segment <vni>` | EVPN snapshots | 4 |
| `vrf context <name>` | every file (mgmt at minimum) | 3 |
| `vrf context <name> / vni N / rd auto / address-family ipv4 unicast / route-target both auto evpn` | EVPN L3VNI | 4 |
| `interface Ethernet<slot>/<port>[/<sub>]` | every file | 1/2 |
| `interface Vlan<N>` (SVI; created by `feature interface-vlan`) | HSRP + EVPN | 2 |
| `interface port-channel<N>` | HSRP | 2 |
| `interface nve1 / source-interface loopback0 / host-reachability protocol bgp / member vni <N>` | EVPN | 4 |
| `interface loopback<N>` | most files | 2 |
| `interface mgmt0` (the dedicated OOBM port) | every file | 1 |
| `ip route [vrf X] <dest>/<prefix-len> <gw>` | most files | 2 |
| `router bgp <asn>` | BGP / EVPN | (3 / Tier-3) |
| `router ospf <N>` / `router eigrp <N>` | EIGRP fixture | (Tier-3) |
| `fabric forwarding anycast-gateway-mac <mac>` | EVPN | 4 (needs T2) |
| `nv overlay evpn` | EVPN | 4 |
| `evpn / vni <N> l2 / rd auto / route-target import/export auto` | L2VNI | 4 |
| `snmp-server user <name> ... auth md5 0x<hex> priv 0x<hex> localizedkey` | every file | 2 |
| `copp profile strict` / `rmon event N ...` | every file | preserved raw |
| `hardware access-list tcam region ... <N>` | EVPN | preserved raw |
| `line console / line vty` | every file | preserved raw |
| `boot nxos bootflash:...` | every file | preserved raw |

**Per-interface sub-grammar** (indentation = 2 spaces; identical
shape to IOS-XE but different keyword surface):

```
interface Vlan10
  no shutdown
  ip address 10.10.10.1/24       ← CIDR form (not dotted mask!)
  vrf member TENANT-777          ← NX-OS form of `vrf forwarding`
  ip forward                     ← T3 anycast bare flag
  hsrp 10
    preempt
    ip 10.10.10.3
```

Key NX-OS-specific differences from IOS-XE noted at the grammar level:

* **`ip address X/N`** — slash-prefix form on the wire, NEVER dotted
  mask.  IOS-XE uses `ip address X Y` with dotted mask.
* **`vrf member <name>`** inside an interface (not `vrf forwarding`).
* **`vrf context <name>`** at top level (not `vrf definition`).
* **`hsrp N`** sub-stanza (not `standby N`).
* **`feature <name>`** required to unlock subsystems (bgp /
  interface-vlan / hsrp / nv overlay / fabric forwarding / lacp).
  Without the right `feature` line, NX-OS rejects the dependent
  config; the codec must emit `feature` declarations for every
  subsystem it renders.
* **`Ethernet1/1`** physical-port form (not `GigabitEthernet1/0/1`).
  No speed prefix — NX-OS uses uniform `Ethernet` regardless of
  10G / 40G / 100G.
* **`interface nve1`** is the VXLAN VTEP endpoint (not `interface nveN` —
  always nve1 on NX-OS).
* **`!Command: show running-config`** banner (no `Building
  configuration...` / `Current configuration:` blocks like IOS-XE).

See `01-grammar-survey.md` for the full per-stanza inventory + grammar
comparison table vs. IOS-XE.

---

## 3. Proposed codec module structure

```
netcanon/migration/codecs/cisco_nxos/
├── __init__.py              # re-export CiscoNXOSCodec
├── codec.py                 # CiscoNXOSCodec class — caps / probe /
│                            # iter_xpaths / port-name delegates
├── parse.py                 # parse_intent() + per-stanza helpers
├── render.py                # render_intent() + per-stanza emit helpers
└── port_names.py            # classify_port_name / format_port_identity
```

Mirrors the existing `cisco_iosxe_cli` layout (post-split).  Same
import surface; same one-line delegators from `codec.py` into the
sibling modules.  The choice of `cisco_nxos` for the module path
(under-scored, no `_cli` suffix) signals that NX-OS does not have a
sibling NETCONF codec to disambiguate from — same convention as
`arista_eos` and `juniper_junos`.

* `name: ClassVar[str] = "cisco_nxos"` — registry key.
* `vendor_id = "cisco_nxos"` — separate vendor identity from
  `cisco_iosxe`; warrants its own row in `definitions/vendors.yaml`.
* `input_format = "cli-nxos"` — new tag to add to `INPUT_FORMATS`
  in `base.py` (Phase 1 touchpoint).
* `version_hint = "9.x / 10.x"` — corpus is 9.2(3) + 10.3(9); future
  10.4 / 11.x are forward-compatible.
* `direction = "bidirectional"` — final Phase 4 state.
* `certainty = "experimental"` (Phase 1) → `"best_effort"` (Phase 2-3)
  → `"certified"` (Phase 4, once corpus clears the 3-fixture /
  2-OS-version bar from `tests/fixtures/real/RESULTS.md`).
* `canonical_model = "openconfig-lite"` — same baseline as every
  other bidirectional codec.

See `02-codec-architecture.md` for the per-method specs.

---

## 4. Implementation phases (landable PRs)

> **Anti-pattern explicitly avoided**: a single 3,000-LOC monster PR.
> Reviewers cannot land that.  Each phase below is a discrete PR with
> its own test suite + capability matrix + corpus fixtures.

### Phase 1 — scaffold + minimal parse / render (~400-500 LOC)

**Goal**: get the codec in the registry; clear the
``test_every_fixture_dir_has_codec_mapping`` test gate; round-trip
the trivial hostname-only case.

Surface:
* `hostname <name>` parse + render
* `!Command: show running-config` banner detection (probe)
* `version <N.N(N)> Bios:version` preserved as raw (cosmetic for
  Phase 1; informs `source_version` in `CanonicalIntent`)
* `vdc <name> id 1 / limit-resource ...` parsed and discarded
  (VDC is N7K virtualisation; safe to drop in v1 since the corpus
  shows it as a top-level wrapper around the rest of the config —
  the inner stanzas are unindented top-level lines, so the wrapper
  is purely informational)
* `username <name> password <hash-type> <hash> role <role>` →
  `CanonicalLocalUser`
* `vlan <N>` and `vlan <N>,<M>,...` and `vlan <N>-<M>` (comma + range
  list form unique to NX-OS) → `CanonicalVlan`
* `vrf context <name>` (top-level) → `CanonicalRoutingInstance`
  (description / rd / RT subset of IOS-XE's vrf definition shape)
* `interface Ethernet1/N`, `interface loopback<N>`, `interface mgmt0`,
  `interface Vlan<N>`, `interface port-channel<N>` —
  `CanonicalInterface` with `description`, `enabled`, `mtu`,
  `ip address X/N`, `ipv6 address X::Y/N`, `vrf member <name>`,
  `shutdown` / `no shutdown`.
* Probe: detects ``!Command: show running-config`` + at least one of
  ``feature <known-list>`` / ``vdc <name> id`` / ``ip address X/N``
  (CIDR form not dotted mask) — see `02-codec-architecture.md` § 7.
* `_DIR_TO_CODEC_NAME["nx_os"] = "cisco_nxos"` wired into
  `tests/unit/migration/test_real_captures.py` (line 80-88).
* `definitions/vendors.yaml` row added for `cisco_nxos`.
* Capability matrix: 12-15 supported paths (hostname, interface basics,
  VLAN id+name, static routes parse-only).

Tests: ~30 unit + 1 real-capture fixture (`nxos_static_route_D1.txt`).
LOC budget: ~400-500 codec + ~250 tests.

### Phase 2 — L2 surface (SVI, VLAN-port membership, LAG, HSRP) (~600-700 LOC)

**Goal**: full L2 grammar round-trips; cross-vendor SVI + LAG
translation in / out of NX-OS works.

Surface added on top of Phase 1:
* `switchport mode {access|trunk}`, `switchport access vlan N`,
  `switchport trunk allowed vlan <list>`, `switchport trunk native
  vlan N`
* `no switchport` (= routed port) flag — NX-OS Ethernet ports default
  to L2 switchport; routed config requires explicit `no switchport`.
  See `01-grammar-survey.md` § 4 for the contrast vs. IOS-XE.
* `channel-group N mode active|passive|on` (LAG member binding)
* `interface port-channelN` declaration + member
  list synthesised from `channel-group` lines (mirrors IOS-XE +
  Arista approach)
* `interface Vlan<N>` SVI synthesis — same fix as `_synthesize_vlans_from_svis`
  in iosxe_cli/parse.py
* `feature interface-vlan` / `feature lacp` declarations:
  parse-time discard, render-time auto-emit when the canonical
  tree implies them (any SVI present → emit `feature interface-vlan`;
  any LAG present → emit `feature lacp`).  Detail in
  `02-codec-architecture.md` § 5.
* **HSRP**: `interface Vlan10 / hsrp N / preempt / ip X / priority N`
  → `CanonicalHSRPGroup` (from T1 — gates this part of Phase 2 on
  T1 landing first).
* `feature hsrp` auto-emit on HSRP presence.
* `snmp-server user <name> ... auth md5 0x<hex> priv 0x<hex>
  localizedkey [engineID ...]` → `CanonicalSNMPv3User`.
* `snmp-server community <community>` (legacy v2c form when present).
* Capability matrix expansion: ~25 supported paths.

Tests: ~50 unit + 2 real-capture fixtures (`nxos_hsrp_nxos1.txt`,
`nxos_hsrp_nxos2.txt`).
LOC budget: ~600-700 codec + ~450 tests.

### Phase 3 — L3 (static routes, VRF interactions, BGP scaffolding) (~500-600 LOC)

**Goal**: VRF + static-route surfaces round-trip with `mgmt` VRF
correctly classified; BGP grammar parsed-and-preserved for the
informational raw-section banner.

Surface added on top of Phase 2:
* `ip route [vrf <name>] <dest>/<prefix> <gw>` (top-level form +
  the per-VRF form inside `vrf context <name> / ip route X/N Y`)
* `vrf context management` membership classification (`mgmt0` →
  `kind="mgmt"`; mirrors the `_is_mgmt_vrf` helper in iosxe_cli/parse.py)
* `vrf context <name> / address-family ipv4 unicast / route-target
  both auto evpn` → `CanonicalRoutingInstance.rt_imports/rt_exports`
  (Phase 3 wires the basic VRF surface; EVPN-specific RT augmentation
  comes back in Phase 4).
* `vrf context <name> / vni <N>` (the L3VNI binding) →
  `CanonicalRoutingInstance.l3_vni` — already a canonical field
  (intent.py line 524).
* `router bgp <asn>` block — parsed into `intent.raw_sections["router
  bgp"]` for the informational banner.  No render-side autogenerator;
  Tier-3 scope.  Tier-3 stanza headers added to
  `_tier3_detection.detect_tier3_sections_nxos`.
* `router ospf` / `router eigrp` — Tier-3 raw_sections.
* `feature bgp` / `feature ospf` etc. auto-emit on declared
  Tier-3 section presence (best-effort — the operator will likely
  hand-author the BGP after migration anyway, but the `feature`
  declaration must be present so the rest of the rendered config
  passes the NX-OS commit syntax check).
* Capability matrix expansion: ~35 supported paths, multiple
  lossy declarations for Tier-3 routing-protocol stanzas.

Tests: ~40 unit + 2 real-capture fixtures (`nxos_static_route_D1.txt`
upgraded from Phase 1, `nxos_ebgp_loop_d1.txt`).
LOC budget: ~500-600 codec + ~400 tests.

### Phase 4 — EVPN-VXLAN fabric (~900-1,000 LOC)

**Goal**: NX-OS DC fabric configs round-trip end-to-end; cross-vendor
EVPN translation (Arista ↔ NX-OS ↔ Junos) lit up.

Surface added on top of Phase 3:
* `nv overlay evpn` + `feature nv overlay` + `feature vn-segment-vlan-based`
  + `feature fabric forwarding` — auto-emit on VxLAN presence.
* `vlan <N> / vn-segment <vni>` → `CanonicalVxlan(vlan_id=N, vni=...)`
* `interface nve1` block parsing:
  * `source-interface loopback0` → `CanonicalVxlan.source_interface`
    (broadcast to all VNIs for the switch)
  * `host-reachability protocol bgp` → discard (Phase 4 assumes
    BGP-EVPN; no other protocol modelled)
  * `member vni <N>` (L2VNI) →
    associate with `CanonicalVxlan.vni`
  * `member vni <N> associate-vrf` (L3VNI) → cross-reference
    with the matching `CanonicalRoutingInstance.l3_vni`
  * `member vni <N> / suppress-arp / ingress-replication protocol bgp`
    → discard sub-flags (Phase 4 scope = head-end / mcast surface
    only)
* `evpn / vni <N> l2 / rd auto / route-target import|export auto`
  top-level block → augments matching `CanonicalVxlan` records
  (RT auto-derivation is a no-op since `rd auto` is implicit).
* `fabric forwarding anycast-gateway-mac <mac>` →
  `CanonicalAnycastGateway` (T2 surface; gates this part on T2
  landing first).
* Per-SVI `fabric forwarding mode anycast-gateway` flag → also T2.
* `router bgp <asn> / address-family l2vpn evpn / neighbor X / activate`
  + `send-community extended` → `CanonicalEvpnType5Route` parse
  for the L3VNI VRFs (already a Tier-2 schema in intent.py).
* Promotes `certainty` to `"best_effort"` (Phase 4 ships) →
  `"certified"` (once 3rd OS version added — see § 5).
* Capability matrix expansion: ~50 supported paths.

Tests: ~60 unit + 3 real-capture fixtures (`nxos_evpn_l3vni_NX1.txt`,
`nxos_evpn_l3vni_NX2.txt`, `nxos_evpn_l2vni_NX1.txt`) + cross-vendor
EVPN migration tests (Arista 7280 leaf → NX-1, NX-1 → Junos QFX).
LOC budget: ~900-1,000 codec + ~700 tests.

---

## 5. Total LOC + corpus estimate

| Phase | Codec LOC | Test LOC | Fixtures | Cert tier reached |
|---|---|---|---|---|
| 1 | 400-500 | 250 | 1 | experimental |
| 2 | 600-700 | 450 | +2 (3 total) | best_effort |
| 3 | 500-600 | 400 | +2 (5 total) | best_effort |
| 4 | 900-1000 | 700 | +3 (8 total) | best_effort → certified |
| **Total** | **2,400-3,200** | **1,800-2,400** | **8** | certified once 9.x + 10.x both covered + 1 community contribution |

**Certified-bar requirement** (per `tests/fixtures/real/RESULTS.md` §
"Certified tier"): ≥3 real captures across ≥2 OS versions.  The
batfish corpus alone covers 9.2(3) + 10.3(9); a third version (likely
a community-contributed 10.4 N9K capture) is the implicit blocker
for the final cert promotion.  See `05-fixture-targets.md` for the
post-batfish targets.

---

## 6. Canonical-model extensions required

The codec needs these schema additions to round-trip NX-OS grammar
**before** Phase 2 ships:

* **`CanonicalHSRPGroup`** — landed by **T1** (VRRP/HSRP canonical
  model).  NX-OS has its own `hsrp N` sub-stanza grammar that's
  semantically the same as Cisco IOS-XE's `standby N` + Aruba's
  `ip vrrp` (despite the name difference — HSRP vs. VRRP).  If T1
  models the surface as `CanonicalVRRPGroup` with a `protocol`
  discriminator (`"vrrp"` / `"hsrp"`), NX-OS slots in cleanly.

* **`CanonicalAnycastGateway`** — landed by **T2** (anycast-gateway
  canonical model).  NX-OS expresses anycast via the system-level
  `fabric forwarding anycast-gateway-mac <mac>` + per-SVI
  `fabric forwarding mode anycast-gateway`.  If T2 lands either as
  a sibling collection on `CanonicalIntent` or as a `mode="anycast"`
  field on T1's `CanonicalVRRPGroup`, NX-OS plugs in.

* **`feature` declarations** — possibly a new canonical primitive.
  Open question: do `feature` lines belong in the canonical tree at
  all, or are they an *implementation detail* of NX-OS render
  (derived from what the renderer is about to emit)?  My current
  recommendation: **derive on render, do not model canonically**.
  See `03-canonical-mapping.md` § 5 for the reasoning.

* **`vdc` raw block** — NX-OS-specific virtualisation primitive.
  Recommend preserving in `intent.raw_sections["vdc"]` for round-trip
  fidelity; not modelled canonically since no other vendor has
  the concept.

* **`copp profile` + `rmon event` + `hardware access-list tcam`
  raw blocks** — informational only, preserved in `raw_sections`.

No new Tier-1 / Tier-2 schema additions specific to NX-OS beyond
what T1 + T2 already plan to land.  This is intentional: the
canonical model's cross-vendor primitive set is already broad
enough to absorb NX-OS's L2 + L3 + EVPN surface.

---

## 7. Cross-vendor migration paths unlocked

Once the codec ships at `certainty="certified"`, the following
cross-vendor migrations become first-class:

* **Cisco IOS-XE → NX-OS** — DC modernisation: Catalyst-stack
  replacement by Nexus 9000 leaves.  High demand from enterprises
  doing VXLAN-EVPN refresh.
* **NX-OS → Junos QFX** — DC vendor swap: typical Juniper sales
  motion against incumbent Nexus.  EVPN-VXLAN translation is the
  long pole; L2/L3 are mechanical.
* **Arista EOS → NX-OS** (or reverse) — DC vendor swap between
  the two main EVPN-VXLAN incumbents.  Should be near-lossless
  once Phase 4 ships since both target the same EVPN spec.
* **Cisco IOS classic (pre-IOS-XE) → NX-OS** — campus → DC uplift
  where the campus core was a Cat6500/7600 and the DC is a Nexus
  fabric.  Gated on the IOS-classic codec which is not in v0.2.0
  scope but is a logical T5 candidate.

---

## 8. Open design questions

Listed in priority order — the implementor should resolve each
before writing the corresponding phase.

### Q1. Single codec or split (CLI / NX-API / NETCONF)?

NX-OS supports three management interfaces:
* CLI text (`show running-config`)
* NX-API REST (JSON-RPC)
* NETCONF (`<get-config>` over SSH)

This design proposes a **single CLI codec** in v1, mirroring how
`cisco_iosxe_cli` ships alongside but separate from `cisco_iosxe`
(the NETCONF codec).  Phase 4 ships with parse + render of the
CLI text only.  An NX-API JSON codec is a logical T7 follow-up.

**Recommendation**: ship CLI-only.  Defer NX-API.

### Q2. Where does `feature` autodetection live?

Render-side, in `render_intent()`.  The canonical tree carries no
`feature` declarations; the renderer walks the tree at the top of
`render_intent()` and emits the union of required `feature` lines:

| Canonical surface present | Required NX-OS feature |
|---|---|
| Any `CanonicalInterface` with `kind="svi"` | `feature interface-vlan` |
| Any `CanonicalLAG` | `feature lacp` |
| Any `CanonicalHSRPGroup` | `feature hsrp` |
| Any `CanonicalVxlan` | `feature nv overlay` + `feature vn-segment-vlan-based` + `nv overlay evpn` |
| Any `CanonicalAnycastGateway` | `feature fabric forwarding` |
| `intent.raw_sections["router bgp"]` populated | `feature bgp` |
| `intent.raw_sections["router ospf"]` populated | `feature ospf` |
| `intent.raw_sections["router eigrp"]` populated | `feature eigrp` |

The parse path can verify (and warn) if a required `feature` is
missing from the source config but the dependent stanza is present —
typically a sign the source capture was truncated or the operator
elided a section.

### Q3. How to handle the empty Ethernet1/<N> ports?

The seed corpus shows every NX-OS config emitting a bare
`interface Ethernet1/N` line (no body) for every unconfigured
physical port on the chassis.  Real captures will have **128 such
lines** for an N9K-C93180YC-FX.  Two options:

* **(A)** Parse them all into `CanonicalInterface` records.  Result:
  the rename modal lists 128 ports the operator has to scroll
  through, most of which are blank.  Most cross-vendor renders
  will skip them (no IP, no description, no switchport mode = no
  output).  Same shape Arista EOS emits for its baseline.
* **(B)** Filter at parse time — drop any interface that has no
  description, no IP, no switchport mode, no LAG membership, no
  shutdown override.

**Recommendation**: **(A)**.  Matches the Arista EOS approach and
preserves round-trip fidelity (the source config has these lines;
the rendered config should too).  Bonus: the rename modal showing
all 128 ports gives the operator a UX cue for "where am I in the
chassis".  The render path's "skip empty interfaces" filter (which
arista_eos already has) keeps the cross-vendor output clean.

### Q4. Probe collision risk with `cisco_iosxe_cli`

Both NX-OS and IOS-XE output start with `!` comments and contain
`hostname X` + `interface ...`.  The IOS-XE probe currently fires
at 95 on `Building configuration...` / `Current configuration:`
banners — neither of which NX-OS emits.

NX-OS instead emits `!Command: show running-config` as the very
first line.  That string is **unambiguously NX-OS** in the modern
era — IOS-XE has never used it.  Probe at 95 on that exact prefix
match plus a CIDR-form `ip address X/N` (NX-OS) vs. dotted-mask
`ip address X Y Y Y` (IOS-XE) as a secondary tiebreaker.

`02-codec-architecture.md` § 7 has the full probe ladder.

### Q5. Phase 4 dependency on T2 anycast-gateway

T2's canonical model is not finalised.  If T2 ships as a `mode=`
field on T1's `CanonicalVRRPGroup`, NX-OS Phase 4 maps anycast
through that.  If T2 ships as a sibling collection
(`CanonicalAnycastGateway`), Phase 4 wires through the sibling.
Either way Phase 4 must coordinate with the T2 implementor before
freezing the render path.

Open: should NX-OS Phase 4 ship at all if T2 hasn't landed?  My
recommendation: **yes, with anycast declared `unsupported`** in
the Phase 4 capability matrix.  L2VNI + L3VNI fabrics that don't
use anycast (rare but real) still benefit from the codec.
Anycast support arrives in a Phase 4.5 PR after T2 lands.

### Q6. `ip address X/N` vs. `ip address X Y` round-trip

Cross-vendor render to IOS-XE must convert NX-OS's CIDR form back
to dotted mask.  The existing IOS-XE renderer already has
`_prefix_to_mask` — reusable as-is.  NX-OS render of an IOS-XE
source must do the reverse (`_prefix_to_mask` → string concat into
`X/N`).  Trivial; no schema change needed.

### Q7. `vlan 1,10,2000` comma-list form

NX-OS allows `vlan 1,10,2000` and `vlan 10-20` syntax to declare
multiple VLAN IDs in one line — the only other codec that does
this is Arista EOS.  Easiest: expand at parse time into N separate
`CanonicalVlan` records, then re-coalesce on render via a small
helper.  The arista_eos codec already has this; the implementor
should crib that helper rather than reinventing it.

---

## 9. Maintainer review checklist

When reviewing this design before approving the implementation:

* [ ] Confirm `cisco_nxos` is the right vendor_id (vs. `nxos`
  bare).  Convention in `definitions/vendors.yaml` is
  `<manufacturer>_<os-family>`; `cisco_nxos` matches.
* [ ] Confirm Phase 4 dependency on T1 + T2 is acceptable.  If
  T1/T2 slip, Phase 4 ships without HSRP / anycast.
* [ ] Confirm the `feature`-on-render approach (Q2) over a
  canonical-model addition.  Alternative would surface `feature`
  declarations in `CanonicalIntent.nxos_features: list[str]` — a
  vendor-specific extension that breaks the cross-vendor
  invariant.  Render-derived is cleaner.
* [ ] Confirm 128-empty-Ethernet handling (Q3).  Decision propagates
  to render path + cross-vendor rename UX.
* [ ] Confirm CLI-only scope (Q1).  NX-API codec deferred to T7.

---

## 10. References + further reading

* `01-grammar-survey.md` — full per-stanza grammar inventory + IOS-XE
  delta table.
* `02-codec-architecture.md` — module layout, class shape, parse +
  render strategies, port-name handling, probe ladder.
* `03-canonical-mapping.md` — xpath → NX-OS command table + schema
  extension list.
* `04-test-plan.md` — unit + real-capture + cross-vendor test
  matrix, per-phase test counts.
* `05-fixture-targets.md` — batfish + community corpus targets,
  per-fixture grammar coverage.
* `06-capabilities-matrix.md` — proposed `CapabilityMatrix` row
  list with grammar-pointer justifications.

External:
* Cisco NX-OS 9.3 Configuration Guides — https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/93x/configuration.html
* batfish/lab-validation `snapshots/nxos_*` — Apache-2.0 corpus
* Cisco NX-OS Programmability Guide (NX-API + NETCONF reference)
