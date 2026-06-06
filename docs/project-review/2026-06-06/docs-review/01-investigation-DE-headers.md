# 01 — Investigation DE: File-header conventions where appropriate

Reviewer **DE**, Fleet D (documentation), read-only project review of
**netcanon** at HEAD `b08040c` / **v0.1.2**.

---

## 1. Scope & method

### 1.1 What this lens owns

Top-of-file **HEADER** blocks in their *orientation* role — the
"where am I, what does this file do, where does the rest live" job a
header does at a glance, distinct from the API-doc role of the same
docstrings (that is DD's lens; where a header *is* the module
docstring, I judge orientation, DD judges Args/Returns/Raises). In
scope:

* the 8 real codec `__init__.py` + `codec.py` module headers
  (Scope / Module-layout / Direction / Certainty blocks), plus the
  `_mock` scaffold;
* template header comment blocks (`migrate.html`'s "Contents map";
  whether other large templates that warrant one have one);
* `tools/*.py` and `netcanon/tools/*.py` headers;
* `netcanon_desktop/*` headers;
* license / SPDX headers and shebangs;
* the platform god-files' orientation headers
  (`api/routes/ui.py`, `models/migration.py`,
  `services/migration_pipeline.py`, `migration/canonical/intent.py`),
  plus entry points `main.py` / `cli.py`.

### 1.2 Method

Read all 18 codec module files (9 `__init__.py` + 9 `codec.py`,
including `_mock`), all 23 templates' heads, all 4 `tools/*.py`, the
2 `netcanon/tools/*.py`, the 11 `netcanon_desktop/*.py` heads, the 4
named god-files, both entry points, and 3 representative
`_partials/*.js`. Cross-checked ordinals, Direction/Certainty labels,
and certainty values against the `*: ClassVar` declarations in each
`codec.py` (via `Grep`). Cross-referenced the codified convention in
`AGENTS.md` Documentation Sync Checklist (rows at `AGENTS.md:166`
and `AGENTS.md:171`) and the closed items in
`docs/docs-audit/2026-05-21/fix-plan.md` Commit 9 (the codec
`__init__.py` Scope→pointer conversion) so as not to re-flag closed
work. LOC spot-checks (`wc -l`) confirm I read current HEAD state:
`migrate.html` 2477, `definitions.html` 926, `ui.py` 894 — all
exactly matching `00-snapshot.md`.

Strictly read-only. No tracked file was modified.

---

## 2. Executive summary

**Header discipline in this codebase is high and clearly
intentional.** Every Python module I opened — without exception —
carries a triple-quoted orientation docstring as its first statement.
The platform god-files, the desktop shell, the canonical IR, and the
entry points are *exemplary*: they orient with "what is this / who
calls it / how is it laid out / startup-shutdown sequence" content
that is exactly the right altitude for a header. The codec corpus is
the most-templated surface and, post-audit, the codec `__init__.py`
Scope→`_CAPS` pointer conversion (Commit 9) landed cleanly across all
six files it targeted. The `_partials/*.js` fragments are unusually
well-headed for view-layer code (they document their module-scope
dependencies on the parent IIFE).

The findings are therefore about **consistency at the margins**, not
absence. Three are worth a maintainer's attention:

1. **A header now contradicts its own code.** `aruba_aoss/__init__.py:52`
   still reads `Certainty: best_effort — validated against synthetic
   fixtures`, but the code was promoted to `certified` (against *real*
   HPE-forum captures) in commit `220ab68`, and `codec.py:70` now
   declares `certainty = "certified"`. The docs-audit fixed the
   *identical* defect on MikroTik (Commit 8, D-MT-1) and missed Aruba.
   This is the single most actionable finding.

2. **The `migrate.html` "Contents map" is mis-located relative to how
   it is advertised.** Both the DE brief and `AGENTS.md:171` cite
   "migrate.html header comment" as the canonical contents-map
   exemplar — but there is **no** top-of-file orientation in
   `migrate.html`; the only "Contents map" is at `migrate.html:796`,
   inside the `{% block scripts %}` `/* */` comment, and it documents
   only the JS `_partials/` includes, not the page structure. The
   template that actually carries a proper top-of-file contents map is
   `definitions.html:4-19`.

3. **The codec orientation headers are individually good but
   collectively non-uniform** along three axes — ordinal style,
   whether Direction/Certainty are *labeled lines* vs prose, and the
   `__init__` vs `codec.py` section vocabulary. None of these is a
   correctness bug, but the brief explicitly asks whether the 8 read
   "consistently post-audit," and the honest answer is *mostly, with
   four named drifts* (see §5).

