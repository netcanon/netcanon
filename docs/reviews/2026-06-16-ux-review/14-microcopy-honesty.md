# 14 — Microcopy & honesty audit (R5)

**Scope:** user-facing strings across every template (labels, buttons,
helptext, placeholders, error/empty/tooltip copy), with emphasis on
`migrate.html` + `diff.html` (the translation-fidelity surface), checked
against `docs/CAPABILITIES.md` + `docs/TROUBLESHOOTING.md` as ground
truth, plus the messages `netcanon/api/routes/migration.py` emits.

**Verdict:** the in-app honesty discipline is, on the whole, genuinely
good — the migrate page surfaces a Tier-3 banner, a three-bucket
supported/lossy/unsupported panel, per-pane "won't render" compat
banners, and a hash-never-falls-back-to-plaintext policy that all match
`CAPABILITIES.md`. The vocabulary is mostly accurate and the error
formatter (`formatApiError`) is a real asset. The defects are
concentrated in **a small number of over-claiming or under-explaining
strings**, not a systemic dishonesty. The single most important finding
is the **"Certified ≠ deploy-ready" gap**: `CAPABILITIES.md` makes that
caveat load-bearing, but the migrate page (the one screen where an
operator copies rendered output and may paste it onto a device) never
states it, and one banner literally says output "round-trips cleanly"
with a green checkmark and a Copy/Download button right beside it.

Below: top 5 first, then the full findings table, then per-surface
notes.

---

## Top 5 (lead findings)

### 1. CONFUSING — migrate page never says "rendered output is NOT deploy-ready" (the load-bearing CAPABILITIES caveat is missing from the one screen it matters on)

`docs/CAPABILITIES.md:48-51` makes this an explicit, blockquoted product
promise:

> **Certified ≠ deploy-ready.** The `certainty` label rates *round-trip
> fidelity* … not deploy automation. Netcanon has no deploy path today
> — rendered output is for manual review and apply…

The migrate page is where an operator obtains rendered output and is
handed a **Copy** and **Download** button (`migrate.html:463-472`). It
never restates this caveat. Worse, the success banner reads:

```
&#10003; Validation OK — every path round-trips cleanly.
```
(`migrate.html:1516`)

A green check + "round-trips cleanly" + a Download button reads as "this
is safe to apply." It is not — `round-trips cleanly` is a *fidelity*
claim about the canonical model, not a *deploy-safety* claim, and the
two are conflated for a reader who hasn't read CAPABILITIES.md. The
intro paragraph (`migrate.html:319-325`) explains capability gaps but
says nothing about review-before-deploy.

**Fix shape:** add a one-line standing note in the Rendered-output
section header (e.g. near `migrate.html:450`): *"For manual review and
apply — Netcanon has no deploy path; verify on the device before
loading."* And soften the OK banner to *"Validation OK — every populated
field maps to a supported path on the target. Review before applying."*
**Effort: S.**

### 2. CONFUSING — "Validation OK — every path round-trips cleanly" overclaims; it only describes *populated* leaves, and "round-trips" is the wrong fidelity axis for cross-vendor

`migrate.html:1515-1516` fires the OK banner whenever
`validation.severity === 'ok'`. Per `CAPABILITIES.md:526-528`, `ok`
means *"every **populated** canonical leaf maps to a `supported` xpath on
the target."* Two honesty problems:

- **"every path"** is broader than the truth. Tier-3 sections (firewall,
  NAT, etc.) were dropped *before* validation and never become "paths,"
  so a config can show "Validation OK — every path round-trips cleanly"
  while the Tier-3 banner simultaneously says 47 firewall lines were
  dropped. The two banners visually contradict (green "everything's
  fine" + amber "we dropped a pile of your config"). The OK copy should
  be scoped to *"every field we translate maps to a supported path,"* not
  *"every path."*
- **"round-trips cleanly"** is the same-vendor fidelity term
  (`CAPABILITIES.md:579-582` "Round-trip vs. cross-vendor" — two distinct
  surfaces "often confused"). For a cross-vendor run, `ok` does **not**
  promise a round-trip; it promises supported-path coverage. Using the
  round-trip word here imports the wrong guarantee.

**Fix shape:** *"Validation OK — every field that translates maps to a
supported path on the target. Tier-3 sections (if any) are listed
separately above."* **Effort: S.**

### 3. CONFUSING — "Translate will almost certainly fail" / "round-trips cleanly" and the broader jargon load assume the operator already knows the matrix vocabulary

The migrate page leans hard on unexplained terms in
**operator-facing** (not just code-comment) strings: `Tier-3` /
`canonical` / `lossy` / `round-trip` / `Force cross-class` / `device
class` / `raw_sections` / `RD/RT` (via the capability panel reasons).
Examples that reach the screen:

- Intro: *"Netcanon translates the **canonical** config across vendors"*
  (`migrate.html:322`) — "canonical" is internal architecture jargon.
- Force checkbox: *"Force cross-class"* with tooltip *"Skip the
  device-class guard (NOT recommended)"* (`migrate.html:413-415`). What a
  "device class" is, and why crossing it is risky, is never said. The
  class-hint warning *"⚠ No shared device class — guard will block unless
  'Force cross-class' is ticked"* (`migrate.html:968-969`) compounds it.
- Compat banner: *"… are currently Tier-3 passthrough (**raw_sections**)"*
  (`migrate.html:2080`) — `raw_sections` is a literal internal field
  name leaking to the UI.

None of these is individually fatal, but collectively a first-time
operator has no in-app glossary. `TROUBLESHOOTING.md` and `CAPABILITIES.md`
define every term — but there is **no link from the migrate page to
either doc** (cf. finding 5).

**Fix shape:** (a) link the migrate intro + the Validation-details
`<summary>` to `docs/CAPABILITIES.md` and `docs/TROUBLESHOOTING.md`; (b)
replace `raw_sections` in `migrate.html:2080` with plain prose
("kept as opaque pass-through"); (c) one-clause gloss on "device class"
in the Force tooltip. **Effort: S–M.**

### 4. CONFUSING/INCONSISTENT — the three honesty surfaces (Tier-3 vs Lossy vs Unsupported) are visually distinguishable but never *named/explained* on-page, and CODEC_BUG — the third leg of the discipline — has no in-app presence at all

`TROUBLESHOOTING.md:6-9` defines the whole product discipline as three
camps: **Tier-3 (expected)**, **Lossy (expected)**, **CODEC_BUG (actual
bug)**. The migrate page surfaces Tier-3 and Lossy/Unsupported well, but:

- It never tells the operator *what to do* with a lossy/unsupported path.
  `TROUBLESHOOTING.md:49-61` says lossy paths "usually have a
  review-comment in the rendered output describing the drift" — the
  migrate page's lossy panel (`migrate.html:493-495` + `fillPathList`)
  shows path + reason + a `lossy` chip but never points the operator at
  the `review:` comments in the output or at the troubleshooting flow.
- **CODEC_BUG has zero in-app surface.** That's defensible (the UI can't
  know it produced a bug), but it means an operator who hits the
  TROUBLESHOOTING "is it actually a CODEC_BUG?" question
  (`TROUBLESHOOTING.md:64-105`) gets no in-app on-ramp — no "something
  look wrong? → report it" affordance, and no link to `BUG_REPORTING.md`.
  For a tool whose differentiator is matrix-honesty, the absence of a
  "report a bad translation" link on the result screen is a real gap.

**Fix shape:** add a small footer under the result region: *"Output
missing something or syntactically wrong? See the troubleshooting flow
(Tier-3 vs Lossy vs bug) → [TROUBLESHOOTING.md] · file a report →
[BUG_REPORTING.md]."* **Effort: S.**

### 5. INCONSISTENT — terminology drift: "config" vs "configuration" vs "backup," and "adapter" vs "codec" vs "vendor" used interchangeably across the same flow

Two distinct drift axes, both operator-visible:

- **config / configuration / backup.** `configs.html:57-59` empty state
  says *"No **configuration files** stored yet. Run a **backup**…"*;
  `migrate.html` calls the same artifacts *"stored config"*
  (`migrate.html:392`, `354`); the dashboard calls them *"backup jobs"*
  and *"Recent Jobs."* Three nouns for one artifact class. The nav label
  is **Configs**, the route is `/configs`, the thing is produced by a
  **Backup**. An operator has to infer that "stored config" = "the
  configuration file a backup produced."
