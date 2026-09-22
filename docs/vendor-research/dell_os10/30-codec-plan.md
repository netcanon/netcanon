# Dell OS10 — codec plan, risks, and the wiring checklist

Written 2026-09-21 from the research in this directory.  **No code has
been written.**  This is the analysis a `dell_os10` codec would start from.

---

## 1. ⚠️ HEADLINE: netcanon today mis-detects every Dell config as Cisco IOS-XE

This is **measured, not predicted**.  `detect_codec()` was run over every
real Dell capture held.  Over the **14 OS10** ones (the 4 OS9/FTOS captures
are counted separately below):

| Result | Count |
|---|---|
| `cisco_iosxe_cli` @ **confidence 95** | 6 |
| `cisco_iosxe_cli` @ confidence 45 | 6 |
| no candidate (`[]`) | 2 |
| **correct** | **0** |

All 4 OS9/FTOS captures also score 95 (via `service timestamps`, which
FTOS genuinely emits) — out of scope for an OS10-only fix.

95 is the high-confidence band.  A Dell OS10 config handed to netcanon
right now is not merely unsupported — it is **confidently claimed by the
IOS-XE codec and parsed as Cisco**, producing silent garbage.  That is the
#460 fail-open shape: the dangerous outcome is not "no codec", it is "the
wrong codec, sure of itself".

### Root cause, exactly

`netcanon/migration/codecs/cisco_iosxe_cli/codec.py`:

```python
_IOS_BANNER_HITS: tuple[tuple[str, int], ...] = (
    ("building configuration", 2),
    ("current configuration :", 2),
    ("! last configuration change at", 2),
    ("service timestamps", 2),
)
...
if cisco_banner_hits >= 2:
    return (95, "IOS-specific banner sequence detected")
```

Each entry carries weight 2 and the threshold is `>= 2`, so **a single
matching line scores 95**.  Dell OS10's `show running-configuration`
second line is:

```
! Last configuration change at Feb  25 15:06:23 2020
```

byte-identical in form to Cisco's.  The comment above `_IOS_BANNER_HITS`
asserts `! Last configuration change at` is Cisco-specific because "Aruba
uses `;` for comments, not `!`" — true of Aruba, **not true of Dell**.

(The OS9 captures hit the same 95 via `service timestamps`, which FTOS
also emits.)

### The fix follows an established pattern