No copy-paste header bleed (a header naming the wrong vendor) was
found — the prior-session class of artifact appears genuinely closed.

Severity tally: **0 critical · 1 high · 4 medium · 5 low · 2 nits.**

---

## 3. The header convention as practiced (de-facto standard)

There is no single written "header style guide," but the practice is
consistent enough to reconstruct, and two `AGENTS.md` rows partially
codify it:

* **`AGENTS.md:166`** — modules "whose top-of-file docstring
  enumerates contents (e.g. `…/migration.py`,
  `…/migration_pipeline.py`)" must keep that enumeration current;
  *"Module docstrings that describe intent rather than inventory are
  unaffected."*
* **`AGENTS.md:171`** — "A file-tree listing or 'contents map' in any
  doc (`ARCHITECTURE.md` partial inventories, **migrate.html header
  comment**, sub-README directory trees)" must be updated in the same
  commit *or* converted to a pointer; *"prefer one-line pointers
  unless the enumeration carries load-bearing explanation."*

From the code itself, the de-facto module-header standard is:

1. **First statement is a `"""…"""` orientation docstring.** Universal
   — no module I read omits it.
2. **Line 1 is a one-line identity**: `` ``ClassName`` — <one-line
   role> `` for `codec.py`, or `<Vendor> codec — <ordinal> <noun>` for
   codec `__init__.py`, or a bare noun-phrase title for platform files
   (`"Application factory."`, `"Embedded Uvicorn server …"`).
3. **Orientation sections** follow, drawn from a recurring menu:
   `Scope` (RST `----` underline), `Module layout:` (bullet list of
   sibling files with one-line roles), `Direction:` / `Certainty:`
   labeled lines, `Tree shape` / `Round-trip invariant`, and for
   platform files `Startup sequence::` / `Shutdown sequence::` ASCII
   diagrams.
4. **"Prefer pointers" for inventories** — post-Commit-9, codec
   `__init__.py` files point at `_CAPS` on the codec class rather than
   re-listing supported xpaths (e.g. `arista_eos/__init__.py:26`:
   *"Supported / lossy / unsupported xpaths: see ``_CAPS`` on
   :class:`.codec.AristaEOSCodec`."*). This is followed by **all six**
   codecs the audit touched, plus the two reference templates
   (`cisco_iosxe_cli`, `cisco_iosxe`).
5. **`codec.py` defers to `__init__.py`** for scope: the split codecs
   open with *"See package ``__init__`` for scope …"* and then give
   the per-file Module-layout breakdown (e.g.
   `arista_eos/codec.py:4`, `fortigate_cli/codec.py:4`,
   `juniper_junos/codec.py:4`, `opnsense/codec.py:4`).
6. **No per-file license/SPDX header, no copyright banner.** Licensing
   lives in the root `LICENSE` file (confirmed present;
   `tests/fixtures/real/NOTICE.md` carries fixture provenance). The
   only `Copyright (c)` string in any `.py` is *inside fixture data*
   (`tests/unit/test_probe_parser.py:25`, a captured Cisco banner),
   not a header. This is a deliberate, internally-consistent choice —
   not a gap.
7. **Shebangs are reserved for "run directly from repo root" scripts**
   — but applied inconsistently (see DE-06).

Against this reconstructed standard the corpus scores well; the
findings below are where individual files drift from their own
neighbours.

---

## 4. Findings

Severity-ordered. Each: `file:line`, claim, evidence, suggested
direction. Severity ladder: **high** = a header asserts something
false about the current code; **medium** = a real inconsistency a
contributor would trip on or that contradicts a codified rule;
**low** = stylistic drift; **nit** = cosmetic.

---

### DE-01 — Aruba header certainty contradicts the code (HIGH)

**File:** `netcanon/migration/codecs/aruba_aoss/__init__.py:52`

**Claim.** The orientation header still declares the codec
`best_effort` and "validated against synthetic fixtures," but the
codec is shipped as `certified` and was promoted on the strength of
*real* captures. The header is stale and now actively misleads.

**Evidence.**
```
aruba_aoss/__init__.py:52   Certainty: ``best_effort`` — validated against synthetic fixtures
aruba_aoss/__init__.py:53   modelled on Aruba docs + community configs.
```
versus the ground truth in code:
```
aruba_aoss/codec.py:70      certainty: ClassVar[str] = "certified"
```
`git log` on that line: commit `220ab68` *"Aruba AOS-S promoted to
certified — 3 HPE forum real captures."* So both the tier (`best_effort`
→ `certified`) **and** the rationale ("synthetic fixtures" →
real HPE-forum captures) in the `__init__.py` header are out of date.
The docs-audit caught and fixed the structurally identical defect on
MikroTik — `fix-plan.md:132` (Commit 8, D-MT-1): *`mikrotik_routeros/__init__.py:36-39` "best_effort" → "certified"* — and MikroTik's
header now correctly reads `certified` (`mikrotik_routeros/__init__.py:28`).
Aruba was simply not on that commit's list.

