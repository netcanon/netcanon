# v0.2.0 / v0.3.0 planning artifacts

This directory holds **research and design artifacts** produced by an
agent-driven planning pass against the four high-leverage enrichment
opportunities surfaced during fixture research on commits
`f52489c..8adaefd` (Junos channelized fix + 2 batfish samples + VRRP
enrichment plan).

> **Read-only research.** Everything in this directory is design
> documentation. No production source code was modified by the agents
> that authored these files. When the implementations land, they will
> cite the design docs by relative path in their commit messages, and
> the corresponding subfolder will get an `IMPLEMENTED.md` stub
> pointing at the merge commit.

---

## Subfolder index

Each task got its own subfolder with a structured set of design
documents (~28 markdown files total, ~13,700 lines of design):

| # | Subfolder | Topic | Tier | Status |
|---|---|---|---|---|
| 1 | [`01-vrrp-canonical/`](01-vrrp-canonical/) | `CanonicalVRRPGroup` model + wire to all 7 bidi codecs | v0.2.0 | Design complete |
| 2 | [`02-anycast-gateway/`](02-anycast-gateway/) | `virtual_gateway_address` field / anycast surface | v0.2.0 | Design complete |
| 3 | [`03-nxos-codec/`](03-nxos-codec/) | Full new NX-OS bidirectional codec | v0.3.0 | Design complete |
| 4 | [`04-iosxr-codec/`](04-iosxr-codec/) | Full new IOS-XR bidirectional codec | v0.3.0+ | Design complete (defer until after T3) |

Per-task artifact set (numbered files inside each subfolder):

* `README.md` — task overview, execution plan, dependency notes
* `01-canonical-model.md` or `01-grammar-survey.md` — schema / grammar analysis
* `02-per-vendor-grammar.md` or `02-codec-architecture.md` — per-vendor breakdown / proposed module layout
* `03-parse-render-touchpoints.md` or `03-canonical-mapping.md` — concrete file:line insertion points / canonical-field mapping
* `04-test-plan.md` — unit + integration + real-capture tests
* `05-capabilities-matrix-updates.md` — proposed `CapabilityMatrix` / `docs/CAPABILITIES.md` rows
* `06-fixture-targets.md` — specific source URLs to ingest

---

## Cross-task synthesis

### The headline conflict: T1 vs T2 on canonical surface shape

T1 and T2 reached opposite recommendations on the same architectural
question: **should anycast-gateway share a canonical record with
classic VRRP, or be a sibling field on the address?**

| Question | T1 recommendation | T2 recommendation |
|---|---|---|
| Anycast canonical surface | Merge into `CanonicalVRRPGroup` with `mode="anycast"` discriminator | Independent `virtual_gateway_address` + `virtual_gateway_mac` on `CanonicalIPv4/6Address` |
| Rationale | Shared field shape (`virtual_ips`, `virtual_mac`); single migrate-page row; one codec dispatch per vendor | Anycast is a property of an IP, not a router group; merging forces fake `group_id` / `priority` / `preempt` field synthesis; Junos one-line source naturally produces address+gateway on same record |

Both arguments are substantive. Re-reading both designs side-by-side,
**T2's argument is stronger** for these reasons:

1. **Domain modelling integrity.** Classic FHRP (VRRP/HSRP/CARP) **is**
   a group of routers with election semantics. Anycast **is** an IP
   property (every leaf has it; no election). The two have
   fundamentally different domain shapes — modelling them as one
   discriminated record forces every codec to write `if mode ==
   "anycast"` branches throughout parse + render, which the
   ship-before-wire matrix doesn't let us hide.

2. **Junos one-line source preservation.**
   `set interfaces irb unit 10 family inet address 10.221.0.5/16
   virtual-gateway-address 10.221.0.1` is ONE Junos line, ONE parse
   dispatch, ONE conceptual operation. T1's merged model forces
   splitting this into two CanonicalInterface attachments (address
   record + VRRP group). T2's independent surface stores both fields
   on the same `CanonicalIPv4Address` record — preserving the
   source's structure.