- **adapter / codec / vendor.** The migrate dropdowns are labelled
  **"Source adapter" / "Target adapter"** (`migrate.html:330,337`), the
  detect banner says **"Detected: <vendor>"**, the compat banner says
  **"Target codec doesn't render…"** (`migrate.html:2076`), and toasts
  say **"No sample available for <codec-name>"** (the raw codec id, e.g.
  `cisco_iosxe_cli`, `migrate.html:1007`). Sanitize page uses **"Source
  vendor"** (`sanitize.html:78`) for the same control the migrate page
  calls **"Source adapter."** So the same concept is "adapter," "codec,"
  and "vendor" within two screens of each other, and the user sees raw
  internal codec ids in some error toasts but friendly vendor names
  elsewhere.

**Fix shape:** pick one operator-facing noun per concept — recommend
**"config"** (drop "configuration"/"backup file") and **"vendor format"**
or simply **"format"** for the adapter selectors (the dropdowns already
show the input_format), reserving "codec"/"adapter" for code/docs. At
minimum, make migrate + sanitize agree on Source label. **Effort: M**
(touches several templates; behaviour-preserving).

---

## Findings table

| # | Path:Line | Severity | Finding | Fix shape | Effort |
|---|-----------|----------|---------|-----------|--------|
| 1 | `migrate.html:450,463-472,1516` | CONFUSING | No "rendered output is for manual review, not deploy-ready" caveat on the migrate screen; conflicts with `CAPABILITIES.md:48-51` | Standing review-before-deploy note near output header; soften OK banner | S |
| 2 | `migrate.html:1515-1516` | CONFUSING | OK banner overclaims: "every path round-trips cleanly" — actually only *populated* leaves, and "round-trips" is the wrong axis cross-vendor (`CAPABILITIES.md:526-528,579-582`) | Rescope copy to "every field that translates maps to a supported path" | S |
| 3 | `migrate.html:322,413-415,968-969,2080` | CONFUSING | Unexplained jargon in user-facing strings: canonical / device class / Tier-3 / raw_sections; no in-app glossary or doc link | Link to CAPABILITIES/TROUBLESHOOTING; de-jargon `raw_sections`; gloss "device class" | S–M |
| 4 | `migrate.html` (whole result region) | CONFUSING | Lossy/unsupported panels don't tell operator what to do; CODEC_BUG has no in-app on-ramp; no link to BUG_REPORTING (`TROUBLESHOOTING.md:6-9,64-105`) | Add result-footer link to troubleshooting flow + bug report | S |
| 5 | `configs.html:57-59`, `migrate.html:330,337,392`, `sanitize.html:78`, `index.html:104` | INCONSISTENT | "config"/"configuration"/"backup" and "adapter"/"codec"/"vendor" used for the same concepts; raw codec ids leak in toasts | Standardise nouns; align migrate+sanitize "Source" label | M |
| 6 | `migrate.html:1042` | CONFUSING | "Translate will almost certainly fail." — definitive prediction on a heuristic (extension mismatch); could over-deter a legitimate paste | Soften to "is unlikely to parse — paste the text instead" | S |
| 7 | `migrate.html:861-864` | CONFUSING | Fallback adapter desc leaks a developer instruction to the operator: "Check its docstring for what parse() expects." | Operator-facing fallback ("No description available for this format.") | S |
| 8 | `definitions.html:587-589` | INCONSISTENT | In-app certainty gloss (certified "≥3 real captures from ≥2 OS versions") states hard numbers that AGENTS.md "Never hard-code a count" rule keeps out of prose docs; risks drift vs RESULTS.md | Qualitative phrasing or link to RESULTS.md as source of truth | S |
| 9 | `migrate.html:415` | CONFUSING | "Force cross-class" + "(NOT recommended)" never says *what bad thing* happens; the guard exists to stop nonsense translations (firewall→switch) | One clause: "may produce nonsensical output — only for deliberate cross-class experiments" | S |
| 10 | `migrate.html:1553-1556` vs `CAPABILITIES.md:441-446` | POLISH | Tier-3 banner body is near-verbatim with CAPABILITIES (good) but the literal example "(firewall rules, NAT, QoS, route-maps, IPsec, etc.)" is hard-coded in JS and could drift if the Tier-3 list changes | Acceptable today; note as drift-watch, optionally link to the doc | S |
| 11 | `migrate.html:889` | INCONSISTENT | "Failed to load adapters: HTTP 500" exposes a bare status code with no recovery hint (every other form uses `formatApiError`) | Add "— reload the page or check the server log" | S |
| 12 | `diff.html:141` | CONFUSING (mild) | Forced cross-vendor diff banner: "semantic equivalence is NOT guaranteed. Changes shown are textual only." is good, but reasons render at `opacity:.85` tiny text — the honest caveat is visually de-emphasised | Keep reasons at banner font-size; don't dim the load-bearing caveat | S |
| 13 | `definitions.html:566-569` | POLISH | Empty target-profiles state explains consequence well; fine. (Listed as positive example.) | — | — |
| 14 | `index.html:131`, `jobs.html:44`, `configs.html:58`, `devices.html:113`, `schedules.html:111` | POLISH | Empty states are consistently good (explain + point to the action). One nit: jobs.html says "Start one from the Dashboard" but the Dashboard's own empty state says "Fill in the form above" — fine, but the cross-references are asymmetric | None required; noted for completeness | S |

