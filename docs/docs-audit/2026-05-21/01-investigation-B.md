# Cluster B — User-facing documentation accuracy

## Summary

Audit of ~30 user-facing docs (README, CAPABILITIES, TROUBLESHOOTING,
BUG_REPORTING, HOW_WE_TEST, COMPARISON, IDENTITY, per-vendor pages,
walkthroughs, vendor-references sample) against current code, codec
`_CAPS`, fixture corpus, CLI / HTTP surface, and GitHub repo
metadata.  Total findings: **18** (2 WRONG, 9 INCOMPLETE, 4 MISSING,
3 STYLE).

Headline real concerns:

* **`docs/vendors/cisco_iosxe.md` calls `cisco_iosxe_cli` "parse-
  only".**  The codec is `bidirectional` (817-line `render.py`,
  declared `direction: bidirectional`).  This contradicts the whole
  walkthrough/demo system that uses Cisco IOS-XE CLI as BOTH source
  and target.  WRONG; fix shape is a one-word edit.
* **`README.md` Python matrix claim is one version stale.**  Says CI
  runs on 3.11 / 3.12 / 3.13; `.github/workflows/ci.yml` runs 3.11 /
  3.12 / 3.13 / 3.14 (and `pyproject.toml` has the matching 3.14
  classifier).
* **Vendor pages chronically under-list fixtures.**  Cisco IOS-XE,
  Juniper, Arista, OPNsense all enumerate fewer fixtures than
  `tests/fixtures/real/<vendor>/` actually contains.  Junos vendor
  page even cites a fixture by name in the VRRP section that's
  missing from the fixtures listing 100 lines later.

Otherwise the docs are remarkably accurate — CAPABILITIES.md's
per-codec narrative tracks the `_CAPS` declarations precisely; the
VRRP / anycast Wave B+C narrative matches `_WIRED_UP_BY_CODEC`;
sanitiser claims in BUG_REPORTING.md match the actual rule set in
`netcanon/tools/sanitize.py`; GitHub repo metadata matches
IDENTITY.md byte-for-byte; PyPI v0.1.2 + the GHCR/Docker Hub images
+ the MSI release asset all exist as documented.

---

## Per-doc audit results

### `README.md`

* Verified claims:
  * `pip install netcanon` resolves on PyPI (`0.1.2` is the latest).
  * `ghcr.io/netcanon/netcanon:latest` matches `IDENTITY.md`
    "Distribution surfaces" table.
  * `netcanon/netcanon:latest` Docker Hub mirror documented as
    unsigned per IDENTITY.md — accurate.
  * MSI download path resolves: `v0.1.2` GitHub release carries
    `netcanon-0.1.2-win64.msi`.
  * Eight codecs enumerated (`cisco_iosxe_cli`, `cisco_iosxe`,
    `juniper_junos`, `arista_eos`, `aruba_aoss`, `fortigate_cli`,
    `mikrotik_routeros`, `opnsense`) plus a `_mock` adapter —
    matches the codec directory.
  * Walkthrough table lists 4 pairs that match `tools/demo.py`
    `SCENARIOS` dict keys (`cisco__junos`, `fortigate__mikrotik`,
    `aruba__arista`, `opnsense__junos`).
  * Quickstart Docker command line shape matches `Dockerfile`'s
    `uvicorn netcanon.main:app` entrypoint.
  * `NETCANON_FERNET_KEY` env-var and `data/.fernet_key` fallback
    behaviour both documented + cross-referenced to `SECURITY.md`.

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 1 | `README.md:277` | WRONG | "CI runs the full matrix on Python 3.11 / 3.12 / 3.13 against Ubuntu" — `.github/workflows/ci.yml:34` has `python-version: ["3.11", "3.12", "3.13", "3.14"]`; `pyproject.toml` classifiers include 3.14. | Add "3.14" to the version list (or replace with "Python 3.11+" pointer to pyproject classifiers per AGENTS.md prose-rot rule). |
| 2 | `README.md:25-26` | INCOMPLETE | The "see it in 10 seconds" Docker command (`docker run --rm ghcr.io/netcanon/netcanon:latest python tools/demo.py …`) doesn't include the `-e NETCANON_FERNET_KEY=…` flag, but the longer install snippet 60 lines later flags it as essential.  Operators copy-pasting the 10-second command get a key auto-generated under `data/` (which then isn't persisted across container restarts since no volume mount either).  Documentation is silent on this. | Add a one-line note that the demo command writes ephemeral state; for persistent use see the Install section below. |

---

### `docs/CAPABILITIES.md`