3. **EOS VARP has no group concept.** `ip address virtual 10.1.10.1/24`
   has no `group_id`. Synthesising one for the merged model is fake
   metadata that has no source token and no target render. The
   independent surface lets EOS parse directly into the address
   record.

4. **Precedent.** The canonical model already distinguishes
   `CanonicalVxlan` from `CanonicalEvpnType5Route` even though both
   are EVPN-overlay primitives — the maintainers chose distinct
   shapes over one discriminated record. Same pattern applies here.

### Recommended resolution: **HYBRID**

Adopt **both** canonical surfaces, scoped to their natural domains:

* **T1's `CanonicalVRRPGroup`** for classic FHRP — VRRP / HSRP / CARP.
  Drop the `mode="anycast"` value from the discriminator; keep
  `mode="vrrp"` / `mode="hsrp"` / `mode="carp"` only. Attach to
  `CanonicalInterface.vrrp_groups: list[CanonicalVRRPGroup]`.
  ~80 LOC schema + per-codec wiring (T1's documents are still
  ~95% correct with this scoping).

* **T2's independent address-fields** for anycast — Junos
  `virtual-gateway-address` / EOS VARP / NX-OS DAG / IOS-XE
  SD-Access. Lives as new fields on `CanonicalIPv4Address` +
  `CanonicalIPv6Address`, plus a system-wide
  `CanonicalIntent.anycast_gateway_mac` for vendors that have
  a chassis-level MAC declaration. ~15 LOC schema.

The two surfaces co-exist on the same `CanonicalInterface` — an
operator can configure both classic VRRP AND anycast on the same
SVI (legitimate dual-stack EVPN-VXLAN + legacy-segment pattern).
The hybrid resolution explicitly accommodates this.

### Schema-extension cascade across all 4 tasks

The 4 design passes surfaced additional canonical-model extensions
needed beyond the T1+T2 cores:

| Extension | Surface by | Also needed for | Action |
|---|---|---|---|
| `CanonicalVRRPGroup` (new type, `mode in {vrrp,hsrp,carp}`) | T1 | T3 NX-OS (HSRP) | Land in Wave A |
| `CanonicalInterface.vrrp_groups: list[...]` | T1 | T3 | Land in Wave A |
| `CanonicalIPv4Address.virtual_gateway_address: str` + `.virtual_gateway_mac: str` | T2 | T3 NX-OS DAG phase 4 | Land in Wave A |
| `CanonicalIPv6Address.virtual_gateway_address: str` + `.virtual_gateway_mac: str` | T2 | T3 NX-OS DAG phase 4 | Land in Wave A |
| `CanonicalIntent.anycast_gateway_mac: str` | T2 | T3 NX-OS DAG phase 4 | Land in Wave A |
| `CanonicalStaticRoute.vrf: str` | T3 (NX-OS) | **Also closes existing IOS-XE Lossy declaration** (per-VRF static-route discriminator) | Bundle with NX-OS Wave A or pull earlier |
| `PortIdentity.kind = "vtep"` (new value) | T3 (NX-OS) | T4 IOS-XR if it adopts a VTEP model | T3-internal; doesn't block other tasks |
| Optional `CanonicalVxlan.rt_imports / rt_exports: list[str]` | T3 (NX-OS phase 4) | None today | Defer until NX-OS phase 4 lands |

The `CanonicalStaticRoute.vrf` addition is a **bonus value catch** —
T3's research found that per-VRF static routes are currently lossy
on IOS-XE (declared in `cisco_iosxe_cli/codec.py` matrix). Adding
this field as part of the T3 schema work also flips that lossy
declaration to supported, with minor IOS-XE codec touchpoints.

### Implementation wave plan

Five waves, designed for landable per-PR scope and parallel-safe
execution where possible:

```
Wave A — Schema landing (single PR)
├── CanonicalVRRPGroup + Interface.vrrp_groups       [from T1]
├── virtual_gateway_address / _mac on Ipv4 + Ipv6    [from T2]
├── CanonicalIntent.anycast_gateway_mac              [from T2]
├── CanonicalStaticRoute.vrf                         [from T3]
├── Tier-1 ship-before-wire: every codec matrix    
│   declares the new paths as unsupported pending     
│   per-codec wire-up
└── Tests: schema validation (~10), defaults

Wave B — VRRP wire-up across 7 codecs (7 small PRs, parallel)
├── cisco_iosxe_cli parse + render + flip matrix to supported
├── juniper_junos                            (anycast = Wave C)
├── arista_eos                                (anycast = Wave C)
├── aruba_aoss
├── fortigate_cli
├── mikrotik_routeros
└── opnsense (mode=carp)

Wave C — Anycast wire-up across 3 codecs (3 small PRs, parallel)
├── juniper_junos (virtual-gateway-address; virtual-gateway-v4-mac)
├── arista_eos (VARP; system-wide ip virtual-router mac-address)
└── cisco_iosxe_cli (SD-Access fabric forwarding mode anycast-gateway)
                                                   (best_effort)

Wave D — NX-OS codec (4 phased PRs)
├── Phase 1: scaffold (~400-500 LOC)
├── Phase 2: L2 + HSRP (~600-700 LOC; consumes Wave A VRRP)
├── Phase 3: VRF + per-VRF routes (~500-600 LOC; consumes Wave A vrf)
└── Phase 4: EVPN-VXLAN + DAG (~900-1,000 LOC; consumes Wave A anycast)

Wave E — IOS-XR codec (4 phased PRs, defer until D is in flight)
├── Phase 1: skeleton + Tier-1 surface (~700-900 LOC)
├── Phase 2: VRF + render (~600-800 LOC)
├── Phase 3: Tier-3 detection + BGP RD harvest (~400-600 LOC)
└── Phase 4: polish → certified (~200-400 LOC)
```

**Parallelisation:**

* **Wave A is single-PR by design** — schema additions need atomic
  matrix declarations to keep CI green.
* **Wave B's 7 PRs** are independent (one per codec) and can land
  in any order.
* **Wave C's 3 PRs** depend only on Wave A.
* **Wave D phases land sequentially** but each phase is
  independently mergeable + tested. Phase 4 gates on Wave C
  landing first (so anycast support lights up).
* **Wave E should NOT start until Wave D Phase 2 ships** — too
  much codec-architecture churn for both to land in flight at the
  same time per a single maintainer's review budget.

### Aggregate budget

| Wave | Production LOC | Test LOC | Tests | Fixtures added |
|---|---|---|---|---|
| A — Schema | ~95 | ~50 | ~10 | 0 |
| B — VRRP × 7 codecs | ~810 | ~250 | ~80 | 5+ (per `06-fixture-targets.md` per codec) |
| C — Anycast × 3 codecs | ~280 | ~150 | ~50 | 2-3 (Junos/EOS already covered; IOS-XE SD-Access fixture is a P1 gap) |
| D — NX-OS codec | ~2,400-3,200 | ~1,800-2,400 | 250+ | 8 (batfish seed) |
| E — IOS-XR codec | ~1,900-2,700 | ~1,200-1,700 | 120+ | 7 (batfish seed) |
| **Total** | **~5,485-7,085** | **~3,450-4,550** | **~510+** | **22-23** |

Worth noting that v0.2.0 ships Wave A + B + C (~1,185 LOC + ~450
test LOC). v0.3.0+ ships Waves D and E (the new codecs).

### Open questions requiring human arbitration

These survived the planning pass and need explicit decisions before
implementation:

**Architectural** (must decide before Wave A):

1. **Adopt the HYBRID resolution?** (this synthesis recommends yes
   per § "Recommended resolution" above)
2. **Should `CanonicalVRRPGroup.mode` keep `"carp"` value or split
   to a sibling `CanonicalCARPInterface` type?** OPNsense BSD CARP
   is wire-protocol-distinct from IETF VRRP; cross-vendor migration
   semantics differ. T1 § 1-canonical-model.md "Decision points"
   leans toward keeping `mode="carp"` with lossy cross-vendor
   declaration.