---

## Honesty deep-dive (the load-bearing axis)

The blackboard flags honesty as a product value and asks specifically:
are *lossy / Tier-3-unsupported / best-effort / CODEC_BUG* outcomes
surfaced **distinguishably and accurately**, and do in-app messages
**match `CAPABILITIES.md`**? Findings:

**What is honest and matches the docs (credit where due):**

- **Tier-3 banner copy** (`migrate.html:1549-1556`) is near-verbatim with
  `CAPABILITIES.md:441-446` and `TROUBLESHOOTING.md:18-26` — same
  enumeration, same "will NOT appear / apply manually on the target"
  framing. This is the cross-reference discipline working as intended.
- **Three-bucket panel** (`migrate.html:482-503`) maps 1:1 to
  CAPABILITIES § A (Supported / Lossy / Unsupported) and shows the
  codec-declared *reason* per path (`fillPathList`,
  `migrate.html:1597-1610`), which is exactly the "expected, with a cited
  reason" promise of `TROUBLESHOOTING.md:38-47`.
- **Per-pane compat banner** (`renderCompatBanners`,
  `migrate.html:2045-2090`) is the honest fix for the "ghost-success" bug
  named in `CAPABILITIES.md:537-547` § E: it warns that rename overrides
  "will apply to the canonical tree but won't appear in the rendered
  output." Accurate and well-scoped.
- **Hash-portability honesty** is preserved end-to-end: sanitize's safety
  note (`sanitize.html:66-72`) and the never-fallback-to-plaintext policy
  (`CAPABILITIES.md:471-487`, `TROUBLESHOOTING.md:99-104`) are consistent;
  the sanitize page even warns placeholders are "intentionally
  non-functional." Strong.
- **Diff cross-vendor caveat** (`diff.html:141`) is honest: "semantic
  equivalence is NOT guaranteed. Changes shown are textual only" — exactly
  the right hedge for a textual diff across vendors. (Only nit: it's
  visually dimmed, finding 12.)
- **Validation severity** ok/warn/block in the banner
  (`migrate.html:1423-1432`) follows the `CAPABILITIES.md:520-535` § D
  rules; "Blocked" vs "Warning" wording is accurate.

**Where honesty slips (the real defects):**

- The **OK banner overclaims** (findings 1, 2): green check +
  "round-trips cleanly" + Copy/Download = an implicit deploy-safe signal
  the docs explicitly disclaim.
- **No deploy-readiness caveat** anywhere in the migrate flow (finding 1)
  — the single biggest honesty gap because the migrate page is the exact
  point of maximum "I'll just paste this on the device" temptation.
- **CODEC_BUG is invisible in-app** (finding 4): the third leg of the
  declared discipline (`TROUBLESHOOTING.md:6-9`) has no on-ramp, so the
  honest "this might be a bug, here's how to tell / report it" message
  lives only in docs the operator may never find from the UI.
- **No link from the UI to CAPABILITIES.md / TROUBLESHOOTING.md /
  BUG_REPORTING.md** (findings 3, 4). The docs are excellent and the UI
  copy is cross-referenced *in spirit*, but there is no actual hyperlink
  bridging the in-app moment to the ground-truth doc. The nav links to
  `/docs` (Swagger) but not to the operator capability docs.

