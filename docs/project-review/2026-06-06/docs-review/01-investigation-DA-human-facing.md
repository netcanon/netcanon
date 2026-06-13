# 01 — Investigation DA: Human / Operator-Facing Documentation Accuracy

**Reviewer lens:** DA (operator/human-facing docs accuracy)
**Commit:** `b08040c` (v0.1.2)
**Mode:** READ-ONLY. No tracked file mutated. Only this output file written.
**Date:** 2026-06-06

---

## 1. Scope & method

### Files owned by this lens (all read in full unless noted)

* `README.md` — read in full.
* `docs/CAPABILITIES.md` — read in full (the operator-facing source of truth).
* `docs/TROUBLESHOOTING.md` — read in full.
* `docs/COMPARISON.md` — read in full.
* `docs/HOW_WE_TEST.md` — read in full.
* `docs/glossary.md` — read in full.
* `docs/IDENTITY.md` — read in full.
* `docs/vendors/README.md` + all 7 per-vendor pages
  (`cisco_iosxe.md`, `juniper_junos.md`, `arista_eos.md`,
  `aruba_aoss.md`, `fortigate.md`, `mikrotik_routeros.md`,
  `opnsense.md`) — read in full.
* `docs/walkthroughs/README.md` + `cisco_iosxe_to_junos.md` — read in
  full; the other three walkthroughs spot-sampled via their shared
  format (deferred to coverage table).
* `BUG_REPORTING.md` — read in full.
* Operator-facing sections of `SECURITY.md` — § "Credential Storage",
  § "Sanitiser", § "Supply-Chain Integrity / Distribution channels",
  § "Known Limitations" (headers + key rows read).

### Cross-check sources (read to ground claims, not owned)

* `docs/docs-audit/2026-05-21/fix-plan.md` — to avoid re-flagging
  closed items (its 17-commit closure list was honoured; I confirmed
  several of its fixes actually landed, e.g. `cisco_iosxe.md:13`
  "parse + render bidirectional", README Python-version list,
  `aruba_aoss.md` 2530/YA hedge).
* `AGENTS.md` § Documentation Sync Checklist + Hard Rules — the
  matrix-honesty and "never ship a user-facing change without
  updating operator docs" rules are the yardstick for several
  findings.
* `pyproject.toml` (packaging config), `Dockerfile`,
  `.github/workflows/ci.yml`, `.github/workflows/docker-publish.yml`
  — to verify install/Docker/pip runnability claims.
* `tools/demo.py` — SCENARIOS dict + module docstring.
* Codec source `_CAPS` declarations, spot-sampled:
  `cisco_iosxe_cli/codec.py` (full `_CAPS` read), `cisco_iosxe/codec.py`,
  `opnsense/codec.py`, `fortigate_cli/codec.py` (+ `parse.py`/`render.py`
  MTU paths), to verify capability claims against actual code.
* `netcanon/tools/sanitize.py` (module docstring + IP-redaction logic)
  to verify the BUG_REPORTING sanitiser claims.
* `tests/fixtures/real/RESULTS.md` Summary table for certification
  cross-check.

### Sampling strategy

The capability-claim universe is large (8 codecs × dozens of xpaths).
I did **deep verification on one codec end-to-end** (`cisco_iosxe_cli`
— read the entire `_CAPS`) plus **targeted spot-checks** where a doc
claim looked falsifiable (FortiGate MTU/tunnel_type;
`unsupported_rename_categories`; the Docker demo command; the
sanitiser IPv6 claim; the Python matrix). The matrix-honesty spot-check
surfaced one real over-claim (DA-03) and one real under-claim (DA-02),
which is roughly the hit-rate you'd want from a sampling pass — enough
signal to recommend a fuller per-codec matrix-vs-`_CAPS` diff as
follow-up, not enough to call the corpus systematically wrong.

---

## 2. Executive summary

* **The flagship "See it in 10 seconds" Docker command in the README
  does not run against the published image.** `tools/demo.py` is not
  packaged into the wheel and not copied into the Docker image, so the
  headline on-ramp command fails with a file-not-found. This is the
  single highest-impact operator-facing defect and nothing in CI
  catches it. (DA-01, **P1**)
* **A handful of capability claims drift from the codecs.** The
  FortiGate vendor page says per-interface MTU is *not* emitted on
  render, but the renderer emits it (`render.py:632-637`); and
  CAPABILITIES.md's Tier-1 blanket "every shipped bidirectional codec
  parses and renders [these] fully" over-claims for `tunnel_type`
  (declared *lossy* on FortiGate) and `mtu` (matrix-silent on
  FortiGate). (DA-02 under-claim **P2**, DA-03 over-claim **P2**)