3. **`virtual_mac` per-group OR top-level on `CanonicalIntent`?**
   T1 sketch places it per-group; Arista's `ip virtual-router
   mac-address` is top-level. Current draft cascades the global
   into every record on parse, hoists back on render. Verify with
   maintainer.
4. **EOS `secondary` trailer on `ip address virtual` lines.** T2
   recommends adding `is_secondary: bool = False` to the address
   records as part of T2; this would also benefit non-anycast
   primary/secondary handling on EOS. Bundle with T2 or split into
   sibling work?

**Per-task scope** (decide per task at PR-author time):

5. T1: which 5 codecs without VRRP fixtures pull in Wave B vs
   defer — `06-fixture-targets.md` lists URLs but some require
   sanitisation.
6. T2: Cisco IOS-XE SD-Access fabric-forwarding fixture — P1 gap,
   not available in public corpora today. Solutions evaluated in
   `02-anycast-gateway/06-fixture-targets.md`.
7. T3: NX-OS phase 4 (EVPN-VXLAN) — ship with anycast `unsupported`
   if T2 / Wave C slips, or block phase 4 on Wave C?
   `03-nxos-codec/README.md` § Q5 recommends ship-with-unsupported.
8. T4: IOS-XR `commit` emission on render — T4
   `02-codec-architecture.md` recommends NO `commit`, match
   `show running-config` shape.
9. T4: Route-policy treatment — T4 recommends Tier-3
   parse-and-notify (parity with Junos `policy-options`). Cross-
   check with the existing Junos pattern before committing.

**Audience / sequencing**:

10. **Should T4 IOS-XR slip beyond v0.3.0?** T4 README explicitly
    recommends deferring until T3 lands (enterprise reach > SP
    audience). Confirm with maintainer's strategic priorities.

---

## Dependency graph

```
                     ┌────────────────┐
                     │ Wave A: Schema │
                     └────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
       ┌───────────┐ ┌─────────────┐ ┌────────────────┐
       │ Wave B:   │ │ Wave C:     │ │  CanonicalSta- │
       │ VRRP × 7  │ │ Anycast × 3 │ │  ticRoute.vrf  │
       └───────────┘ └─────────────┘ │  (also lights  │
                            │         │   IOS-XE      │
                            │         │   per-VRF     │
                            │         │   routes)     │
                            ▼         └────────────────┘
                  ┌──────────────────┐
                  │ Wave D: NX-OS    │  (Phase 4 gates on Wave C)
                  └──────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │ Wave E: IOS-XR   │  (defer until Wave D Phase 2)
                  └──────────────────┘
```

---

## How to consume these artifacts

* **Project maintainer reviewing the v0.2.0 backlog**: read this
  README first, then each task's `README.md`. Then read the open
  questions list above and decide on the architectural
  arbitrations (#1-#4).
* **Implementor picking up Wave A**: read
  `01-vrrp-canonical/01-canonical-model.md` +
  `02-anycast-gateway/01-canonical-model.md` for the hybrid schema
  shape this synthesis recommends. Cross-reference
  `03-nxos-codec/03-canonical-mapping.md` for the
  `CanonicalStaticRoute.vrf` addition.
* **Implementor picking up Wave B / C**: per-task
  `03-parse-render-touchpoints.md` has exact file:line citations
  + code shapes.
* **Implementor picking up Wave D / E**: start with the task
  `README.md` for phasing, then `02-codec-architecture.md` for
  module layout.
* **Contributor wondering whether to start on T4 vs T3**: read
  `04-iosxr-codec/README.md` § "Audience analysis" — agent
  explicitly recommends T3 first.

---

## Provenance

The four design subfolders were authored by four parallel `general-
purpose` agents on 2026-05-19, each given the same hard constraint
(write only into their assigned subfolder, never modify production
code). Total agent runtime ~21 minutes wall-clock (parallel) /
~84 minutes CPU-time. Artifacts total ~13,700 lines markdown
across 28 files. No production code was modified by the agents.