**Suggested direction.** Update `aruba_aoss/__init__.py:52-53` to
`Certainty: ``certified``` and re-word the rationale to cite the real
HPE-forum captures (mirror the MikroTik wording at
`mikrotik_routeros/__init__.py:28-32`, which points at
`tests/fixtures/real/RESULTS.md`). DD should confirm there is no
*other* "synthetic" claim in the class docstring — I checked
`codec.py:59-64` and there is not, so the fix is a single-header edit.

---

### DE-02 — `migrate.html` has no top-of-file contents map; the advertised one is buried in the scripts block (MEDIUM)

**File:** `netcanon/templates/migrate.html:1-4` (absence) and
`migrate.html:796` (the actual map)

**Claim.** The DE brief, the docs-scope (`00-docs-scope.md:99`), and
the codified rule (`AGENTS.md:171`) all treat "migrate.html header
comment / Contents map" as *the* exemplar of a template contents map.
But `migrate.html` opens with no orientation at all, and its only
"Contents map" sits at line 796 inside the `{% block scripts %}`
`/* */` comment, scoped to the JS `_partials/` includes — not to the
page's HTML structure. A reader opening the 2477-line file gets zero
top-of-file orientation.

**Evidence.** The file head is bare:
```
migrate.html:1   {% extends "base.html" %}
migrate.html:2   {% block title %}Migrate — Netcanon{% endblock %}
migrate.html:3
migrate.html:4   {% block content %}
                 <style> …            ← straight into CSS
```
The "Contents map" is a JS-partials inventory far down the file:
```
migrate.html:796    * Contents map (large blocks extracted to _partials/ — included via
migrate.html:797    *   Jinja include directives; each partial shares module-scope state …
migrate.html:800    *   _partials/classify.js        — _guessKind + _looksLikeUplink
…
```
By contrast `definitions.html` *does* lead with a proper structural
contents map in a Jinja `{# #}` comment:
```
definitions.html:4    {#
definitions.html:5      Definitions browser — four sections:
definitions.html:6        1. Backup-side device definitions (family-base YAMLs).
…
definitions.html:14         4. Vendors + codec capabilities …
definitions.html:19    #}
```
So the rule's named exemplar is the *weaker* of the two, and it is
not where a reader looks first.

**Suggested direction.** Two coherent options: (a) add a short
top-of-file `{# … #}` page-structure map to `migrate.html` (mirroring
`definitions.html:4-19`) and keep the line-796 block as the
*scripts-specific* partials map; or (b) re-word `AGENTS.md:171` to cite
`definitions.html`'s header as the contents-map exemplar and describe
the migrate.html block accurately as a *scripts-block partials map*.
Either way the rule and the file should stop disagreeing about where
the map is. (The line-796 map itself is accurate and current — it
correctly lists all the rename-table partials including
`kbd-cheatsheet`-adjacent ones; this is purely a location/labeling
issue.)

---

### DE-03 — Codec `__init__.py` ordinal style is non-uniform, and one codec has no ordinal at all (MEDIUM)

**Files:** all 8 codec `__init__.py:2`

**Claim.** The codec headers open with a "<vendor> — <ordinal> <noun>"
identity line, but (a) the ordinal switches from spelled-out words for
codecs 1–3 to digit-ordinals for codecs 4–7, (b) the noun varies
across five different phrasings, and (c) `cisco_iosxe_cli` — a real,
shipped, certified codec — has **no ordinal at all**, so the
"Nth codec" series silently skips the 8th member.

**Evidence** (`Grep` over `**/__init__.py:2`):
```
cisco_iosxe        : "first real adapter."
opnsense           : "second real adapter, Phase 1."
mikrotik_routeros  : "third real adapter (Session 2 …)"
aruba_aoss         : "4th real vendor, Session C …"
fortigate_cli      : "5th real codec."
arista_eos         : "6th shipped codec, first DC-switching specialist."
juniper_junos      : "7th shipped vendor, first hierarchical-config …"
cisco_iosxe_cli    : (no ordinal — "Cisco IOS-XE CLI codec — parses + renders …")
```
Two style flips inside one corpus: `first/second/third` →
`4th/5th/6th/7th`, and the noun cycles through *adapter / real
adapter / real vendor / real codec / shipped codec / shipped vendor*.
The missing ordinal on `cisco_iosxe_cli` is defensible — it is a sibling
of the NETCONF "first real adapter" and shares `vendor_id` — but it
leaves the reader unable to reconcile "7th shipped vendor" (Junos)
against an inventory of 8 codecs.