* **The matrix-honesty story is otherwise strong and well-grounded.**
  The `cisco_iosxe_cli` `_CAPS` matches CAPABILITIES.md path-for-path;
  the `unsupported_rename_categories` claim (only NETCONF + OPNsense
  declare `{"snmpv3"}`) is exactly right; the supply-chain /
  credential-storage claims line up with the workflows and SECURITY.md.
* **Minor stale-version and presentation residue.** BUG_REPORTING.md
  pins an IPv6 limitation "at v0.1.0" (substance still true, version
  stale); the README "Paste this / Get this" framing implies the demo
  accepts pasted input when it runs an embedded config. (DA-04, DA-05,
  P3/OBSERVATION)
* **The per-vendor pages and walkthroughs are exemplary** — richly
  cross-referenced, honest about Tier-3 deferral, and current to the
  v0.2.0 VRRP/anycast wave. Worth propagating as a model. (§4)
* **No dead operator-facing links found** in the sampled set; the
  "See also" reciprocity in the operator docs is consistently present
  (DB owns the full link-graph proof).

---

## 3. Findings

Ordered by severity. Severity scale per the project-review README
(P0 = ship-blocker / actively misleading on safety; P1 = materially
wrong, high-traffic surface; P2 = wrong but bounded / disclosed
elsewhere; P3 = stale/cosmetic; OBSERVATION = note, not a defect).

---

### DA-01 — README "See it in 10 seconds" Docker command is not runnable (`tools/demo.py` absent from the published image and wheel)

* **Severity:** P1
* **Anchor:** `README.md:23-24` (and the reinforcing
  `tools/demo.py:14-15` docstring claim)
* **The claim:**

  > ## See it in 10 seconds
  > ```bash
  > docker run --rm ghcr.io/netcanon/netcanon:latest python tools/demo.py --pair cisco__junos
  > ```

  This is the **first runnable command in the README**, presented as
  the zero-friction on-ramp ("See it in 10 seconds").

* **Evidence:** the file `tools/demo.py` is not shipped in either the
  Docker image or the pip wheel:
  * `pyproject.toml:122-124` packages only `netcanon*` and
    `netcanon_desktop*`:
    ```toml
    [tool.setuptools.packages.find]
    where = ["."]
    include = ["netcanon*", "netcanon_desktop*"]
    ```
    `tools/` is a top-level sibling, not a package — it is **not** in
    the wheel. `pip install netcanon` does not lay down `tools/demo.py`.
  * `Dockerfile:35-36` (builder) copies only metadata + `netcanon/`:
    ```dockerfile
    COPY pyproject.toml README.md LICENSE ./
    COPY netcanon/ ./netcanon/
    ```
    and `Dockerfile:69` (runtime) copies only `definitions/`. The
    runtime stage installs the wheel from `/wheels`. **`tools/` never
    enters the image.** Running the README command yields, in effect,
    `python: can't open file '//tools/demo.py': [Errno 2] No such file
    or directory`.
  * `tools/demo.py:14-15` compounds the problem by telling operators:
    > Drop into a Python 3.11+ env with `pip install netcanon` and run.

    — but a pip-installed `netcanon` does not include `tools/demo.py`,
    so this instruction is also wrong for the pip path.
  * CI does **not** catch it: `.github/workflows/ci.yml:98-157`
    (`docker-build-smoke`) boots the image and curls `/health` + `/`,
    but never invokes `tools/demo.py`. So the regression is invisible
    to the green suite.

  The script itself is fine — `tools/demo.py:28-29` imports only
  `netcanon.migration.codecs.registry` and
  `netcanon.services.migration_pipeline`, both of which ARE in the
  wheel. So the demo runs perfectly from a **source checkout**
  (`git clone` → `python tools/demo.py …`), which is the contributor
  path the walkthroughs assume. The defect is specifically that the
  README sells the *Docker* (and the docstring sells the *pip*) path,
  and those two distribution artifacts don't carry the file.

* **Why it matters:** this is the project's marketing-surface
  first impression and the literal "10 seconds to value" promise. An
  evaluating operator who copy-pastes it gets an error, not a
  translation. It also undercuts the matrix-honesty brand: the doc is
  confidently wrong about the most basic runnable claim.

