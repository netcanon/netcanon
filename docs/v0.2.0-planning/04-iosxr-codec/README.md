# T4 — Cisco IOS-XR bidirectional codec

> **Scope of this folder:** design-only artifacts for a planned new
> `cisco_iosxr` bidirectional codec.  No production source code is
> modified by these documents.  When the implementation lands it will
> cite this folder by relative path in commit messages and an
> `IMPLEMENTED.md` stub will point at the merge commit (per the
> v0.2.0-planning convention).

## Executive summary

Cisco IOS-XR is Cisco's service-provider routing NOS for the ASR 9000,
NCS 5500 / 540 / 560 / 5700 / 8000, and CRS series.  It powers the
core + edge of most North-American and European Tier-1 networks
(AT&T, Verizon, Comcast, CenturyLink/Lumen, Telefonica, DT) plus a
slice of hyperscaler PoP / DCI deployments.  IOS-XR is **not** an
IOS-XE flavour — its grammar diverges sharply in five places that
matter to the codec:

1. **Two-pass commit semantics** — config is staged in a *candidate*,
   then `commit` makes it active.  Wire form preserves the candidate
   shape; the codec emits `commit` only when round-tripping a session
   transcript.
2. **VRF is top-level** (`vrf <name>` / `address-family ipv4 unicast`
   / `import|export route-target`) — *not* IOS-XE's `vrf definition
   <name>` block.  RD lives under `router bgp` per-VRF, not in the
   VRF stanza itself.
3. **Route-policy replaces route-map** — the policy language is a
   structured if/elseif/then/endif DSL terminated by `end-policy`,
   not the line-by-line `route-map NAME permit 10 / match X / set Y`
   form.  Sibling primitives `prefix-set` and `community-set`
   replace `ip prefix-list` / `ip community-list`.
4. **Four-segment port names** — `GigabitEthernet0/0/0/0`
   (rack/slot/instance/port), not IOS-XE's 3-segment
   `GigabitEthernet0/0/0`.  LAGs are `Bundle-Ether<N>`, not
   `Port-channel<N>`.  Management port is `MgmtEth0/RP0/CPU0/0`.
5. **`ipv4 address X Y`** inside an `interface` stanza — not
   IOS-XE's `ip address X Y`.  IPv6 is `ipv6 address X/N`.  L2
   sub-stanzas (`encapsulation dot1q`) appear on `.subif` child
   interfaces rather than the parent.

The seed corpus from `batfish/lab-validation` (Apache-2.0) covers
the cross-section that matters for v1: 3 snapshots × 7 device
configs spanning eBGP, iBGP RR over OSPF, and XR↔XE VPNv4 interop.
The XR PE nodes in `cisco_xr_ios_vpnv4` exercise `vrf` /
`route-policy` / `mpls ldp` / `router bgp address-family vpnv4
unicast` simultaneously — the trio that makes XR XR.

This document set lays out a 4-phase implementation plan that
follows the same shape as the IOS-XE CLI codec evolution (start
with hostname + interfaces + static routes, layer on VRF, then
SP-routing protocols, then route-policy).  See
`01-grammar-survey.md` for the full inventory.

---

## Audience analysis — should this land before or after T3 (NX-OS)?

| Dimension | NX-OS (T3) | IOS-XR (T4) |
|---|---|---|
| **Install base size** | Massive — every DC running Nexus 3000 / 5000 / 7000 / 9000 (likely every Fortune-500 + most mid-market enterprises) | Concentrated — Tier-1 SPs, hyperscaler PoPs, some large MSP cores |
| **Enterprise reach** | High — DC switching is the bread + butter | Low — most operators don't see XR unless they buy SP transit |
| **Cross-vendor migration likelihood** | High — NX-OS ↔ Arista EOS is *the* dominant DC-fabric migration story today (Cisco→Arista, Cisco→Juniper QFX) | Moderate — XR ↔ Junos MX, XR → SONiC for hyperscaler use, but the audience knows the targets exist already |
| **Grammar overlap with existing codecs** | Moderate — shares `interface Vlan<N>` / `switchport` / VLAN-centric DNA with IOS-XE; new surfaces are HSRP/anycast (gated on T1+T2) and `vrf context` | Low — `route-policy` is a new DSL, `prefix-set`/`community-set` are new primitives, `Bundle-Ether` is a new LAG kind |
| **Open-source corpus availability** | Excellent — batfish has `nxos_hsrp` + `nxos_evpn_l2vni` + `nxos_evpn_l3vni` + more | Good — 3 batfish snapshots cover the core grammar; Cisco DevNet sandbox has live XR but capture licensing is unclear |
| **Risk of scope creep** | Higher (HSRP / VxLAN EVPN / fabric forwarding all distinct surfaces) | Lower (the core surface — interfaces + VRF + static — is well-bounded; SP routing slots in as later phase) |
| **Best LOC-per-impact ratio** | Better — more potential migrations land per LOC written | Worse — but enables a specific market we can't reach today |

**Recommendation: defer T4 until after T3 lands.**  NX-OS has wider
enterprise reach and the migration patterns it enables (Cisco-DC →
Arista / Cisco-DC → Juniper-QFX) are the dominant DC-fabric
modernisation story.  T4 (IOS-XR) is the **second** codec to land
once the canonical-model extensions for VRF (T1 already lays
groundwork) + route-policy (new this PR) settle.  However, the seed
corpus + grammar inventory + architectural decisions are
sufficiently distinct that **the design work can land in parallel
with T3 implementation** — there's no schema conflict between the
two.

---

## Proposed codec module structure

```
netcanon/migration/codecs/cisco_iosxr/
├── __init__.py        # CiscoIOSXRCodec re-export
├── codec.py           # CiscoIOSXRCodec class — metadata, capabilities,
│                      # probe, port-name delegates.  parse/render are
│                      # one-line delegators to siblings.
├── parse.py           # Line-scan + per-stanza dispatch + indentation-
│                      # aware `!`-terminated stanza walker.  Handles
│                      # the route-policy `if ... then ... endif` DSL
│                      # and prefix-set / community-set blocks.
├── render.py          # CanonicalIntent → IOS-XR running-config text.
│                      # Knows the XR-specific stanza ordering, the
│                      # 4-segment port naming, the `Bundle-Ether`
│                      # LAG form, and the per-VRF address-family
│                      # emission pattern.
└── port_names.py      # classify_port_name / format_port_identity
                       # — 4-segment XR ports + Bundle-Ether + Mgmt
                       # variants.