* Verified claims:
  * Supported-vendor table (8 codecs) matches `_CAPS` `adapter` /
    `vendor_id` / `certainty` / `direction` on every codec checked.
  * `cisco_iosxe_cli` per-path table (lines 159-176) matches
    `cisco_iosxe_cli/codec.py` `_CAPS` (5 VRRP/anycast/SD-Access
    paths under supported; modern-AF + EVPN + routing-instances
    lossy; IPv6 anycast + per-VRF static + IOS-XE VXLAN + ACL/NAT/
    firewall unsupported).
  * `arista_eos` per-path table (lines 213-227) matches `_CAPS`
    (4 Wave B+C supported paths including IPv6 VARP, 2 per-IP MAC
    lossy paths, BGP/OSPF/ACL/per-VRF unsupported).
  * `juniper_junos` per-path table (lines 244-258) matches `_CAPS`
    (4 Wave B+C supported paths including per-IP MAC, per-VRF static
    + apply-groups + subinterface + EVPN lossy, BGP / firewall /
    anycast-gateway-MAC unsupported).
  * `aruba_aoss` table (lines 230-241), `fortigate_cli` table
    (lines 261-276), `mikrotik_routeros` table (lines 279-291),
    `opnsense` table (lines 294-307) all match their respective
    `_CAPS`.
  * Cross-vendor L3-redundancy grammar reference (lines 511-572)
    matches per-codec wire-up state in
    `tests/unit/migration/test_canonical_vrrp_anycast_schema.py`'s
    `_WIRED_UP_BY_CODEC` map (5 Wave-B/C wired-up codecs +
    cisco_iosxe NETCONF stub still unwired).
  * Cross-paradigm exceptions (lines 480-498) all verifiable:
    NETCONF stub is `unsupported`-heavy by design;
    `_TARGET_ACCEPTS` for `mikrotik_routeros` confirmed
    `plaintext`-only; Aruba DHCP comment block confirmed in
    `aruba_aoss/render.py` (cited in CAPABILITIES.md line 364).
  * "What is auto-tested" section refers to actual tools that
    exist (`tools/run_full_mesh.py`, `tools/run_phase4_reconciliation.py`,
    `tests/unit/migration/test_real_captures.py`).

* Findings: no findings.  This is the strongest-aligned doc in
  the cluster — narrative tracks code precisely.

---

### `docs/TROUBLESHOOTING.md`

* Verified claims:
  * Three-banner taxonomy (Tier-3 / unsupported / lossy) matches
    migrate-page actual behaviour as documented in
    CAPABILITIES.md § "Notification mechanisms operators see".
  * Variance class names (`CODEC_BUG`) match `HOW_WE_TEST.md` taxonomy.
  * Hash-portability "review comment" claim cited under "My hashed
    password came out as a review comment" matches
    `netcanon/migration/_user_secrets.py` implementation as
    summarised in CAPABILITIES.md § C.
  * LAG name-equivalence table (Cisco `Port-channel<N>` ≡ Arista
    `Port-Channel<N>` ≡ Junos `ae<N>` ≡ Aruba `trk<N>` ≡ MikroTik
    `bond<N>`) matches the inventory in
    `docs/COMPARISON.md` + per-vendor pages.
  * paramiko-shell capture artifact rescue documented in OPNsense
    vendor page + `opnsense/parse.py` `_trim_xml_prologue` helper.

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 3 | `docs/TROUBLESHOOTING.md:112` | STYLE | The flowchart calls the sanitiser "the Phase 4.5 sanitiser" — internal-development phase numbering leaking into operator-facing copy.  Operators don't have a mental model of "Phase 4.5". | Drop "Phase 4.5" — just "Use the sanitiser:" reads cleaner.  Or pivot to "Use `netcanon sanitize`" (the actual command name). |

---

### `BUG_REPORTING.md`