* **Suggested direction (NOT a fix):** decide whether the demo should
  be reachable from the image/wheel or whether the README should point
  at the source-checkout path instead. Options the maintainer can
  weigh: (a) `COPY tools/ /app/tools/` in the Dockerfile runtime stage
  and ship `tools` as package-data or a console entry-point so it's
  importable post-pip; (b) reframe the README headline to the
  source-checkout invocation (`git clone … && python tools/demo.py …`)
  and fix the `tools/demo.py:14-15` docstring to match; (c) expose a
  `netcanon demo` CLI subcommand (the `netcanon` console script already
  exists per `pyproject.toml:94-95`) so the published artifacts have a
  first-class demo path. Whichever path, add a CI step that actually
  runs the demo inside the built image so this can't silently rot
  again — the `docker-build-smoke` job is the natural home.

---

### DA-02 — FortiGate vendor page says per-interface MTU is not emitted on render; the renderer emits it

* **Severity:** P2
* **Anchor:** `docs/vendors/fortigate.md:33-36`
* **The claim:**

  > **Note:** per-interface MTU is parsed when FortiGate is the
  > *source* (carried into the canonical model and rendered by other
  > target codecs that emit MTU) but **not emitted when FortiGate is
  > the *target*** — see codec capability matrix.

* **Evidence:** the FortiGate renderer DOES emit MTU when FortiGate is
  the target. `netcanon/migration/codecs/fortigate_cli/render.py:632-637`:
  ```python
  if iface.mtu is not None:
      # FortiOS requires mtu-override enable before
      # set mtu has effect on physical ports.  Emit
      # both so the config is deployable.
      out.append("        set mtu-override enable")
      out.append(f"        set mtu {iface.mtu}")
  ```
  The render module docstring at `render.py:22-25` only says *default*
  MTU (`set mtu 1500`) is suppressed for round-trip cleanliness — not
  that all MTU is dropped:

  > Defaults that FortiOS omits on export (e.g. `set radius-port 1812`,
  > `set mtu 1500`) are NOT emitted here so our renders round-trip
  > against real exports …

  So a non-default MTU (say 9216) from a cross-vendor source **is**
  emitted on render-into-FortiGate. The vendor page's "not emitted
  when FortiGate is the target" is therefore inaccurate (an
  under-claim — it tells operators a working capability doesn't work).

* **Compounding:** the page says "see codec capability matrix," but
  `/interfaces/interface/config/mtu` is **absent** from FortiGate's
  `_CAPS` entirely — it is in neither `supported`, `lossy`, nor
  `unsupported` (`fortigate_cli/codec.py:114-300`). So the matrix
  neither confirms nor denies; the page points operators at a doc that
  is silent on the field. (That matrix gap is more Fleet-C's lens, but
  it's why the operator-facing claim can't self-correct.)

* **Suggested direction:** reconcile the page with the code — either
  state that explicit (non-default) MTU IS rendered while FortiOS
  defaults are omitted, or, if the product intent is genuinely "don't
  emit MTU on FortiGate," change the renderer. Whichever way the truth
  resolves, declaring `/interfaces/interface/config/mtu` explicitly in
  FortiGate's `_CAPS` (as `supported` or `lossy`) would let the page
  point at a matrix that actually backs the claim, restoring the
  "no silent gap" property the matrix-honesty discipline promises.

---

### DA-03 — CAPABILITIES.md Tier-1 blanket "every shipped bidirectional codec parses and renders [these] fully" over-claims for `tunnel_type` and `mtu`

* **Severity:** P2
* **Anchor:** `docs/CAPABILITIES.md:54-61`
* **The claim:**

  > ### Tier 1 — auto-translatable (cross-vendor stable)
  > Fully modelled; every shipped bidirectional codec parses and renders:
  > * `interfaces` — `name`, `description`, `enabled`, IPv4 + IPv6
  >   addresses, `vrf` binding, `kind` …, `mtu`, `lag_member_of`,
  >   `dhcp_client_v6` …, `tunnel_type` (GRE / EoIP / IPIP / IPSEC /
  >   VXLAN encap discriminator)

  The header sentence asserts **every** bidirectional codec parses AND
  renders **all** the listed interface sub-fields fully.