**Suggested direction.** Low-stakes but cheap: normalise to one noun
("Nth shipped codec") and one ordinal style. If `cisco_iosxe_cli` is
intentionally un-numbered because it shares the Cisco slot, say so in
one clause (e.g. *"the CLI sibling of the first real adapter; shares
``vendor_id=cisco_iosxe``"* — which the body already explains at
`cisco_iosxe_cli/__init__.py:4-9`, just not in the identity line).
These ordinals are historical-narrative, not load-bearing, so a
maintainer may also reasonably choose to drop them entirely.

---

### DE-04 — Direction / Certainty are labeled lines in some codec headers, prose in others, absent in two (MEDIUM)

**Files:** the 8 codec `__init__.py`

**Claim.** The header convention "should" surface Direction +
Certainty as a labeled pair (that is how `cisco_iosxe_cli`, the audit's
named reference template, does it). But across the 8 the treatment is
uneven: some have both as labeled lines, some only Certainty, one only
Direction, and one (OPNsense) has neither in the `__init__.py` header.

**Evidence** (`Grep` for `Direction:` / `Certainty:` over
`**/__init__.py`):

| Codec | `Direction:` labeled line | `Certainty:` labeled line |
|---|---|---|
| `cisco_iosxe_cli` | yes (`:10`) | yes (`:11`) |
| `arista_eos` | yes (`:32`) | yes (`:33`) |
| `cisco_iosxe` | yes (`:23`) | yes (`:24`) |
| `juniper_junos` | yes (`:14`) | **no** (only in ClassVar) |
| `aruba_aoss` | **no** (prose) | yes (`:52`) |
| `fortigate_cli` | **no** (prose) | yes (`:43`) |
| `mikrotik_routeros` | **no** (prose) | yes (`:28`) |
| `opnsense` | **no** | **no** |

So only 3 of 8 carry the clean labeled pair; OPNsense surfaces neither
in its header (both are present only as ClassVars at
`opnsense/codec.py:84-85`). The values that *are* stated all match
the code except DE-01.

**Suggested direction.** If Direction/Certainty are meant to be
header-discoverable (the reference template implies they are), add the
two labeled lines to `opnsense/__init__.py`, add `Certainty:` to
`juniper_junos/__init__.py`, and lift Direction out of prose into a
labeled line for `aruba_aoss` / `fortigate_cli` / `mikrotik_routeros`.
This is the same "consistency across all 8" goal Commit 9 pursued for
the Scope block; the Direction/Certainty pair was simply not in that
commit's scope.

---

### DE-05 — `cisco_iosxe` NETCONF header uses a different section vocabulary than the seven split codecs (MEDIUM)

**Files:** `cisco_iosxe/codec.py:1-82` vs the split-codec `codec.py`
headers

**Claim.** Seven codecs are split (parse/render) and their `codec.py`
headers follow a uniform skeleton: *one-line identity → "See package
``__init__`` for scope" → `Module layout:` bullets*. The NETCONF
`cisco_iosxe/codec.py` is the one single-file codec and instead uses
`Public tree shape` / `Internal parse representation` / `Render
coverage (Phase 0.5 stub)` / `Round-trip invariant` headings, with no
"Module layout" block and no "see `__init__`" deferral. It is a good
header — but it is the odd one out, so a reader moving between codecs
loses the structural muscle-memory.

**Evidence.** Split-codec uniform shape, e.g.:
```
arista_eos/codec.py:4       See package ``__init__`` for scope + grammar-departure notes.
arista_eos/codec.py:6       Module layout (post-split):
```
mirrored verbatim in `fortigate_cli/codec.py:4-6`,
`juniper_junos/codec.py:4-7`, `opnsense/codec.py:4-6`,
`cisco_iosxe_cli/codec.py:7`, `aruba_aoss/codec.py:4-6`,
`mikrotik_routeros/codec.py:5-6`. The NETCONF outlier:
```
cisco_iosxe/codec.py:4      Public tree shape
cisco_iosxe/codec.py:13     Internal parse representation
cisco_iosxe/codec.py:68     Render coverage (Phase 0.5 stub)
cisco_iosxe/codec.py:79     Round-trip invariant (proven in unit tests):
```
The divergence is *justified* — there are no sibling parse/render
modules to lay out — but the header doesn't say "single-file codec; no
split layout," so the absence of a Module-layout block reads as an
omission rather than a deliberate difference.