```

Same shape as `cisco_iosxe_cli/` and `juniper_junos/` — establishes
the post-split convention (see `netcanon/migration/codecs/README.md`).

`vendor_id` will be `"cisco_iosxr"` (NEW — distinct from
`"cisco_iosxe"`).  An accompanying YAML entry will live under
`definitions/vendors/cisco_iosxr.yaml`.

---

## Implementation phases — landable PRs

Sized to mirror the IOS-XE evolution (each phase ~one PR review
session).  Phase deliverables are independent: each lands a
production-shippable subset, with the next phase widening coverage.

### Phase 1 — Skeleton + Tier-1 surface (~700-900 LOC)
**Goal:** ship a `parse_only` codec that classifies as Cisco IOS-XR
and recovers enough state for *some* cross-vendor migration to be
meaningful.

- `codec.py` skeleton (probe — `!! IOS XR Configuration` banner +
  4-segment port name detector); `direction="parse_only"`;
  `certainty="experimental"`.
- `parse.py`: hostname, `domain name`, `username`, interfaces
  (physical + Loopback + Mgmt + Bundle-Ether), `ipv4 address`,
  `ipv6 address`, description, shutdown, MTU.  Static routes via
  `router static / address-family ipv4 unicast / X/N Y` (note the
  CIDR + next-hop form distinct from IOS-XE `ip route X Y Z`).
- `port_names.py`: 4-segment classification + Bundle-Ether kind=lag
  + MgmtEth kind=mgmt heuristic + Loopback kind=loopback.
- Tests: ~25-30 unit tests mirroring `test_cisco_iosxe_cli.py`'s
  `TestR3Fields` + `TestParseCLI` structure.
- Real-capture fixtures: drop the 7 batfish snapshot configs into
  `tests/fixtures/real/cisco_iosxr/`; add `"cisco_iosxr":
  "cisco_iosxr"` row to `_DIR_TO_CODEC_NAME` in
  `test_real_captures.py:80`.

### Phase 2 — VRF + render path (bidirectional, ~600-800 LOC)
**Goal:** flip direction to `bidirectional`; certainty stays
`experimental`.  Enables IOS-XR as a migration *target*.

- `parse.py`: top-level `vrf <name>` stanzas + per-VRF
  `address-family ipv4 unicast` + `import route-target` /
  `export route-target` list parsing.  Per-interface `vrf <name>`
  binding (note: not `vrf forwarding` like IOS-XE — just `vrf
  <name>`).  Management VRF promotion to `kind="mgmt"` reusing
  the IOS-XE heuristic.
- `render.py`: full canonical → XR emission for everything Phase 1
  parses, plus VRF stanzas.  Bundle-Ether ↔ Port-channel renaming
  cascade via the port-name bridge (already handled by the
  cross-vendor orchestrator once `format_port_identity` is wired).
- Tests: ~30-40 more unit tests + round-trip tests on the 7 batfish
  fixtures.
- Capability matrix declarations covering everything supported +
  the new `route-policy` / `prefix-set` / `community-set` as
  `unsupported` Tier-3 (intentional non-translation; see
  `06-capabilities-matrix.md`).

### Phase 3 — SP-routing parse-and-display (~400-600 LOC)
**Goal:** make XR fixtures stop dropping the SP-routing stanza
content on the floor; surface it via `dropped_tier3_sections`.

- `_tier3_detection.detect_tier3_sections_iosxr()` recognising the
  XR-specific Tier-3 stanza headers: `router bgp`, `router ospf`,
  `router isis`, `mpls ldp`, `mpls te`, `route-policy`,
  `prefix-set`, `community-set`, `as-path-set`, `extcommunity-set`.
- `router bgp <asn>` stanza parse harvesting `bgp router-id`,
  `neighbor <ip>` + `remote-as` + `update-source` into Tier-2 BGP
  records — IF a `CanonicalBgpNeighbor` lands by then (otherwise
  parse-and-ignore + Tier-3 notification only).
- `mpls ldp` parse harvesting member-interface list (parse-only,
  Tier-3 notification).
- Tests: confirm Tier-3 banner surfaces for every batfish fixture.

### Phase 4 — Certified bar + 1-2 follow-on fixtures (~200-400 LOC, mostly tests)
**Goal:** flip `certainty` to `certified`; round-trip stability proven
against ≥3 real captures.

- Source 1-2 additional fixtures beyond the batfish corpus (Cisco
  DevNet sandbox snapshots, Cisco public docs, NTC-Templates'
  `tests/cisco_xr/` collection if licence permits).  Goal: 5+ XR
  fixtures total.
- Polish: dedup helper extraction, lint fixes, docstring round-up.
- CHANGELOG + CAPABILITIES.md / COMPARISON.md row additions.

### Total estimated LOC across all 4 phases
- **Production source:** ~1,900-2,700 LOC
  - Phase 1: ~700-900
  - Phase 2: ~600-800
  - Phase 3: ~400-600
  - Phase 4: ~200-400 (mostly fixture wiring + polish)
- **Test code:** ~1,200-1,700 LOC (≈60-70% of production LOC, same
  ratio as `test_cisco_iosxe_cli.py` against the IOS-XE CLI codec)
- **Grand total:** ~3,100-4,400 LOC

This places IOS-XR around the same total scope as Junos (3,400 LOC
production + tests today) — fair, given the comparable grammar
surface depth.

---

## Open design questions for the implementor

1. **`commit` emission on render — yes or no?**  XR's wire format
   from `show running-config` doesn't include `commit`, but a session
   transcript would.  Recommend: render emits no `commit` (matches
   `show running-config` shape; operators apply via their own tool
   chain).  Confirm before Phase 2 lands.
2. **Route-policy: parse-and-ignore Tier-3, or model as opaque
   string field?**  Junos has `policy-options` declared
   `unsupported` (see `juniper_junos/codec.py:202-211`).  XR
   `route-policy` is more constrained (no nested policies) but
   semantically similar.  Recommend: same treatment — Tier-3 banner
   only, no canonical model surface.  See
   `03-canonical-mapping.md` for rationale.
3. **`Bundle-Ether<N>` vs `Port-channel<N>` cross-vendor mesh.**  XR
   uses `Bundle-Ether<N>`.  When an IOS-XE source migrates to XR,
   the rename mesh needs to convert `Port-channel5` →
   `Bundle-Ether5`.  Confirmed achievable via `kind="lag"` +
   `index=5` in the existing `PortIdentity` shape — no schema
   change required.  Same for `MgmtEth0/RP0/CPU0/0` ↔ Cisco IOS-XE
   `GigabitEthernet0/0` carrying `vrf forwarding Mgmt-vrf` (cascade
   via existing `kind="mgmt"` mechanism).
4. **VRF RD placement: under `vrf` stanza, or under `router bgp /
   vrf <name>`?**  In XR, RD is conventionally declared under
   `router bgp <asn> / vrf <name> / rd <rd>` — *not* the top-level
   `vrf` stanza (which is IOS-XE's convention).  Parser must read
   from the BGP block; render must emit there.  This is the biggest
   structural divergence from IOS-XE's VRF handling — and the
   biggest single risk if `router bgp` parsing is deferred to
   Phase 3.  **Recommend Phase 2 lands a minimal BGP-VRF stub** —
   `router bgp <asn> / vrf <name> / rd <rd>` only — to keep VRF
   metadata round-tripping cleanly.  Without it,
   `CanonicalRoutingInstance.route_distinguisher` drops on every
   XR round-trip.
5. **`encapsulation dot1q <vlan>` on `.subif` interfaces — model as
   tagged subinterface, or fold into `CanonicalInterface.access_vlan`?**
   XR uses `interface GigabitEthernet0/0/0/1.35 / encapsulation
   dot1q 35` — same physical port carries multiple VLAN-tagged
   sub-interfaces, each with its own L3 config.  Junos has similar
   semantics (`unit 35 vlan-id 35`).  Recommend: same treatment as
   Junos GAP 4 — materialise as a distinct `CanonicalInterface`
   named `<parent>.35` with `name_speed_hint` inherited from parent.
   See `03-canonical-mapping.md`.
6. **What's the right boundary for "this is Cisco-XR, not Cisco-XE"
   in the auto-detection probe?**  `!! IOS XR Configuration` is
   nearly unambiguous (Cisco-XR-specific banner; no other vendor
   emits this).  Backup is the 4-segment port-name pattern
   `interface GigabitEthernet\d+/\d+/\d+/\d+\b`.  See
   `02-codec-architecture.md` for the proposed probe scoring.

---

## Artifacts in this folder

| File | Purpose |
|---|---|
| [`README.md`](README.md) | (this file) executive summary |
| [`01-grammar-survey.md`](01-grammar-survey.md) | Full grammar inventory with corpus citations |
| [`02-codec-architecture.md`](02-codec-architecture.md) | Module layout + class shape + parse/render strategy |
| [`03-canonical-mapping.md`](03-canonical-mapping.md) | Canonical fields ↔ IOS-XR grammar table |
| [`04-test-plan.md`](04-test-plan.md) | Test surfaces, fixture wiring, cross-vendor cases |
| [`05-fixture-targets.md`](05-fixture-targets.md) | Source URLs + licenses + sanitization for the corpus |
| [`06-capabilities-matrix.md`](06-capabilities-matrix.md) | Proposed initial `CapabilityMatrix` |

---

## Dependencies on T1 (VRRP) + T2 (anycast)

| Dependency | Impact on T4 |
|---|---|
| **T1 — `CanonicalVRRPGroup`** | IOS-XR has its own VRRP grammar: `router vrrp` top-level stanza (not per-interface like IOS-XE).  Phase 1 of T4 parses-and-ignores; later phases consume `CanonicalVRRPGroup` once T1 lands |
| **T2 — anycast-gateway** | IOS-XR uses `router vrrp` with `track interface` for anycast-ish flows, plus `fabric forwarding` for SD-Access (very narrow use case in SP).  T4 declares both as `unsupported` until T2 lands; even then, IOS-XR anycast coverage is low priority |

T1 and T2 are formal prerequisites for T4 in the v0.2.0 implementation
order (per the top-level `v0.2.0-planning/README.md` dependency graph)
but the codec skeleton + 7 batfish-fixture coverage can land BEFORE
T1+T2 do; the impacted surfaces just stay in the `unsupported` list
on the capability matrix until then.