* **Evidence:** at least one listed Tier-1 field is declared **lossy**
  on a shipped codec, contradicting "renders … fully":
  * `tunnel_type` is `lossy` on FortiGate —
    `fortigate_cli/codec.py:172-182`:
    ```python
    LossyPath(
        path="/interfaces/interface/tunnel-type",
        reason=("FortiOS expresses tunnels in separate top-level "
                "sections … tunnel_type does not survive "
                "render-into-FortiGate."),
        severity="warn",
    ),
    ```
  * `mtu` is matrix-silent on FortiGate (see DA-02) — emitted by code
    but undeclared.

  The list mixes genuinely-universal Tier-1 fields (hostname, name,
  description, enabled, IPv4 address) with fields that are
  per-codec-conditional (`tunnel_type`, `mtu`, and arguably `kind`
  inference). The blanket "every codec … fully" sentence is the
  trust-load-bearing claim of the document (HOW_WE_TEST.md and the
  README both lean on it), so an over-claim here is more consequential
  than the same words in a less central doc.

* **Note on internal consistency:** the per-codec matrix *below* in
  the same file is honest (it doesn't list FortiGate `tunnel_type` as
  supported), and the FortiGate vendor page partially discloses the
  nuance (`fortigate.md:30-31` flags `tunnel_type` deferral). So the
  drift is localised to the **summary sentence**, not the detailed
  tables — which is exactly the class of over-claim AGENTS.md's
  matrix-honesty Hard Rule (`AGENTS.md:295-304`) is meant to prevent.

* **Suggested direction:** soften the Tier-1 header to scope the
  "fully" claim to the fields that are genuinely universal, and split
  out the conditionally-rendered fields (`tunnel_type`, `mtu`) with a
  per-field "see matrix for codecs where this is lossy" caveat — the
  way `static_routes[].vrf` is already caveated two bullets down
  (`CAPABILITIES.md:64-66`). The pattern already exists in the doc;
  it just isn't applied to these two interface sub-fields.

---

### DA-04 — BUG_REPORTING.md pins the IPv6-redaction limitation "at v0.1.0" (stale version anchor; substance still correct)

* **Severity:** P3
* **Anchor:** `BUG_REPORTING.md:163`
* **The claim:**

  > * **IPv6-public redaction is IPv4-only at v0.1.0.**  IPv6 addresses
  >   pass through verbatim.  If your config has public IPv6 addresses,
  >   hand-redact those before submitting.

* **Evidence:** the *substance* is still accurate at v0.1.2 — the
  sanitiser only handles `IPv4Address`
  (`netcanon/tools/sanitize.py:413`, `:445` both use
  `ipaddress.IPv4Address(...)`; there is no `IPv6Address` redaction
  path). So IPv6 still passes through. But the version anchor "at
  v0.1.0" is stale: HEAD is v0.1.2 and the limitation is unchanged, so
  the phrasing reads as if it might have been fixed since. Per the
  snapshot (`00-snapshot.md`) and the docs-review baseline, "accurate
  to current state" means HEAD/v0.1.2; a frozen "at v0.1.0" version
  string in operator prose is exactly the stale-version class flagged
  in `00-docs-scope.md`.

