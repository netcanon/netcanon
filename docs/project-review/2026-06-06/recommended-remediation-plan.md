# Recommended remediation plan — 2026-06-06 review

A **sequenced plan, not an execution.** This review was read-only; no
project file was modified. Batches are ordered by leverage and grouped
so each could land as one commit (mirroring the docs-audit fix-plan
shape). Severities + anchors are in `findings-register.md`.

Two batches change CODE (security + small fixes) and require test runs;
the rest are docs/structure. Nothing here is started — the maintainer
decides what to take.

---

## Batch 1 — P1: close the security leak + fix the broken demo  ⚠ CODE
*Highest leverage. Do these two first; they're the only operator-visible P1s.*

**1a — Sanitiser secret-redaction gap (R-01, R-16, security).**
- Add a redaction rule covering `CanonicalInterface.vrrp_groups[].authentication` (strip/replace the `plain:` / `carp-key:` / `md5:` value) in `tools/sanitize.py`'s `sanitize_intent` walk + `_SubstitutionTable`.
- In the same pass, decide scope for the PII/network tail (R-16): `snmp.contact`, VLAN-SVI IPv4, RADIUS/trap/DHCP hosts.
- Sync the docs the AGENTS.md redaction-category row demands: `SECURITY.md` § Sanitiser table + § Known limitations, `BUG_REPORTING.md` "what gets sanitised".
- **Add the structural guard:** a test asserting *every* secret-bearing canonical field has a redaction rule (prevents the whole class — would have caught this).
- Verify: `py -m pytest tests/unit -k sanitize -p no:cacheprovider`.

**1b — `tools/` ships in nothing (R-02).** Pick one:
- *Ship it:* add `tools` to `pyproject.toml` packages (or move `demo.py` under `netcanon/`), `COPY tools/ ./tools/` in the Dockerfile builder+runtime, and add a `docker-build-smoke` step that actually runs the demo; **or**
- *Reword it:* change the README hero command + `tools/demo.py:14-15` docstring to a source-checkout instruction and stop implying it works from the published image/wheel.
- Verify: build the wheel (`py -m build`) and confirm `tools/` presence matches the chosen path.

> Batch 1 is the natural candidate for a **v0.1.3 security/packaging
> point release** (the user already earmarked v0.1.3 for OS additions —
> these could ride along or precede them).

---

## Batch 2 — P2 code: the cheap, high-confidence fixes  ⚠ CODE
*Small diffs, each independently testable.*

- **R-03 — Junos `TypeError` → `RenderError`.** One line in `juniper_junos/render.py:105` + `Raises:` docstring + flip any `pytest.raises(TypeError)`. (A task chip already tracks this; quadruple-confirmed.)
- **R-04 — sanitize route off the event loop.** `run_in_threadpool` around the blocking call in `api/routes/sanitize.py:42` (or make it sync `def`).
- **R-11 + R-05-guard — invariant guard tests.** Add the `inspect.signature` freeze-guard for the 3 pipeline functions (R-11) AND a header-`certainty`-vs-ClassVar equality test (the R-05 class). Cheap CI insurance matching the existing `_WIRED_UP_BY_CODEC` taste.
- Verify: `py -m pytest tests/unit/migration tests/unit/api -p no:cacheprovider`.

---

## Batch 3 — P2 docs: matrix-honesty + currency catch-up
*No code; the doc-sync the project's own discipline asks for.*

- **R-05 — Aruba `best_effort`→`certified` header** (`aruba_aoss/__init__.py:52`). (The guard test lands in Batch 2.)
- **R-06 — capability over-claims.** Soften `CAPABILITIES.md:54-61` Tier-1 summary to match the honest per-codec tables; fix `vendors/fortigate.md:33-36` MTU claim; add `mtu` to FortiGate `_CAPS`.
- **R-07 — `RESULTS.md` self-contradiction** (`:639` "10/five codecs" → 17/7).
- **R-09 + R-10 — meta-doc currency.** Add `ARCHITECTURE.md` `security/` section + `_tier3_detection.py` to the cross-cutting list; fix the false self-claim at `AGENTS.md:192`; swap the drifted `AGENTS.md:186` line-ref for an anchor.

---

## Batch 4 — P2: regen generated artifacts + the ui.py split
- **R-08 — regenerate** `CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md` from the 45-fixture corpus (`tools/run_full_mesh.py --matrix` → `tools/run_phase4_reconciliation.py`); commit as a clean "regen" diff per the AGENTS.md row.
- **R-12 — `api/routes/ui.py` → `api/routes/docs.py`** split at the line-447 seam (the `/docs` Swagger reskin). Behaviour-preserving; verify the `/docs` page + nav still render (Claude-in-Chrome or e2e).

---

## Batch 5 — P3 hygiene sweep (batch the cheap ones)
*One or two commits; low risk, clears the tail.*

- **Docstring de-stale:** R-14 (intent.py VRRP/anycast → "wired Wave B/C" + OPNsense `_CAPS` de-dup), R-15 (Phase-0/libyang framing).
- **Doc structure:** R-22 (per-pane 4→5), R-23 (migrate.html contents map / repoint exemplar), R-24 (codec header uniformity), R-25 (tests/README upward See-also), R-26 (nxos planning links), R-27 (orphan sub-READMEs), R-28 (dangling `slow` marker snippet).
- **Codec fidelity (schedule with codec work):** R-13 (is_secondary asymmetry + dead regex), R-17 (`PortIdentity.original`), R-21 (NETCONF port-name banner).
- **Opportunistic structure:** R-18 (backup→`services/`), R-19 (matrix types placement), R-20 (file_store decode bijection).

---

## Batch 6 — optional refactors (WATCH, not urgent)
- **R-29 / R-30** — continue `migrate.html` partial-extraction; extract Junos `render_intent` along its 14 banner seams. Both earned-size today; do only if the files become change-hotspots.

---

## The one structural recommendation worth elevating

Across CD-03, DE-01, and the sanitiser gap, the pattern is **documented
invariants without mechanical enforcement.** Batches 1–2 already add the
three guard tests (sanitiser-coverage, signature-freeze, header-vs-
ClassVar). Adopting "every documented invariant gets a guard test" as a
standing rule — the way `_WIRED_UP_BY_CODEC` already works — is the
highest-leverage durable outcome of this review. Consider an AGENTS.md
Hard-Rule row to that effect.

## Sequencing summary

| Batch | Theme | Code? | Gate |
|-------|-------|-------|------|
| 1 | P1 security + packaging | ✅ | sanitize tests + wheel build; candidate v0.1.3 |
| 2 | P2 cheap code fixes + guard tests | ✅ | unit (migration+api) |
| 3 | P2 docs matrix-honesty/currency | — | link/anchor check |
| 4 | regen artifacts + ui.py split | mixed | regen diff + /docs render |
| 5 | P3 hygiene sweep | mixed | unit if codec-touching |
| 6 | optional refactors | ✅ | full unit + visual |

## Reminder
**This dossier is read-only and currently uncommitted.** Nothing above
has been done. Commit the dossier (evidence trail, per the prior cycles'
pattern) whenever you're ready; execute batches at your discretion.

## See also
- [`99-synthesis.md`](99-synthesis.md) · [`findings-register.md`](findings-register.md)
- [`docs-review/99-docs-synthesis.md`](docs-review/99-docs-synthesis.md) · [`code-review/99-code-synthesis.md`](code-review/99-code-synthesis.md)
- [`docs/docs-audit/2026-05-21/fix-plan.md`](../../docs-audit/2026-05-21/fix-plan.md) — the prior cycle's execution model