**Accuracy of the messages `migration.py` emits:** the route docstrings
(`migration.py:175-211`) correctly describe `completed` / `partial` /
`failed` and that `partial` means "rendered output exists but should be
reviewed before deploying" — and the migrate JS treats `partial` as
`block`/red (`migrate.html:1424-1425`), which is consistent and honest.
The 422 error messages (e.g. `migration.py:610-616` "Exactly one of
`raw_text` or `source_filename` is required") are specific and
actionable; combined with `formatApiError` they surface cleanly. No
dishonest copy in the API layer.

---

## Clarity / jargon notes

- **Tooltips are genuinely strong** on the dashboard backup form
  (`index.html:32,45,51,57,64,72,78`) — Host/IP examples, username
  defaults per vendor, enable-password explained, port "change only if
  non-standard." This is a model the migrate page should emulate.
- The migrate **source/target select tooltips** (`migrate.html:333,340`)
  are good and concrete (CLI vs XML vs set-form). Keep.
- The recurring **jargon load** is the clarity weak point (finding 3):
  canonical / Tier-3 / lossy / round-trip / device class / raw_sections
  appear in operator strings with no gloss and no doc link.

## Error-copy notes

- `formatApiError` (`base.html:602-618`) is a real asset — it normalises
  both FastAPI HTTPException string detail and Pydantic-422 arrays into
  one readable line, with a documented history of why (`[object Object]`
  swallowing). Most error toasts route through it and are specific. Good.
- Bare-status-code exceptions (finding 11, `migrate.html:889`) and a few
  `res.statusText`-only toasts (`configs.html:162`,
  `definitions.html:709`) bypass `formatApiError` and degrade to terse
  "Reload failed: Internal Server Error." Minor but inconsistent.
- No "something went wrong" generic copy found — good; the app
  consistently includes the underlying message.

## Empty-state / first-run notes

- Empty states are uniformly good and follow one pattern: state the
  emptiness + point at the action (`index.html:131`, `jobs.html:44`,
  `configs.html:58`, `devices.html:113`, `schedules.html:111`,
  `definitions.html:566`). The migrate rename-modal empty panes are
  *excellent* — they explain *why* a pane might legitimately be empty
  (TACACS-only devices have no local users, `migrate.html:697-702`; SNMPv3
  vs v2c, `migrate.html:727-732`). This is best-in-app microcopy.
- `schedules.html:92-93` correctly gates the schedule form on having a
  device profile first and links to `/devices`. Good first-run chaining.
- **First-run on migrate** is the weak spot: the textarea placeholder
  *"Pick a source adapter above and a matching sample will appear here."*
  (`migrate.html:375`) is fine, but the only path to actually understand
  what the tool *won't* do is post-translation. No pre-run expectation
  setting beyond the intro paragraph.

---

## Over-engineering / scope flags

- **Don't build an in-app glossary modal or tooltips-everywhere system.**
  The fix for the jargon findings is *links to existing docs* +
  de-jargoning a handful of strings, not a new help subsystem. The docs
  are already the source of truth; the gap is the hyperlink, not the
  content.
- **Don't add a CODEC_BUG detector.** Finding 4's fix is a static link to
  TROUBLESHOOTING/BUG_REPORTING, not heuristics that guess whether output
  is buggy.
- The terminology-standardisation (finding 5) should stay
  behaviour-preserving copy edits; resist renaming routes/testids/API
  fields (`/configs`, `data-testid`s, `source`/`target` body fields) —
  those are contracts. Only the *visible labels* should converge.
- Finding 8 (hard-coded certainty numbers) — the right fix is *removal*
  toward qualitative phrasing per the AGENTS.md rule, not adding a CI
  guard to keep the in-prose numbers honest (that would be gold-plating a
  string that shouldn't carry numbers at all).

---

## Cross-references checked

- `docs/CAPABILITIES.md` — §§ Translation tiers, A (matrix), B (Tier-3
  banner), C (review comments), D (severity), E (rename compat banner),
  and the "Certified ≠ deploy-ready" + "Round-trip vs cross-vendor"
  notes. In-app Tier-3 / three-bucket / compat-banner copy matches; the
  deploy-readiness + round-trip-vs-cross-vendor distinctions do NOT reach
  the migrate UI (findings 1, 2).
- `docs/TROUBLESHOOTING.md` — the Tier-3 / Lossy / CODEC_BUG triage. UI
  covers two of three; CODEC_BUG has no in-app on-ramp (finding 4).
- `netcanon/api/routes/migration.py` — status/severity semantics and 422
  messages are honest and actionable; no copy defect in the API layer.