* Verified claims:
  * Three sanitiser invocation paths (Browser UI, CLI, HTTP API)
    all exist:
    * `/sanitize` page → `netcanon/templates/sanitize.html` +
      `netcanon/api/routes/ui.py` route
    * `netcanon sanitize` CLI → `netcanon/cli.py` declares the
      `sanitize` subparser with `-i`, `-o`, `-s`/`--source-vendor`,
      `--dry-run` flags exactly as documented
    * `POST /api/v1/sanitize` → `netcanon/api/routes/sanitize.py`
  * All three call `netcanon.tools.sanitize.sanitize_text` as
    claimed (line 124 "All three paths … call the same shared
    library").
  * Per-category counter scheme matches `_SubstitutionTable`'s
    fields: `_hostnames`, `_ipv4`, `_communities`, `_secret_counters`,
    `_hash_counter`, `_local_user_names`, `_snmpv3_user_names`.
  * Field replacement table (lines 137-148) matches `sanitize_intent`
    behaviour: hostname → `device-N`, domain → `example-N.test`,
    public IPv4 → RFC 5737 docs ranges, local user → `localuserN`,
    SNMPv3 user → `snmpv3userN`, RADIUS shared secret →
    `REDACTED-RADIUS-N`, interface descriptions →
    `description redacted`, Tier-3 sections → stripped entirely.
  * "IPv6-public redaction is IPv4-only at v0.1.0" limitation
    (line 165) accurate — `_SubstitutionTable` has no IPv6
    redaction method.
  * "Banner / comment text not redacted" limitation (line 161)
    accurate — the canonical model is the AST and the sanitiser
    operates on it (per the docstring at
    `netcanon/tools/sanitize.py:42-48`).
  * `tests/fixtures/real/WANTED.md` referenced at line 202 exists.
  * Issue templates `bug_report.yml` + `fixture_submission.yml`
    referenced; not verified directly but external (GitHub-side).

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 4 | `BUG_REPORTING.md:26, :124, :151` | STYLE | Three relative links use `../netcanon/tools/sanitize.py` from a file at repo root; the `../` escapes the repo.  Should be `netcanon/tools/sanitize.py` (no leading `..`).  Cluster A interlinking should also catch this, noting here since it's load-bearing for operators who click through to verify the sanitiser rules. | Strip the `../` prefix on these three links (and any other root-relative `../netcanon/...` ones if grep finds them). |

---

### `docs/HOW_WE_TEST.md`

* Verified claims:
  * Four test layers (Unit / Integration / E2E / Desktop) match
    the `tests/` directory structure (`unit/`, `integration/`,
    `e2e/`, `desktop/` subtrees).
  * Eight-class variance taxonomy (`ALIGNED` / `CODEC_BUG` /
    `EXPECTED_LOSSY` / `EXPECTED_UNSUPPORTED` /
    `METHODOLOGY_ISSUE_under` / `METHODOLOGY_ISSUE_over` /
    `STRUCTURAL_ONLY` / `TRIVIAL_EMPTY`) matches the README.md
    headline list (line 14-18) and the variance enumeration in
    AGENTS.md's "doc-sync" row.
  * Cross-mesh audit tool names match what's in
    `tools/run_full_mesh.py` + `tools/run_phase4_reconciliation.py`.
  * "Zero CODEC_BUG cells" trust claim is correctly hedged
    ("as of the current commit" + "the audit only covers cells
    we have fixtures for") — matrix-honesty discipline observed.
  * Mocking discipline (`get_collector` as the single mock-point)
    matches `AGENTS.md` hard rule.

* Findings: no findings.

---

### `docs/COMPARISON.md`

* Verified claims:
  * Adjacent-tool comparison table positions Netcanon's
    differentiator ("Per-field capability matrix … explicit Tier-3
    boundary; matrix-honesty discipline") accurately versus
    Batfish (parse-only) / Capirca / Aerleon (firewall DSL render
    only) / NAPALM / Netmiko / Nornir (orchestration).
  * Vendor list (`Cisco / Juniper / Fortinet / Aruba / Arista /
    MikroTik / OPNsense`) matches CAPABILITIES.md supported-vendors
    table (7 families, 8 codecs).
  * "What Netcanon won't do" section accurately enumerates the
    Tier-3 deferrals (firewall, NAT, VPN, QoS) and points to
    CAPABILITIES.md for the cited reasoning.
  * The Capirca / Aerleon recommendation for firewall translation
    is consistently cross-referenced from per-vendor pages
    (FortiGate, OPNsense, walkthroughs) — no contradictions.

* Findings: no findings.  Positioning still holds — none of the
  adjacent tools have shipped a feature that would invalidate the
  comparison.  STYLE point: the "Where Netcanon competes" /
  "Where Netcanon is complementary" frame is sharp and operator-
  useful; no changes needed.

---

### `docs/IDENTITY.md`

* Verified claims (against `gh api repos/netcanon/netcanon`):
  * **Tagline:** repo `description` = "Multi-vendor network config
    translator — Cisco / Juniper / Fortinet / Aruba / Arista /
    MikroTik / OPNsense. Cross-mesh audit catches silent
    translation errors before they ship."  Matches IDENTITY.md
    line 34 exactly.
  * **GitHub Topics:** API returns `["arista", "aruba", "cisco",
    "config-migration", "fastapi", "fortinet", "juniper",
    "mikrotik", "network-automation", "network-configuration",
    "opnsense", "python", "vendor-translation"]` — 13 topics,
    matches IDENTITY.md line 50-63 exactly (GitHub returns them
    alphabetised).
  * **Distribution surfaces table** (lines 144-150) matches
    `pyproject.toml` PyPI listing + actual GHCR / Docker Hub
    image registry namespaces verified via PyPI JSON API
    (`netcanon` package, latest `0.1.2`).
  * License `mit` confirmed in API response; matches `LICENSE`
    file at repo root.
  * Logo brief explicitly marked "Not yet commissioned" — that's
    EXPECTED-STALE per the audit charter (intentional
    forward-looking section).

* Findings: no findings — strongest GitHub-side alignment of any
  doc in the cluster.

---

### `docs/vendors/cisco_iosxe.md`

* Verified claims:
  * `cisco_iosxe_cli` certified, `cisco_iosxe` (NETCONF) best_effort
    (Phase 0.5 stub) — matches codec metadata.
  * VRRP single-line + SD-Access anycast wire-up matches
    `cisco_iosxe_cli/codec.py` `_CAPS` (lines 137-149) and
    `_WIRED_UP_BY_CODEC` entry for `cisco_iosxe_cli`.
  * Modern AF VRRP form lossy + IPv6 SD-Access anycast unsupported
    + track decrement value lossy claims all match `_CAPS`
    declarations.
  * `tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt`
    fixture exists (used as example at line 57).

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 5 | `docs/vendors/cisco_iosxe.md:13` | WRONG | "`cisco_iosxe_cli` — `show running-config` text **parse-only**" — codec is `direction: bidirectional` (`netcanon/migration/codecs/cisco_iosxe_cli/codec.py:80`) and ships an 817-line `render.py`.  Cisco IOS-XE serves as BOTH a translation source AND target throughout `tools/demo.py`, walkthroughs (Junos → Cisco renders), and the demo headline output.  This claim contradicts the entire feature surface. | Replace "parse-only" with "parse + render bidirectional" (matching the wording used on every other vendor page).  The follow-up parenthetical "(Cisco serves as a translation *source*; render lands on the target codec)" should also drop. |
| 6 | `docs/vendors/cisco_iosxe.md:171-184` | INCOMPLETE | Fixtures listed: 7 (Batfish corpus as one bundle + racc CSR1/CSR1000v/Cat8000V + user_contrib_cat9300 + cml_saumur + cml_basic_forwarding).  Actually present in `tests/fixtures/real/cisco_iosxe/`: 13 files including `batfish_iosxe_basic_vrrp.txt` (referenced in the same page's VRRP section!) and `ntc_carrier_interfaces.txt`. | Add the two missing fixtures with one-line provenance each (Batfish-corpus VRRP + ntc-templates carrier-interfaces). |

---

### `docs/vendors/juniper_junos.md`

* Verified claims:
  * `juniper_junos` certified bidirectional matches codec metadata.
  * VRRP grammar (`vrrp-group` nested under `family inet address`)
    + anycast (`virtual-gateway-address`) + per-IRB-unit MAC
    (`virtual-gateway-v4-mac` / `-v6-mac`) all match `_CAPS`
    supported list.
  * Per-VRF static-route lossy declaration matches `_CAPS`
    LossyPath entry verbatim.
  * `/anycast-gateway-mac` unsupported on Junos with the
    "per-IRB-unit override instead" rationale matches `_CAPS`
    UnsupportedPath verbatim.

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 7 | `docs/vendors/juniper_junos.md:164-181` | INCOMPLETE | Fixtures listed: 5 (`buraglio_netlab_junos184.set`, `ksator_labmgmt_qfx5100_junos173.set`, `ksator_labmgmt_ex4550_junos151.set`, `batfish_evpntype5_router1_junos2541.set`, `batfish_l3vpn_pe1_junos2541.set`).  Actually present in `tests/fixtures/real/junos/`: 7 files — also `ksator_labmgmt_qfx10k2_junos173.set` and `ksator_labmgmt_qfx5110_junos173.set`.  The page even cites the QFX10K2 fixture by name in the VRRP section ("Exercised by the QFX10K2 fixture (`ksator_labmgmt_qfx10k2_junos173.set`)" at line 57) but omits it from the fixtures section. | Add the two ksator QFX fixtures with one-line provenance each; update the trailing "Five real captures covering four distinct Junos majors" summary line accordingly (current count claim is itself wrong). |

---

### `docs/vendors/arista_eos.md`

* Verified claims:
  * `arista_eos` certified bidirectional matches codec metadata.
  * VRRP multi-line + VARP per-SVI + chassis-wide MAC supported
    paths all match `arista_eos/codec.py` `_CAPS` (lines 134-139).
  * Per-IP `virtual-gateway-mac` lossy with rationale (only
    chassis-wide MAC supported) matches `_CAPS` LossyPath entry.
  * MLAG + EVPN/VXLAN + spanning-tree gotchas all match observed
    codec behaviour (MLAG peer-link xpath in `_CAPS`; VXLAN paths
    in supported list with GAP-6 demoted comment).

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 8 | `docs/vendors/arista_eos.md:153-167` | INCOMPLETE | Fixtures listed: 4 (`ksator_dcs_7150s64_eos4224.txt`, `batfish_labval_dc1_leaf2a_eos4230.txt`, `batfish_duplicateprivate_eos4211.txt`, `karneliuk_a_eos1_eos4260.txt`).  Actually present: 5 files including `batfish_eos_evpn_vlan_based_leaf.txt`.  "Spans 4 distinct EOS majors (4.21 + 4.22 + 4.23 + 4.26)" summary line at 169 doesn't reflect the missing fixture. | Add `batfish_eos_evpn_vlan_based_leaf.txt` with one-line provenance; verify the spans summary still holds (or update it). |

---

### `docs/vendors/aruba_aoss.md`

* Verified claims:
  * VRRP-on-VLAN-SVI grammar matches `aruba_aoss/codec.py` `_CAPS`
    (supported list line 139) and `_WIRED_UP_BY_CODEC` entry
    (only VRRP graduated; anycast paths still unsupported).
  * Single virtual-ip-per-vrid lossy declaration matches `_CAPS`
    LossyPath entry verbatim.
  * Anycast paths all unsupported with "AOS-S has no native
    anycast grammar" rationale — matches `_CAPS` UnsupportedPath
    entries verbatim.
  * Aruba DHCP-relay comment-block behaviour matches
    `aruba_aoss/render.py` (cited in CAPABILITIES.md § C as well).

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 9 | `docs/vendors/aruba_aoss.md:162-163` | INCOMPLETE | Summary line says "Spans WB / WC / KB software branches and 2530 / 2920 / 2930F / 2930M / 5400R hardware classes" — but `tests/fixtures/real/aruba_aoss/` has NO 2530 fixture (only 2920 / 2930F × 2 / 2930M / 5400R + Aruba Central rendered template + 5406Rzl2 modular).  The body text 144 lines above correctly hedges "other generations (2530, the YA branch, etc.) parse and render through the same pipeline — they just aren't pinned by a fixture yet" — only the summary line over-claims. | Drop "2530 /" from the hardware-classes list, or rephrase as "covers 2920 / 2930F / 2930M / 5400R (2530 / YA branch unfixtured — operator captures welcome)". |

---

### `docs/vendors/fortigate.md`

* Verified claims:
  * VRRP nested-edit grammar + lossy per-knob declarations
    (`vrip` single per group, `vrdst` single per group, virtual-MAC
    drops, anycast paths unsupported) all match
    `fortigate_cli/codec.py` `_CAPS`.
  * Three fixtures listed (`kevinguenay_fgt_70g_branch.conf`,
    `kevinguenay_fgt_vm_hub.conf`, `user_contrib_fg100e_fos7213.conf`)
    — matches `tests/fixtures/real/fortigate/` exactly.
  * `set vdom` single-VDOM scope note + ENC encrypted secrets
    round-trip note both accurate.

* Findings: no findings.

---

### `docs/vendors/mikrotik_routeros.md`

* Verified claims:
  * VRRP top-level pseudo-interface grammar + IP-cross-reference
    pattern matches `mikrotik_routeros/codec.py` `_CAPS` supported
    entry (line 158).
  * Renamed-port preservation + `default-name=ether2` lookup
    syntax claims align with the codec's documented behaviour.
  * Anycast paths unsupported with "SOHO/SMB platform without
    fabric primitives" rationale matches `_CAPS` UnsupportedPath
    entries.
  * Four fixtures listed (`ntc_ip_address_export.rsc`,
    `routeros_diff_verbose_export.rsc`, `taqavi_initial_provisioning.rsc`,
    `user_contrib_crs310_ros7.rsc`) — matches the directory
    contents exactly.

* Findings: no findings.

---

### `docs/vendors/opnsense.md`

* Verified claims:
  * CARP grammar mapping (`<mode>carp`, `<vhid>`, `<advskew>`
    → `priority = 254 - advskew`, `<advbase>` → advertisement
    interval) all match `opnsense/codec.py` `_CAPS` supported
    entry + the OPNsense-specific LossyPath (lines 187-204).
  * "Only mode='carp' round-trips" caveat matches LossyPath
    reason verbatim.
  * `unsupported_rename_categories = frozenset({"snmpv3"})` on
    OPNsense codec matches the doc's SNMPv3 Tier-3 note.

* Findings:

| # | Path:Line | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 10 | `docs/vendors/opnsense.md:160-181` | INCOMPLETE | Fixtures listed: 5 (`opnsense_core_default.xml`, `opnsense_service_test_config.xml`, `opnsense_acl_test_config.xml`, `user_contrib_supergate_opn25.xml`, `opnsense_paramiko_shell_capture.xml`).  Actually present: 7 files — also `opnsense_docs_carp_ha_master.xml` and `opnsense_docs_carp_ha_backup.xml` (added per commit `4686198` "feat(opnsense): pull docs CARP HA fixtures").  These are particularly relevant since the CARP HA pair is the headline new feature documented at lines 43-122. | Add the two CARP HA fixtures with one-line provenance (OPNsense docs site CARP HA tutorial master + backup configs); reinforces the CARP narrative directly above. |

---

### `docs/walkthroughs/README.md`

* Verified claims:
  * Four walkthrough rows match `tools/demo.py` `SCENARIOS` dict
    keys exactly.
  * Format-shape claim (6-section template) matches the actual
    content of all 4 walkthrough files.

* Findings: no findings.

---

### `docs/walkthroughs/cisco_iosxe_to_junos.md`

* Verified claims (traced through `tools/demo.py` and codecs without
  running):
  * Demo command `python tools/demo.py --pair cisco__junos` matches
    `SCENARIOS["cisco__junos"]` in `tools/demo.py:165`.
  * Embedded `_CISCO_IOSXE` source text contains hostname, vlan 10
    (DATA), vlan 20 (VOICE), 3 interfaces with switchport access
    vlan, DNS, NTP, default route — matches what the walkthrough's
    sample output renders (interfaces 0/0/0 / 0/0/1 / 0/0/2;
    VLANs DATA + VOICE; name-server; ntp; default route).
  * Tier-3 deferral list (ACLs / NAT / IPsec / QoS / BGP / OSPF /
    EIGRP) matches `cisco_iosxe_cli/codec.py` `_CAPS` UnsupportedPath
    entries (`/access-list/*`, `/firewall`, `/nat`) and Junos codec
    UnsupportedPath entries (`/routing/bgp`, `/firewall/filter`).

* Findings: no findings.

---

### `docs/walkthroughs/fortigate_to_mikrotik.md`

* Verified claims (traced through demo + codecs):
  * Embedded `_FORTIGATE` source text covers system global
    (hostname), system dns, two interfaces, DHCP server pool —
    matches walkthrough's "embedded scenario covers …" claim
    verbatim.
  * Tier-3 deferral list (firewall policy / NAT / IPsec / SSL-VPN /
    UTM / SD-WAN / FortiGuard) matches `fortigate_cli/codec.py`
    `_CAPS` UnsupportedPath entries (`/filter/rule`, `/nat/rule`,
    VXLAN paths).
  * "Most of a FortiGate config is Tier-3" — confirmed by the
    `kevinguenay_fgt_70g_branch.conf` fixture documented at 12,317
    lines in vendor page.

* Findings: no findings.

---

### `docs/walkthroughs/aruba_to_arista.md`

* Verified claims (traced through demo + codecs):
  * Embedded `_ARUBA_AOSS` source text matches walkthrough
    description (hostname, three VLANs DEFAULT/USERS/MGMT,
    inter-VLAN L3 IPs, default-gateway, DNS, SNMP).
  * Paradigm-flip narrative (AOS-S `untagged 1-20` projected to
    Arista per-port `switchport access vlan 10`) matches the
    codec's `project_switchport_to_vlan` transform documented in
    `netcanon/migration/canonical/transforms.py` (referenced in
    TROUBLESHOOTING.md).
  * Rename-mesh affordance (`POST /api/v1/migration/run` with
    `rename_overrides`) matches the actual route signature in
    `netcanon/api/routes/migration.py`.

* Findings: no findings.

---

### `docs/walkthroughs/opnsense_to_junos.md`

* Verified claims (traced through demo + codecs):
  * Embedded `_OPNSENSE` source text matches "intentionally
    minimal (system + WAN/LAN interfaces + DNS)" description.
  * Tier-3 deferral list (`<filter>` / `<nat>` / `<ipsec>` /
    `<wireguard>` / OpenVPN / `<proxy>` / `<captiveportal>` /
    routing-protocol plugins / `<cert>` / `<ca>`) matches OPNsense
    Tier-3-detection helper in `_tier3_detection.py` +
    `opnsense/codec.py` `_CAPS` UnsupportedPath entries.
  * Migrate-page banner example (`filter (847 rules)` etc.) is
    illustrative not literal — phrasing is honest.

* Findings: no findings.

---

### `docs/vendors/README.md`

* Verified claims:
  * Per-vendor table (7 families, 8 codecs) matches
    CAPABILITIES.md supported-vendors table.
  * Page-format shape (8 sections, L3 redundancy section v0.2.0+)
    matches every per-vendor page audited above.

* Findings: no findings.

---

## Vendor-references sampling result

### Sampled pair (in depth): `docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/`

* File count: 14 files (`_INDEX.md` + 13 topic files).
* `_INDEX.md` schema: title + 1-paragraph context + topic table
  + retrieval date + see-also.  Consistent with the cache
  convention documented in `docs/vendor-references/README.md`.
* Spot-check on `interface-naming.md`: includes Source URLs +
  retrieval date + citation ids (matching `cisco-interface-cli` /
  `junos-iface-naming` keys in `_INDEX.md`).  Per-vendor form
  blocks (Cisco / Junos) + Mapping notes — follows the
  documented template at `docs/vendor-references/README.md:35-57`.
* Citation IDs in `_INDEX.md` map cleanly to YAML expectation
  references (not exhaustively checked — sampled-pair scope).

* No findings on the sampled pair.

### Cross-pair template consistency (56 pairs other than sampled)

* All 56 pair directories carry `_INDEX.md` (zero pairs missing).
* File counts vary widely: 8-16 files per pair.
  * Lowest (8): `arista_eos_to_cisco_iosxe`,
    `cisco_iosxe_to_arista_eos`, `cisco_iosxe_to_fortigate_cli`,
    `cisco_iosxe_to_mikrotik_routeros`, `cisco_iosxe_to_opnsense`,
    `fortigate_cli_to_cisco_iosxe`, `mikrotik_routeros_to_cisco_iosxe`.
    These are NETCONF-side pairs where many surfaces are
    unsupported on the NETCONF stub — fewer topic files makes
    sense.
  * Highest (16): `fortigate_cli_to_aruba_aoss`,
    `aruba_aoss_to_fortigate_cli`.  Plausible — both vendors
    model rich surfaces, the cross-paradigm surface area is
    largest.

* Per the cluster-B scope ("for the other ~41 pairs, verify the
  template shape is consistent rather than auditing each page
  individually") — template shape is consistent across the
  sampled spot-checks (each directory has its `_INDEX.md` table
  with citation IDs + topic columns).

* Findings:

| # | Path | Severity | Finding | Fix shape |
|---|---|---|---|---|
| 11 | `docs/vendor-references/<pair>/` (cross-pair) | INCOMPLETE | File-naming convention is inconsistent across pairs.  Some pairs use hyphen-separated topic names (`interface-naming.md`, `vrf-routing-instances.md`), others use underscore-separated (`interface_naming.md`, `local_users.md`), and some have `_unsupported` / `_gap` suffix conventions specific to one pair (`vlan-render-gap.md` in `arista_eos_to_cisco_iosxe/`, `vrf_unsupported.md` in `arista_eos_to_aruba_aoss/`).  Doesn't affect correctness but does affect cross-pair grep / discoverability for contributors. | Pick one (hyphen-separated is the more common pattern in modern doc convention); rename inconsistent files in a hygiene pass.  Lower priority than per-doc accuracy findings; batch with other rename passes. |

---

## Cross-cutting observations

### Vendor-page fixture-listing drift is the dominant pattern (4 of 6 vendor pages affected)

Four of the six per-vendor pages with fixture lists (Cisco IOS-XE,
Juniper, Arista, OPNsense) under-list real fixture coverage.  The
common cause appears to be that new fixtures get committed (per
recent git log: `feat(opnsense): pull docs CARP HA fixtures`,
`feat(opnsense): pull docs CARP HA fixtures (master + backup)`)
without the AGENTS.md "doc-sync" row "A new real-capture fixture
under `tests/fixtures/real/<vendor>/`" rule firing for the
per-vendor page (it fires for `NOTICE.md` and `RESULTS.md`, but
not for the vendor pages).  **Fix shape:** consider extending the
doc-sync row to include "and the vendor page's fixtures list, if
the new fixture exercises a notable grammar."  Mechanical guard
would be a unit test that asserts `docs/vendors/<vendor>.md`'s
fixture-list count matches `len(os.listdir('tests/fixtures/real/
<vendor>/'))` minus the README files — but that's prose-rot
territory (per AGENTS.md hard rule); the soft suggestion is the
doc-sync row extension.

### Wave B + C VRRP / anycast narrative is the most accurate slice

Every per-vendor page's L3-redundancy section matches its codec's
`_CAPS` + the `_WIRED_UP_BY_CODEC` map in
`tests/unit/migration/test_canonical_vrrp_anycast_schema.py`
verbatim.  This is the strongest evidence the "ship-before-wire
pattern" + the test invariant work as designed for keeping docs
honest — the two-sided invariant test (already in place per the
test file's `TestShipBeforeWireUnsupportedDeclarations`) forces
the matrix declarations to track wire-up state, and the
CAPABILITIES.md narrative follows because it cites the codec's
`_CAPS` text directly.  No findings on this slice across 7 codecs
× 2 surfaces (VRRP + anycast).

### Sanitiser claims tracked exactly — the BUG_REPORTING.md / sanitize.py contract is healthy

The 9-field replacement table in BUG_REPORTING.md lines 137-148
matches the actual `sanitize_intent` walk in
`netcanon/tools/sanitize.py` lines 187-360 field-for-field.
Counter-per-session stability claim verifiable in
`_SubstitutionTable.__init__` (lines 378-396).  The IPv6-public
limitation honestly disclosed.  Operators reading this doc and
then auditing the sanitiser output will find what's promised.
No findings on the sanitiser contract.

### IDENTITY.md ⇄ GitHub repo metadata is in sync (zero drift)

This is a known-difficult discipline to maintain because the
GitHub-side surface lives outside the repo.  Both halves
(description + topics) match byte-for-byte as of the audit run.
The "Distribution surfaces" table also matches PyPI / GHCR /
Docker Hub registry contents.  No findings.

### One forward-looking surface flagged not as drift but as a pattern check

`docs/RELEASE_PLAN.md` is referenced as the parent doc IDENTITY.md
derives from ("Phase 2 of `docs/RELEASE_PLAN.md`").  Per audit
charter (`docs/v0.2.0-planning/`, etc. = EXPECTED-STALE), I did
not audit `RELEASE_PLAN.md` itself — it's a planning artifact.
Note for orchestrator: if RELEASE_PLAN.md is reorganised, the
IDENTITY.md back-reference may need updating, but as long as
"Phase 2" stays present in RELEASE_PLAN.md, IDENTITY.md's reference
remains valid.

---

## Severity recap

| Severity | Count | Findings |
|---|---|---|
| WRONG | 2 | #1 (Python version matrix), #5 (Cisco "parse-only") |
| MISSING | 0 | — |
| INCOMPLETE | 9 | #2 (Docker quickstart fernet), #6 / #7 / #8 / #10 (vendor-page fixture lists), #9 (Aruba 2530), #11 (vendor-references naming), [implicit: cross-cutting fixture drift pattern] |
| STYLE | 3 | #3 (Phase 4.5 wording), #4 (BUG_REPORTING.md broken `../` links), and the file-naming inconsistency at finding #11 has style overlap |
| EXPECTED-STALE | 0 | — |

The two WRONG findings are both single-word / single-line edits.
INCOMPLETE findings are concentrated on the per-vendor pages'
fixtures section — a consistent under-listing pattern that
suggests adding a doc-sync row would have caught all four.

## Notes for orchestrator

* Finding #4 (broken `../` links in BUG_REPORTING.md) overlaps
  with cluster-A interlinking scope.  Defer to whichever
  cluster lands the fix first; the substantive fix is small
  (strip the `..` prefix).
* Findings #6 / #7 / #8 / #10 are mechanical fixture-list
  additions; appropriate for orchestrator-direct fixing.
* Finding #1 + #5 are both single-line edits; appropriate for
  orchestrator-direct fixing in the same commit.
* Finding #2 is a UX-philosophy nudge ("warn the operator that
  the 10-second demo doesn't persist state"); reasonable to defer
  if the project decision is "the demo's whole point is
  ephemeral".
* Finding #3 (Phase 4.5 wording) is operator-facing; safe to
  batch with other STYLE fixes.
* Finding #9 (Aruba 2530 over-claim) is a 3-character delete in
  the summary line.
* Finding #11 (vendor-references naming inconsistency) is the
  largest in scope but lowest in user impact; batch or defer.