**Suggested direction.** Add one orienting clause near the top —
*"Single-file codec (no parse/render split); see ``__init__`` for
scope and matrix."* — so the reader knows the missing Module-layout
block is by design. Keep the rich tree-shape sections; they are
genuinely useful.

---

### DE-06 — Shebang convention is applied to only 2 of 4 `tools/` scripts (LOW)

**Files:** `tools/*.py`

**Claim.** Two repo-root tool scripts carry `#!/usr/bin/env python`;
two equally-runnable ones do not. All four document `python tools/…`
invocation in their headers, so the shebang split is arbitrary.

**Evidence** (`Grep ^#!` over `*.py` — only two hits in the whole
tree):
```
tools/run_full_mesh.py:1              #!/usr/bin/env python
tools/run_phase4_reconciliation.py:1  #!/usr/bin/env python
```
But `tools/demo.py:1` and `tools/load_cross_vendor_expectations.py:1`
begin directly with `"""` — no shebang — despite documenting the same
direct-invocation pattern:
```
demo.py:5                          python tools/demo.py …
load_cross_vendor_expectations.py:8   python tools/load_cross_vendor_expectations.py
```
(Also note both shebangs say `python`, which on Windows resolves to the
Store shim — the project's own MEMORY notes `py` is the correct
launcher; on POSIX `python` may be Py2. This is a portability nit on
top of the inconsistency, and these files aren't `chmod +x` in a
Windows checkout anyway.)

**Suggested direction.** Pick one rule. Either add the shebang to
`demo.py` + `load_cross_vendor_expectations.py` (4/4) or drop it from
the two that have it (0/4) — all four are documented as
`python tools/…` so the shebang buys little. If kept, `python3` is the
more portable form for a POSIX shebang.

---

### DE-07 — `opnsense/__init__.py` header carries a vestigial "Phase 1" tag (LOW)

**File:** `netcanon/migration/codecs/opnsense/__init__.py:2`

**Claim.** The identity line ends with a stale internal phase tag.

**Evidence.**
```
opnsense/__init__.py:2   OPNsense adapter — second real adapter, Phase 1.
```
"Phase 1" is dev-cycle nomenclature with no meaning to a reader of
v0.1.2; it dates the header to the pre-1.0 build sequence.
`AGENTS.md:166` warns specifically that phase language in headers
*"become[s] lies the instant Phase 2 lands."* The fix-plan's Commit 9
row for OPNsense (`fix-plan.md:146`) targeted the *Scope (Phase 1)*
**enumeration** (now correctly a `_CAPS` pointer at
`opnsense/__init__.py:15`) but left the "Phase 1" tag in the line-2
identity string.

**Suggested direction.** Drop ", Phase 1" from line 2. (Compare the
clean post-audit identity lines on arista/fortigate, which carry no
phase tag.)

---

### DE-08 — `cisco_iosxe` header's "Phase 0.5 stub" framing diverges from the user-facing "NETCONF stub / best_effort" vocabulary the `__init__` settled on (LOW)

**Files:** `cisco_iosxe/codec.py:68, :190` vs
`cisco_iosxe/__init__.py:24`

**Claim.** The same codec describes its provisional status two
different ways in its two headers — "best_effort — NETCONF stub" in
the package header, "Phase 0.5 stub" in the module header — mixing the
user-facing certainty vocabulary with internal phase nomenclature.

**Evidence.**
```
cisco_iosxe/__init__.py:24   Certainty: ``best_effort`` — NETCONF stub; see
cisco_iosxe/codec.py:68      Render coverage (Phase 0.5 stub)
cisco_iosxe/codec.py:190     #: Render-coverage honesty (Wave 10γ-2): this codec is a Phase 0.5
```
The `__init__` framing ("NETCONF stub / best_effort") is the
operator-legible one; "Phase 0.5" is build-cycle shorthand. (The many
`Phase 0.5 stub` strings deeper in `codec.py` — `:223`, `:239`–`:434`,
`:631`, `:635` — are `UnsupportedPath` `reason=` runtime text and
belong to DD/DA's lens, not header orientation; I flag only the
*header* instance at `:68`.)