`cisco_iosxe_cli.probe()` already contains deferral blocks for IOS-XR,
Aruba AOS-S, NX-OS and AOS-CX — each added after exactly this kind of
mis-detection (#234, #237).  A Dell block belongs alongside them, keyed on
markers that are OS10-exclusive **and** land inside the 500-byte probe
window (`probe_bytes: int = 500`):

| Candidate marker | Exclusive? | In 500B window? |
|---|---|---|
| `^interface breakout \d+/\d+/\d+ map` | yes — OS10 only | 2 of 4 config classes |
| `^ip vrf default` | strong (NX-OS uses `vrf context`) | 2 of 4 |
| `^system-user linuxadmin` | yes — OS10's Linux account | 1 of 4 |
| `^vlt-domain \d+` | yes (Cisco `vpc domain`, Aruba `vsx`) | deeper |
| `^vrrp (version \d\|delay reload)` at col 0 | yes — global VRRP is OS10 | 1 of 4 |

> ⚠️ **Honest limitation:** the `DellGEOS` hand-authored captures open with
> ~500 bytes of pure QoS (`class-map type queuing`, `trust dot1p-map`,
> `qos-map traffic-class`) and contain **no OS10-exclusive marker in the
> probe window at all**.  A 500-byte probe cannot detect every real OS10
> config.  Either accept that tail as undetected, or raise `probe_bytes`
> — which is a global change affecting all 12 existing codecs and must
> not be done casually.

### ✅ FIXED — PR #475 (2026-09-21)

This defect was independent of whether the codec is built, so it shipped on
its own. `cisco_iosxe_cli.probe()` now defers on the OS10-exclusive markers
tabled above, and Dell configs fail honestly instead of parsing as Cisco.

Measured after the fix, over the same 14 OS10 captures:

| | @95 | @45 | no candidate | correct |
|---|---|---|---|---|
| before | 6 | 6 | 2 | **0** |
| **after** | **0** | 4 | **10** | **10** |

The 95-confidence band is eliminated (6 → 0) and all six genuine device
dumps now return no candidate.  **The 4 residual @45 matches are the
DellGEOS QoS-window captures predicted above** — their first 500 bytes carry
no OS10 marker, which is inherent to `probe_bytes=500` and is the open
question in §9.1, not a defect in the fix.

OS9/FTOS is deliberately unaffected (it matches via `service timestamps`,
which FTOS genuinely emits) — see [`40-os9-appendix.md`](40-os9-appendix.md).

---

## 2. Canonical-surface fit

OS10 is a **good** fit — closer to the canonical model than several
shipped codecs.

| Canonical surface | OS10 | Verdict |
|---|---|---|
| `hostname` | `hostname X` | Tier 1 |
| Interfaces (name/desc/mtu/enabled) | direct | Tier 1 |
| IPv4/IPv6 addresses | CIDR, like NX-OS/Arista | Tier 1 |
| L2 switchport (access/trunk/native) | port-centric, Cisco-shaped | Tier 1 |
| VLANs | `interface vlanN` + port projection | Tier 1 (⚠ case, §3) |
| LAG | `port-channel` + `channel-group … mode active` | Tier 1 |
| VRF | `ip vrf <n>` / `ip vrf forwarding` | Tier 1/2 |
| Static routes | `ip route` CIDR **and** dotted-mask; `ip route vrf` | Tier 1 |
| VRRP | real VRRP, `vrrp-group` + `virtual-address` | **Tier 1 — no HSRP normalisation needed** |
| Local users | `username … role … priv-lvl` + `$6$` | Tier 2 |
| SNMP v2c/v3 | full family | Tier 2 (⚠ USM, §4) |
| DNS/NTP/syslog/domain | direct | Tier 2 |
| VXLAN/EVPN | `virtual-network` indirection | later phase |
| VLT (MLAG) | `vlt-domain` | **Tier 3 — no canonical surface** |
| QoS/DCB, ACL, BGP/OSPF, FC/FCoE | — | Tier 3 |

Two OS10-specific traps:

- **`management route 0.0.0.0/0 <gw>` is not `ip route`.** Seen in 8
  captures. Parsing it as a normal static route puts a management-only
  default into the global RIB.
- **`switchport access vlan` on a trunk port means the native VLAN.**
  Mapping it to `access_vlan` there is a semantic inversion of the kind
  #239 fixed for Junos.

---

## 3. Interface keyword case is not stable (measured)

`interface vlanN` ×137 (device dumps) vs `interface Vlan N` ×50
(hand-authored) vs `interface vlan N` ×24.  Parse must accept
`interface\s+[Vv]lan\s*(\d+)`; render should emit the device-normalised
`interface vlanN`.  Full measurement in [`10-grammar.md`](10-grammar.md) §2.

---

## 4. SNMPv3 USM — non-negotiable requirements

OS10 carries a **per-line `localized` marker** (manual L9085), and Dell
states localised keys are engine-ID-salted and cannot be copied between
switches (L8942).  This is the NX-OS `localizedkey` pattern that #471 was
built for.  A `dell_os10` codec must:

1. **Parse** — stamp `auth_kind` / `priv_kind` per line: `localized`
   present → `LOCALISED`, absent → `PLAINTEXT`.  Kind comes from the
   source grammar, **never** the value's shape (#460).
2. **Render** — re-emit `localized` when the recorded kind is not
   plaintext.  Recovering a key without re-marking it makes the device
   derive a key from a key: the #471 same-vendor corruption, which #472
   then found in three further grammars.
3. **Declare** `"dell_os10": PLAINTEXT` in `_SOURCE_DEFAULT_KIND`
   ([`_usm_keys.py`](../../../netcanon/migration/_usm_keys.py)) — the
   default for an *unmarked* line.  Omit it and the codec fails closed to
   `localised` (safe, but every Dell USM key becomes unmigratable).
4. **Declare** `dell_os10` in `_TARGET_USM_ACCEPTS` as
   `frozenset({PLAINTEXT})`, matching every other target — no target can
   consume another agent's localised key.
5. **Explicitly declare** `/snmp/v3-user/auth-passphrase` and
   `/snmp/v3-user/priv-passphrase` in the capability matrix.
   `classify()` defaults undeclared xpaths to `supported` — i.e. **silent
   loss**.

Also secret-bearing and needing sanitiser coverage: `username … password
$6$…`, `system-user linuxadmin password $6$…`, and the SNMP v3 key
positions.

---

## 5. Wiring checklist (exact sites, verified)

| # | Site | Change |
|---|---|---|
| 1 | `netcanon/migration/vendors/dell_os10.yaml` | **new** — pure data (`VendorInfo`: `id`, `display_name`, `device_classes`, `default_timeout`, `notes`) |
| 2 | `netcanon/migration/codecs/dell_os10/` | **new** package; `@register` on the `CodecBase` subclass |
| 3 | `netcanon/migration/codecs/base.py:118` `INPUT_FORMATS` | add `cli-dellos10` |
| 4 | **NINE** explicit import lists (see below) | 12-name list → 13, in each |
| 5 | `tests/fixtures/synthetic/dell_os10/kitchen_sink.cfg` | **new, MANDATORY** — see below |
| 6 | `netcanon/migration/_usm_keys.py` | `_SOURCE_DEFAULT_KIND` + `_TARGET_USM_ACCEPTS` |
| 7 | `tests/unit/migration/test_synthetic_dell_os10_kitchen_sink.py` | **new** (one per codec convention) |
| 8 | `docs/CAPABILITIES.md` § Supported vendors | new table row |
| 9 | `docs/vendors/dell_os10.md` | **new** operator page (8-section format) |
| 10 | `docs/vendor-references/dell_os10_to_*/` + `*_to_dell_os10/` | **24 new pair directories** |
| 11 | `tests/fixtures/cross_vendor_expectations/` | **24 new pair YAMLs** |
| 12 | regen | `py tools/run_full_mesh.py --matrix` → `py tools/run_phase4_reconciliation.py --write-baseline` |

### ⚠️ Correction: there are NINE import-list rot points, not two

An earlier revision of this checklist named two (`run_full_mesh.py` and
`test_registry_capability_honesty.py`).  A repo-wide grep finds **nine**
hand-maintained 12-codec import lists, every one of which must gain
`dell_os10`:

```
tools/run_full_mesh.py:102
tests/unit/migration/test_bidirectionality_invariants.py:45
tests/unit/migration/test_cross_mesh_overrides.py:47
tests/unit/migration/test_lag_mode_fidelity.py:41
tests/unit/migration/test_real_captures.py:60
tests/unit/migration/test_registry_capability_honesty.py:102
tests/unit/migration/test_silent_loss_list_subfields.py:72
tests/unit/migration/test_silent_loss_naming_sensitive.py:65
tests/unit/migration/test_synthetic_kitchen_sink_round_trips.py:62
```

Everything else (`test_cross_codec_matrix`, `test_device_class`,
`test_input_format`, `test_codec_header_certainty`,
`test_canonical_vrrp_anycast_schema`) derives its roster from
`list_codecs()` / `list_public_codecs()` and self-adjusts.
`test_cross_mesh_overrides.py`'s `_resolve_codec_class` raises *"Did you
forget to import `netcanon.migration.codecs.<vendor>`"* — that is the
guard that fires on a missed registration.

### The synthetic kitchen-sink is mandatory, and gated on `direction`

`test_corpus_covers_every_round_trippable_codec` asserts every registered
non-`mock` codec is represented in
`tests/fixtures/synthetic/<codec>/`, and
`test_every_synthetic_dir_maps_to_a_registered_codec` asserts the
converse.  The two together mean the fixture directory and the
registration must land in the SAME change — creating the directory early
fails the second guard, and registering without it fails the first.

### Ten disposition rows (computed, not guessed)

The PR-2a/2b/2c walk-expansion guards treat a codec ABSENT from a leaf's
`_EXPECTED` dict as expected-`supported`, so every leaf `dell_os10`
declares lossy needs an explicit row.  Measured against the shipped
matrix, ten rows are required and five are correctly omitted:

| guard | rows needed |
|---|---|
| `test_vrrp_subfield_walk_expansion` | `mode`, `advertisement-interval`, `authentication`, `virtual-ipv6s`, `description` (5) |
| `test_snmpv3_subfield_walk_expansion` | `auth-protocol`, `priv-protocol`, `priv-passphrase` (3) |
| `test_singleton_subfield_walk_expansion` | `instance-type` (1) |

`priority`, `preempt`, `/snmp/v3-user/group`, `/routing/static-route/gateway`
and `/interfaces/interface/ipv6/address/scope` classify `supported` and
must stay absent.

`test_secret_fail_open.py`'s parametrized emit-table check only needs a
row if the codec gains a password-type table (like `_NXOS_PASSWORD_TYPE`).

---

## 6. Mesh + gate impact — this is the expensive part

Current baseline (`tests/fixtures/real/_phase4_runs/latest.json`):
**`cells_total = 1224`**, 132 expectation YAMLs = one per ordered
cross-vendor pair (12 × 11).

A 13th codec makes it **13 × 12 = 156** ordered pairs: **+24 pairs, +24
expectation YAMLs**, and a materially larger `cells_total`.

`tests/integration/test_cross_mesh_ci_guard.py` asserts
`cells_total == baseline` **exactly**, so the baseline *must* be
re-cut with `--write-baseline`. The standing gates still apply:

- `CODEC_BUG <= 5` (`_ABSOLUTE_CODEC_BUG_CEILING`)
- `METHODOLOGY_ISSUE_over = 21`
- `METHODOLOGY_ISSUE_under` ratcheted `live <= baseline`

### ⚠️ The coverage ratchet makes Phase 4 ATOMIC (measured 2026-09-21)

The committed baseline reads:

```
cells_total                    : 1224
cells_without_expectation_yaml : 0        <- the ratchet floor
expectation_yamls_loaded       : 132
all_codecs                     : 12
```

and `docs/vendor-references/` holds **132 directories — one per ordered
pair**.  Coverage is complete, at zero.

`test_cross_mesh_ci_guard.py:378` asserts

```python
len(result["cells_without_expectation_yaml"]) <= len(baseline[...])
```

Against a floor of **0**, that means *any* pair lacking a YAML fails.  So
registration cannot be split from authoring, and there are only three
honest ways forward:

| option | cost | what it does to the invariant |
|---|---|---|
| **A — author all 24** | 24 expectation YAMLs + 24 `canonical_surface.md` docs, each from a measured mesh run, each walking all 21 `_AUDITED_FIELDS` | keeps `cells_without_expectation_yaml` at 0 |
| **B — register and re-cut** | small | **loosens the ratchet 0 → 24.** Wave A6 (#444/#450/#452/#453/#454) took five PRs to reach 0; this gives part of that back |
| **C — stop before registration** | none | Phases 1-3 ship as a self-contained codec; Phase 4 becomes its own PR |

> **Resolved: C then A.**  Phases 1-3 shipped unregistered as PR #478
> (option C), and Phase 4 then took **option A** — all 24 YAMLs authored,
> ratchet held at 0.  Option B was rejected: wave A6 spent five PRs
> (#444/#450/#452/#453/#454) driving `cells_without_expectation_yaml`
> to 0, and loosening it 0 → 24 would hand most of that back.
>
> The authoring rule that actually binds is NOT "read the two matrices".
> It is the per-pair unevidenced ratchet
> (`test_no_new_pair_declares_a_loss_it_never_observes`), which allows a
> pair absent from `_UNEVIDENCED_BASELINE` exactly **zero** declared-but-
> never-observed losses.  So a field the corpus PRESERVES on every cell
> must be `good` — hedging it to `lossy` fails the build just as surely
> as under-declaring a real loss does.  Every disposition here was
> resolved through the audit's own `actual_disposition()` over a measured
> run.
>
> ⚠️ **Replaying `derive_variance` is NOT verification.**  That was tried
> as a pre-flight check and reported both gates clean; the real guard
> then found **40 unevidenced fields across 9 pairs**.  The reconciler
> applies a `STRUCTURAL_ONLY` collapse AFTER `derive_variance`: when a
> list parent drifts wholesale, the FIRST sub-field in YAML insertion
> order owns the structural signal and every sibling on that cell is
> overridden to `STRUCTURAL_ONLY`.  A field whose only drifted cells were
> collapsed never earns an `EXPECTED_LOSSY`, so declaring it lossy reads
> as unevidenced even though the parent really did drift.
>
> The fix was to drive the dispositions to a fixed point against the
> RECONCILER'S OWN per-cell output (`field_variances`), not a model of
> it — two iterations, 40 fields to `good`, 0 back to `lossy`, 0 new
> `CODEC_BUG`.  Anyone authoring the next codec's pairs should skip the
> simulation entirely and iterate against `run_phase4_reconciliation.py`
> from the start.

⚠️ **The YAMLs cannot be written in advance.**  Their dispositions come
from OBSERVED drift, not from the capability matrices — the schema spec
is explicit that "a field that never drifts is `good` even where the
target matrix declares a lossy path, and a field that drifts is `lossy`
even where both matrices call it supported."  So the order is forced:
wire → run the mesh → read the drift → author → `--write-baseline`.

Nor can they be stubbed: `test_every_declared_reference_path_resolves`
rejects a dangling `references[].path`, so each YAML drags its
`canonical_surface.md` with it, and the README requires an unresearched
field to appear explicitly as `lossy` + "deferred to subsequent audit
pass" rather than be omitted.

> **The 24 expectation YAMLs are the real cost of this codec**, not the
> parser — and Phases 1-3 landing green does not shorten them by a day.
> Budget accordingly, and do not treat "write the parser" as the bulk of
> it.

---

## 7. Corpus adequacy

12 permissively-licensed configs — count is fine, **version spread is
not**. Only 6 carry a version banner and all say `10.5.1.0`; current
trains are 10.5.6 / 10.6.0 / 10.6.1. Only those 6 are genuine device
dumps; the rest are authored scripts (`configure terminal`, `write
memory`, `<PLACEHOLDER>`) and are **parse-only, not round-trip
fixtures**. Details + licence ledger in [`20-corpus.md`](20-corpus.md).

Free OS10 virtual images (GNS3 / EVE-NG qcow2) exist, so unlike
`CiscoNXOS`/`CiscoIOSXR`/`ArubaCX` a Dell device definition could ship
**live-validated** rather than provisional — gated on the Proxmox estate
returning.

---

## 8. Recommended phasing

**Phase 0 — ✅ DONE (PR #475).** `cisco_iosxe_cli.probe()` now defers on
OS10 markers, closing the live fail-open where Dell configs were parsed as
Cisco. Shipped standalone, ahead of any codec work.

**Phase 1 — ✅ DONE.** hostname + interfaces + VLANs + switchport + LAGs +
VRF declarations + static routes, parse-only.  Shipped unregistered.

**Phase 2 — ✅ DONE.** Render path, canonical-stable round-trip, and
Tier-3 loss surfacing (`dropped_tier3_sections`).  `direction` flipped to
`bidirectional`, `certainty` to `best_effort`.

**Phase 2.5 — ✅ DONE (unplanned, found by measurement).**  47 walkable
xpaths were silently defaulting to `supported` because
`CapabilityMatrix.classify()` is an EXACT-STRING match — declaring a
parent (`/snmp/v3-user`, `/interfaces/interface/vrrp-groups/group`) does
NOT cover its children.  The matrix now carries 102 explicit declarations
and exactly 8 leaves rely on the default, each proved to round-trip by a
counter-case.

**Phase 3 — ✅ DONE.** Local users (`priv-lvl` optional — 2 of 8 real
lines omit it), SNMP v2c + v3 USM **with the per-line `localized` marker
from day one**, and VRRP (real VRRP, no HSRP normalisation).  OS10's
per-codec default kind is `plaintext`, the OPPOSITE of NX-OS, so an
unmarked native value must render WITHOUT the keyword — pinned by
`test_dellos10_snmpv3_key_gate.py`.

Measured at the end of Phase 3: **14/14 real captures parse cleanly and
14/14 round-trip canonical-stable** under the repo's own comparator.

**Phase 4 — ✅ DONE.**  Registered as the 13th codec via **option A**
(§ 6): the mesh grew 1224 → **1339** cells across **156** ordered pairs,
and all **24** new pair-expectation YAMLs + their
`docs/vendor-references/` companions were authored from a MEASURED mesh
run, holding `cells_without_expectation_yaml` at **0**.  `CODEC_BUG`
stayed at 5 and `METHODOLOGY_ISSUE_over` at 21; all 24 new pairs render
and re-parse with zero errors.

**Deferred:** VXLAN/EVPN `virtual-network`, VLT, QoS/DCB.

---

## 9. Open questions

1. `probe_bytes = 500` cannot cover OS10 configs that spend the window
   on a preamble. Accept the tail, or raise the window globally?

   **Quantified 2026-09-21 over a 40-capture corpus** (was: "the four
   DellGEOS captures"). Running the real `detect_codec()` across all
   codecs, not `dell_os10.probe()` alone:

   | Outcome | Count |
   |---|---|
   | `dell_os10` wins outright | 19 |
   | No candidate at all | 7 |
   | **Genuine OS10 claimed by `cisco_iosxe_cli`** | **10** (4 at ≥90) |
   | OS9/FTOS claimed by `cisco_iosxe_cli` @95 | 4 (expected — #475 left FTOS matching via `service timestamps`) |

   So the failure mode is NOT silence, it is **mis-attribution to the
   Cisco codec** — the #460/#475 fail-open shape, at confidence 90.
   Three distinct preamble classes cause it: jinja2 template headers
   (`! system.j2`), serial-console login banners, and QoS-leading
   configs. The first two carry a valid OS10 marker *later in the
   file*, so a wider window would rescue them; the QoS-leading
   DellGEOS captures are markerless throughout and would not be.
   Pinned in
   `tests/unit/migration/codecs/dell_os10/test_probe_window_limits.py`.
2. `feature config-os9-style` lets OS10 present OS9-style commands —
   a config collected under it may not match the OS10 grammar at all.
   Unquantified; no capture in this corpus exercises it.
3. OS9 → OS10 is a vendor-acknowledged migration corridor with an official
   Dell command-mapping guide. If OS9 ever ships, that pair is the
   highest-value in the matrix — see [`40-os9-appendix.md`](40-os9-appendix.md).
4. The `dell-tsb/*` leaf/spine configs are the best-structured OS10
   material found but carry **no licence**. Worth an explicit request to
   Dell TSB.