* **Cross-cutting note (DD's lens, flagged lightly):** the
  `sanitize.py` module docstring "Limitations" block
  (`sanitize.py:42-53`) does **not** list the IPv6-passthrough
  limitation that BUG_REPORTING.md surfaces — so the operator doc is
  *more* complete than the code docstring here. Not a DA defect, but
  worth a DD glance.

* **Suggested direction:** drop the version anchor ("IPv6-public
  redaction is not yet implemented — IPv6 addresses pass through
  verbatim…") so the statement stays true regardless of release, or
  re-anchor to the current behaviour without a version. Optionally
  mirror the limitation into the `sanitize.py` docstring for parity.

---

### DA-05 — README "See it in 10 seconds" framing implies the demo accepts pasted input; the demo runs an embedded config

* **Severity:** OBSERVATION (borderline P3)
* **Anchor:** `README.md:24-49`
* **The claim:** the section runs `python tools/demo.py --pair
  cisco__junos` (line 24), then says **"Paste this:"** (line 27) with a
  config block, then **"Get this:"** (line 43) with rendered output —
  implying the operator pastes the shown config and the demo
  translates it.

* **Evidence:** `tools/demo.py` takes no stdin/paste — `--pair`
  selects a scenario whose `source_text` is a hard-coded embedded
  config (`tools/demo.py:164-211`; the `cisco__junos` scenario uses
  the module-level `_CISCO_IOSXE` constant, not operator input). The
  CLI only accepts `--pair` and `--list` (`tools/demo.py:306-312`).
  So "Paste this / Get this" is illustrative of *what the embedded
  scenario does*, not an input the operator supplies to that command.
  The shown output also doesn't fully match the demo's embedded config
  (the README block omits DNS/NTP lines that the demo's
  `cisco_iosxe_to_junos.md` sample output shows). It's a presentation
  ambiguity, not a falsehood — but combined with DA-01 (the command
  doesn't run in the image at all), the section reads more
  interactive than it is.

* **Suggested direction:** once DA-01 is resolved, either (a) clarify
  that the demo runs a built-in example (e.g. "This runs a built-in
  Cisco→Junos example and prints:") so "Paste this" becomes "It
  translates this:", or (b) if a paste path is desired, point at the
  `/sanitize`-style paste affordance or the web UI. Low urgency; fold
  into the DA-01 edit.

---

## 4. What's GOOD (worth propagating)

* **The per-vendor pages are a model of honest operator docs.** Each
  follows the documented 8-section shape (`docs/vendors/README.md:28-45`)
  and is current to the v0.2.0 VRRP/anycast wave. Standouts:
  * `docs/vendors/cisco_iosxe.md:46-131` — the L3-redundancy section
    walks classic VRRP *and* SD-Access anycast with exact grammar,
    canonical mapping, and a precise "modern AF form is lossy" caveat
    that I verified matches `cisco_iosxe_cli/codec.py:174-192`
    (`/interfaces/interface/vrrp-groups/group/address-family` lossy).
  * `docs/vendors/opnsense.md:42-122` — the CARP section's
    `advskew↔priority` inversion and "CARP-only on render" caveat
    match the codec's declared lossy behaviour and CAPABILITIES.md
    line 296-297 exactly.
  * `docs/vendors/fortigate.md:15-21,143-161` — the "most of a
    FortiGate config is Tier-3" framing is the right expectation-set
    for the vendor whose flagship surface Netcanon deliberately won't
    translate. (The MTU note, DA-02, is the one blemish.)
* **`docs/CAPABILITIES.md`'s per-codec matrix tables** (lines 159-307)
  are exhaustive and cite a reason per `lossy`/`unsupported` path. The
  `cisco_iosxe_cli` table matched its `_CAPS` path-for-path on my full
  read — supported VRRP + IPv4 anycast + anycast-mac, unsupported IPv6
  anycast + per-VRF static route, lossy modern-AF + routing-instances.
  This is the matrix-honesty discipline working as designed.
* **`docs/HOW_WE_TEST.md`** correctly refuses to hard-code the
  CODEC_BUG count, pointing instead at the machine-generated
  `PHASE4_RECONCILIATION.md` (lines 43-44, 52) — honouring the
  AGENTS.md "no hard-coded counts in prose" Hard Rule
  (`AGENTS.md:269-279`). Same discipline in `CAPABILITIES.md:594-596`.
* **`docs/COMPARISON.md`** is unusually honest for a positioning doc —
  it names what Netcanon *won't* do (firewall/NAT/VPN/QoS) and points
  operators at Capirca/Aerleon/Batfish rather than over-claiming
  (lines 74-84). Good trust signal.
* **The `unsupported_rename_categories` story is exactly right across
  three docs** (CAPABILITIES.md:419-421, glossary.md:69-75, and the
  codec source). I verified the only two declarers are
  `cisco_iosxe/codec.py:181-183` and `opnsense/codec.py:117-119`, both
  `{"snmpv3"}`, with `fortigate_cli/codec.py:98` explicitly empty and
  `base.py:204` defaulting empty. No drift.
* **Supply-chain + credential-storage claims line up with reality.**
  README's Docker quickstart (lines 85-127) matches the Dockerfile env
  (`NETCANON_DATA_DIR=/app/data`, auto-`.fernet_key`) and SECURITY.md's
  three-tier key resolution (`SECURITY.md:75-152`); the GHCR-signed /
  Docker-Hub-unsigned distinction matches `docker-publish.yml:155-193`
  (cosign keyless on `ghcr.io/*` only) and `IDENTITY.md:144-148`.
* **README Python-version matrix is current** — "3.11 / 3.12 / 3.13 /
  3.14" (README:277) matches `ci.yml:34` exactly, and the
  `pyproject.toml:43-46` classifiers. (This was a 2026-05-21 audit fix
  that landed cleanly.)

---

## 5. Coverage table

| Surface | Examined? | Notes |
|---|---|---|
| `README.md` | ✅ full | DA-01, DA-05 here. Install/pip/Docker/MSI claims verified against Dockerfile + pyproject + publish workflow. |
| `docs/CAPABILITIES.md` | ✅ full | DA-03. Per-codec tables spot-verified against `cisco_iosxe_cli` `_CAPS` (full match) + FortiGate (MTU/tunnel_type drift). |
| `docs/TROUBLESHOOTING.md` | ✅ full | No defects found; Tier-3/Lossy/CODEC_BUG flowchart is accurate; "Phase 4.5" wording already removed (2026-05-21 fix landed). |
| `docs/COMPARISON.md` | ✅ full | No defects. Adjacent-tool framing honest. |
| `docs/HOW_WE_TEST.md` | ✅ full | No defects. Count-free per Hard Rule. |
| `docs/glossary.md` | ✅ full | No defects. `unsupported_rename_categories` entry verified correct. The 2026-05-21 audit added the missing terms (M12). |
| `docs/IDENTITY.md` | ✅ full | No defects. Distribution surfaces table matches workflows. |
| `docs/vendors/*.md` (7 pages + README) | ✅ full | DA-02 (FortiGate MTU). Others verified against `_CAPS`/code where claims were falsifiable; high quality (§4). |
| `docs/walkthroughs/cisco_iosxe_to_junos.md` | ✅ full | No defects; demo command shares DA-01 (source-checkout-only) caveat but that's the README's framing, not the walkthrough's (walkthroughs correctly assume a checkout). |
| `docs/walkthroughs/{fortigate_to_mikrotik,aruba_to_arista,opnsense_to_junos}.md` | ⚠️ sampled | Format + demo-pairing verified via README table + demo SCENARIOS dict (all 4 keys exist). Per-line capability claims **deferred** — same structure as the cisco page; low marginal risk. A follow-up pass should read these three in full. |
| `BUG_REPORTING.md` | ✅ full | DA-04. Sanitiser 3-path claim + redaction table verified against `sanitize.py`. |
| `SECURITY.md` operator-facing § | ✅ targeted | Credential Storage / Sanitiser / Supply-Chain / Known-Limitations headers + key rows read. Operator-facing claims consistent with README + workflows. Full SECURITY.md prose-accuracy is a DF/security-lens concern. |
| Per-codec `_CAPS` vs CAPABILITIES.md, all 8 codecs | ⚠️ sampled | Deep-verified `cisco_iosxe_cli` (full); spot-checked FortiGate, NETCONF, OPNsense. **Deferred:** a full per-codec matrix-vs-`_CAPS` diff for arista/aruba/junos/mikrotik — recommended follow-up given DA-02/DA-03 both surfaced from the sampled codecs. |

---

## 6. Open questions / human-call-needed

1. **DA-01 product call:** should the demo be reachable from the
   published image/wheel, or should the README stop advertising the
   Docker/pip path for it? This is a product decision (ship `tools/`
   vs. reframe the docs vs. add a `netcanon demo` subcommand), not a
   mechanical doc fix. Whichever way, the broken headline command
   should not stand at v0.1.2.

2. **DA-02 truth-source:** is "FortiGate does not emit MTU on render"
   the *intended* behaviour (making `render.py:632-637` the bug) or is
   the rendering intended (making the vendor page the bug)? A
   maintainer who knows the product intent must pick which side moves.
   My read of the code says MTU *is* emitted, so the doc is wrong —
   but I flag the inverse possibility for completeness.

3. **DA-03 scope of the over-claim:** beyond `tunnel_type` and `mtu`,
   does `kind` (physical/mgmt/loopback/uplink inference) round-trip
   "fully" on every codec, or is it also inference-lossy on some? I
   did not exhaustively verify `kind` across all 8 codecs; the Tier-1
   "fully" sentence should be re-scoped only after that check, so the
   replacement wording is itself honest.

4. **Matrix-completeness vs. matrix-honesty (cross-lens):** the
   FortiGate MTU case shows a field that is *behaviourally* supported
   but *undeclared* in `_CAPS`. The glossary defines the matrix as
   "no silent unsupported — every gap is declared"
   (`glossary.md:54-57`). A behaviourally-supported-but-undeclared
   field is a different gap class (silent *support*, not silent
   *unsupport*), but it still dents the "every field is declared"
   promise. Worth a Fleet-C decision on whether `_CAPS` should
   enumerate every behaviourally-handled field.

---

*End of DA investigation. All findings grounded in `file:line` at
commit `b08040c`. Confidence: DA-01 high (verified across pyproject +
Dockerfile + CI); DA-02/DA-03 high (read the codec source directly);
DA-04/DA-05 high. No claims marked UNVERIFIED.*