**Suggested direction.** Align the module-header section heading to the
package header's vocabulary, e.g. `Render coverage (NETCONF stub —
``best_effort``)`. Keeps the honesty, drops the internal phase
shorthand from the orientation surface. DD owns the body-text reason
strings.

---

### DE-09 — Most page templates open straight into `<style>`/markup with no one-line orientation (LOW)

**Files:** `diff.html`, `devices.html`, `jobs.html`, `schedules.html`,
`sanitize.html`, `configs.html`, `index.html`

**Claim.** Of the larger page templates, only `definitions.html` leads
with a structural `{# #}` header. The others jump from
`{% block content %}` directly into a `<style>` block or markup. For
the 400–600-LOC pages this is a minor orientation gap (the
sub-500-LOC ones are arguably fine without).

**Evidence.** Heads are uniformly bare of a contents/orientation
comment:
```
diff.html:4       {% block content %}\n<style>
devices.html:4    {% block content %}\n<style>
jobs.html:4       {% block content %}\n<style>
schedules.html:4  {% block content %}\n<style>
sanitize.html:4   {% block content %}\n<style>
```
(These pages *do* carry good *inline* comments — e.g.
`sanitize.html:6-9` explains why `san-*` CSS is kept page-scoped, and
`devices.html:20`'s `<!-- ── New Device Profile form ── -->` section
rules — so the in-body discipline is real; it's the top-of-file
orient that's absent.) Per `AGENTS.md:171`'s "prefer pointers unless
load-bearing," a one-liner is sufficient and a full map is not
required.

**Suggested direction.** Optional. For the two largest after
`definitions.html` — `migrate.html` (covered by DE-02) and
`devices.html` (518 LOC) — a one-line `{# Devices page — new-profile
form + per-device cards; testids per section #}` would match
`definitions.html`'s pattern. The smaller pages can stay as-is; this
is a "warrant one" judgement and most do not.

---

### DE-10 — `cli.py` / `demo.py` headers show `python …` invocation, against the project's own `py`-launcher guidance (NIT)

**Files:** `netcanon/cli.py:14`, `tools/demo.py:5`

**Claim.** Header usage examples invoke bare `python`, which the
project's own operational memory flags as the broken launcher on
Windows (resolves to the Store shim).

**Evidence.**
```
cli.py:14     python -m netcanon.cli sanitize ...
demo.py:5     python tools/demo.py                       # Default …
```
This is cosmetic and arguably correct for the POSIX `pip install`
audience the CLI header targets (`cli.py:16-18`), so I rate it a nit,
not a finding-with-teeth. Flagging only because DE owns "are the
header *examples* runnable as written," and on the project's primary
desktop platform (Windows) these are not.

**Suggested direction.** None required; if a maintainer wants
cross-platform copy-paste safety, note `py -m …` as the Windows
equivalent. Coordinate with DA, who owns operator-facing runnability
of quickstart commands generally.

---

### DE-11 — Minor: `_mock` certainty `experimental` is not a documented tier alongside certified/best_effort (NIT)

**File:** `netcanon/migration/codecs/_mock/codec.py:44`

**Claim.** The mock declares `certainty = "experimental"` — a third
value the real codecs never use (they use `certified` / `best_effort`).
The `_mock/__init__.py` header (correctly) makes no certainty claim, so
there's no header drift; I note it only because the certainty
vocabulary across the corpus is `certified | best_effort |
experimental` and nothing in a header enumerates that the third value
exists or that it is test-scaffold-only.

**Evidence.**
```
_mock/codec.py:44   certainty: ClassVar[str] = "experimental"
```
The mock's header is otherwise model-correct — it explicitly says
*"Not wired to any real device."* (`_mock/codec.py:38`) and
*"No vendor semantics here"* (`_mock/__init__.py:11`).

**Suggested direction.** None at the header level. (If DD/DF maintain a
certainty-vocabulary glossary, `experimental` should appear there with
its "scaffold-only" meaning — but that's their lens.)

---

## 5. Consistency matrix — the 8 codec headers side-by-side

`✓` present as a labeled/dedicated block · `prose` woven into
narrative, not labeled · `—` absent · `ptr` = `_CAPS` pointer
(post-Commit-9 standard).

| Codec | `__init__` ordinal | `__init__` Scope→`_CAPS` ptr | `__init__` Direction | `__init__` Certainty | Cert. matches ClassVar? | `codec.py` "see `__init__`" | `codec.py` Module-layout |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| `cisco_iosxe` (NETCONF) | "first" (word) | ✓ (`:13`) | ✓ `:23` | ✓ `:24` | ✓ both `best_effort` | — (single-file) | — (single-file)¹ |
| `cisco_iosxe_cli` | **— (none)** | ✓ ref-template | ✓ `:10` | ✓ `:11` | ✓ `certified` | n/a² | ✓ `:7` |
| `opnsense` | "second" (word) +Phase1 | ✓ (`:15`) | **—** | **—** | n/a (no hdr claim)³ | ✓ `:4` | ✓ `:6` |
| `mikrotik_routeros` | "third" (word) | ✓ (`:12`) | prose | ✓ `:28` | ✓ `certified` | n/a² | ✓ `:5` |
| `aruba_aoss` | "4th" (digit) | ✓ (`:19`) | prose | ✓ `:52` **stale** | **✗ hdr `best_effort` / code `certified`** | ✓ `:4` | ✓ `:6` |
| `fortigate_cli` | "5th" (digit) | ✓ (`:10`) | prose | ✓ `:43` | ✓ `certified` | ✓ `:4` | ✓ `:6` |
| `arista_eos` | "6th" (digit) | ✓ (`:26`) | ✓ `:32` | ✓ `:33` | ✓ `certified` | ✓ `:4` | ✓ `:6` |
| `juniper_junos` | "7th" (digit) | (grammar list, not `_CAPS`)⁴ | ✓ `:14` | **—** (ClassVar only) | ✓ `certified` (code `:83`) | ✓ `:4` | ✓ `:6` |

¹ Single-file codec — no parse/render siblings, so no Module-layout
block; flagged DE-05 for not *saying* so.
² The NETCONF/CLI/MikroTik/OPNsense headers either don't open with the
"see `__init__`" clause or are single-file; `codec.py` Module-layout
present where a split exists.
³ OPNsense states Direction/Certainty only as ClassVars
(`opnsense/codec.py:84-85`), not in any header — DE-04.
⁴ Junos `__init__.py` keeps an explicit `Supported grammar (Tier 1 +
Tier 2):` enumeration (`:20-55`) rather than a `_CAPS` pointer. This is
arguably *load-bearing* (the grammar list documents the exact `set …`
forms accepted and is genuinely educational), so it is defensible under
`AGENTS.md:171`'s "unless the enumeration carries load-bearing
explanation" clause — but it makes Junos the one codec that did not
adopt the pointer pattern. Noting for completeness, not flagging as a
defect.

**Reading of the matrix.** The post-audit *Scope→`_CAPS` pointer*
conversion is uniform across the six codecs it targeted (all `✓ ptr`);
Commit 9 did its job and I am not re-flagging it. The *Module-layout*
block is present in every split codec. The drift is concentrated in
two columns: **ordinal style** (word vs digit, one missing — DE-03)
and **Direction/Certainty labeling** (3 of 8 have the clean pair;
OPNsense has neither header line, Junos lacks Certainty — DE-04). The
one **correctness** defect is the Aruba certainty contradiction
(DE-01).

---

## 6. What's GOOD

Worth recording, because the defaults here are better than most
codebases and the review should not read as net-negative:

* **100% module-header coverage.** Every Python module opened — codec,
  platform, desktop, tools, entry point — leads with a triple-quoted
  orientation docstring. There are no header-less modules.
* **The platform god-files are textbook orientation headers.**
  `services/migration_pipeline.py:1-55` states "this module is THE
  migration orchestrator," names every binding caller, and enumerates
  the three frozen public functions with per-function intent;
  `api/routes/ui.py:1-13` explains *why* the routes were extracted from
  `main.py` and that they are `include_in_schema=False`;
  `models/migration.py:1-14` defines the ok/warn/block severity
  convention up front; `migration/canonical/intent.py:1-71` lays out
  the four design principles and the Tier-1/2/3 taxonomy — exactly the
  orientation a newcomer to the IR needs. None of these is an
  enumeration that will rot (they describe *intent*, per
  `AGENTS.md:166`).
* **The desktop shell is uniformly well-headed.** `app.py:1-30` carries
  ASCII startup/shutdown sequence diagrams; `server.py`,
  `tray.py`, `single_instance.py`, `__main__.py`, and the package
  `__init__.py` each open with role + design-notes blocks. Cross-platform
  caveats (Windows-only mutex, MessageBox-not-traceback) are stated in
  the headers, not buried.
* **`_partials/*.js` fragments document their coupling.** Each opens
  with a `/* ── Title ── */` block that lists the *module-scope state
  it depends on from the parent IIFE* (e.g.
  `rename-table.js:1-20` enumerates `_lastJob`, `_renameUserMap`,
  `_renameProfiles`, …). For included view fragments that share scope
  with their host, this is precisely the right orientation and is rare
  to see done well.
* **The "prefer pointers" rule is real and largely followed.** The
  Scope→`_CAPS` conversion (Commit 9) is consistent across all six
  targeted codecs; the codec corpus has clear reference templates
  (`cisco_iosxe_cli` for `__init__`, the split `codec.py` skeleton) and
  most files conform.
* **No copy-paste header bleed.** Every codec header names its *own*
  vendor/class throughout — I cross-checked vendor names, class names,
  and the `Module layout` sibling-file lists against the actual files
  on disk for all 8. The prior-session "header naming the wrong codec"
  artifact class appears genuinely closed; I found zero instances.
* **License convention is coherent.** Root `LICENSE` + fixture
  `NOTICE.md`, zero per-file SPDX/copyright banners. The one
  `Copyright (c)` string is fixture payload
  (`tests/unit/test_probe_parser.py:25`), not a stray header. This is a
  deliberate, uniformly-applied choice.

---

## 7. Coverage table

| Surface | Files examined | Header present | Notes |
|---|---|---|---|
| Codec `__init__.py` (real) | 8 | 8/8 | DE-01/03/04/07 |
| Codec `__init__.py` (`_mock`) | 1 | 1/1 | model-correct; DE-11 (vocab nit) |
| Codec `codec.py` (real) | 8 | 8/8 | DE-05 (NETCONF outlier), DE-08 |
| Codec `codec.py` (`_mock`) | 1 | 1/1 | good |
| Platform god-files | 4 | 4/4 | exemplary (`ui.py`, `models/migration.py`, `migration_pipeline.py`, `intent.py`) |
| Other large platform | 3 | 3/3 | `api/routes/migration.py`, `canonical/port_names.py`, `target_profiles.py` — all strong |
| Entry points | 2 | 2/2 | `main.py`, `cli.py` good; DE-10 (nit) |
| `tools/*.py` (repo root) | 4 | 4/4 | DE-06 (shebang split) |
| `netcanon/tools/*.py` | 2 | 2/2 | `sanitize.py`, `__init__.py` — both good |
| `netcanon_desktop/*.py` | 11 (heads) | 11/11 | uniformly well-headed |
| Templates (page) | 10 | 1 contents-map / 9 bare | only `definitions.html` has a structural map; DE-02, DE-09 |
| Templates (`_partials/*.js`) | 13 (3 read in full) | high quality | document IIFE-scope deps |
| `base.html` | 1 | inline-commented | FOUC boot script well-explained (`:7-12`); no top-of-file map (acceptable for a layout shell) |
| License / SPDX | whole tree | root `LICENSE` | no per-file banners (deliberate) |
| Shebangs | whole tree | 2 files | DE-06 |

Total Python modules whose header I read: **~40** spanning every
layer. Header-presence rate: **100%**. Defect rate (header asserts
something false): **1** (DE-01). Everything else is consistency or
style.

---

## 8. Open questions

1. **Is the labeled `Direction:` / `Certainty:` pair *meant* to be a
   header standard?** The reference template (`cisco_iosxe_cli`) and
   three others carry it; four do not. If yes, DE-04 is a clear
   cleanup; if the ClassVars are considered the single source of truth
   and the header lines are optional, then DE-04 downgrades to "nice to
   have" and DE-01 narrows to "fix the stale claim, or delete the
   header line entirely." A maintainer ruling would settle several
   findings at once.

2. **Should `AGENTS.md:171` be re-pointed?** The rule names
   "migrate.html header comment" as the contents-map exemplar, but
   `definitions.html` is the file with the proper top-of-file map and
   migrate.html's map is a buried scripts-block partials list (DE-02).
   This is half-DE, half-DF (AGENTS.md ownership) — flagging the
   overlap so it isn't dropped between lenses.

3. **Are the "Nth codec" ordinals load-bearing or vestigial?** They
   read as historical narrative ("6th shipped codec, first DC-switching
   specialist"). If vestigial, normalising *or deleting* them resolves
   DE-03; if a maintainer values the shipping-order story, normalise
   the style and number the 8th codec. Not a correctness issue either
   way.

4. **Phase-N vocabulary half-life.** `AGENTS.md:166` already warns
   phase language rots. Two header instances remain (DE-07 OPNsense
   line 2; DE-08 cisco_iosxe NETCONF line 68), plus a large body of
   `Phase 0.5 stub` *reason-string* text in `cisco_iosxe/codec.py`
   (DD's lens). Worth a maintainer decision on whether "Phase 0.5" is
   retired wholesale in favour of "NETCONF stub / `best_effort`."

5. **Does any other codec's certainty header silently drift?** I
   verified all 8 header certainty claims against their ClassVars and
   found exactly one mismatch (Aruba, DE-01). But the *mechanism* that
   let it drift — promoting the ClassVar without touching the
   `__init__` header — has no guard. A one-line invariant test
   (`assert <header certainty> == Codec.certainty`, or simply asserting
   the header doesn't say `best_effort` when the ClassVar says
   `certified`) would prevent recurrence; this echoes the
   ship-before-wire two-sided-invariant pattern already used elsewhere
   in the test suite. (Spawned as a follow-up task.)

---

*End of investigation DE. All claims grounded in `file:line` at HEAD
`b08040c`. Read-only; no tracked file modified.*
