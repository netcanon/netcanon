# Phase 4b — opnsense source CODEC_BUG findings

Investigation of every `field_variances[*].variance == "CODEC_BUG"` cell in
`tests/fixtures/real/_phase4_runs/latest.json` whose `source_codec ==
"opnsense"`.  Reconciles against the per-target Phase 3 expectation YAMLs
under `tests/fixtures/cross_vendor_expectations/opnsense__<target>.yaml`.

The reconciliation matrix in `PHASE4_RECONCILIATION.md` reports 10 OPNsense-
sourced CODEC_BUG cells, distributed: arista_eos (1), aruba_aoss (4),
fortigate_cli (5).  All 10 reconcile to one of three root causes; no finding
implicates the OPNsense parser itself.

## Bucket totals

Each finding lands in exactly one bucket:

| Bucket | Meaning | Count |
|---|---|---:|
| A | Genuine codec defect (parser drops, renderer omits, missing wire path) | **6** |
| B | Stale Phase 3 YAML — drift is now legitimate output of a canonical-layer fix | **0** |
| C | Comparator / methodology artefact (drift is structural, not data loss) | **4** |
| | **Total CODEC_BUG cells** | **10** |

No wave-6-cascade entries: the wave-6 commits (`c16d2c0`, `5edf800`,
`2b2c743`) wired `<ipaddr>dhcp</ipaddr>` into `CanonicalInterface.dhcp_client`
and lifted admin-priv elevation, but neither `dhcp_client` nor `local_users`
appear among the 10 bug cells — the per-target YAMLs already declare both
`lossy`, so those fields surface as `METHODOLOGY_ISSUE_under` or
`EXPECTED_LOSSY`, not CODEC_BUG.  Phase-4d can skip OPNsense.

## Per-target sections

### opnsense → fortigate_cli (5 CODEC_BUGs · all Bucket A)

Affected cells: `opnsense_acl_test_config.xml`, `opnsense_core_default.xml`,
`opnsense_paramiko_shell_capture.xml`, `user_contrib_supergate_opn25.xml`,
`synthetic/opnsense/kitchen_sink.xml`.  Single field on each:
``domain`` (`'localdomain' → ''`, `'internal' → ''`, `'example.test' → ''`,
`'example.net' → ''`, etc.).

YAML disposition: `domain: good`.  Drift is real.

**Locus.** `netconfig/migration/codecs/fortigate_cli/parse.py:268-274` —
`_apply_system_dns` captures `primary` and `secondary` resolver IPs but
makes no reference to the `domain` setting.  The renderer at
`render.py:443-451` correctly emits `set domain "<value>"` inside
`config system dns`, so the loss is parse-side only (round-trip drops it).

### opnsense → arista_eos (1 CODEC_BUG · Bucket A)

Affected cell: `synthetic/opnsense/kitchen_sink.xml`, field
``radius_servers``.  Drift summary: ``all 2 radius_servers dropped`` (source
carries 10.0.0.50 + 10.0.0.51 with `fakeRadiusSharedSecret*` keys; target
empty).

YAML disposition: `radius_servers: good`.  Drift is real.

**Locus.** `netconfig/migration/codecs/arista_eos/{parse,render}.py` —
zero occurrences of `radius` (case-insensitive grep).  The arista codec
has no RADIUS surface; the canonical list is silently dropped on render.
Either implement EOS render (`radius-server host <ip> auth-port 1812
acct-port 1813 key <key>` plus parse counterpart) or — cheaper — flip
YAML to `unsupported`.  Flagged Bucket A so the codec gap shows up in
the backlog rather than being papered over by a YAML edit.

### opnsense → aruba_aoss (4 CODEC_BUGs · 1 Bucket A, 3 Bucket C)

Affected cell: `synthetic/opnsense/kitchen_sink.xml` only.  Four fields:

| Field | drift | Bucket | Rationale |
|---|---|---|---|
| `radius_servers` | server 2 ports `11812/11813 → 1812/1813` | **A** | render at `aruba_aoss/render.py:368-374` only emits `radius-server host {host} key "{key}"`; auth-port / acct-port not emitted, parser regex (parse.py:156-161) doesn't capture them either.  YAML says `good` but loses non-default ports. |
| `interfaces[].enabled` | em4 source `false` → target `true` | **C** | em4 is an OPNsense `<opt5>` zone with `<enable>` element absent (canonical `enabled=false`).  After port-rename mesh + aruba SVI absorption the resulting interface list is reordered such that the per-record diff lines em4 against a different source slot.  Not a codec data loss. |
| `interfaces[].ipv4_addresses` | em0/em1/em2/em3 IPs scrambled | **C** | Same mechanism: `198.51.100.2/30` source-on-em0 lands on em2 in the target list because OPNsense zone labels (`<wan>`, `<lan>`, `<opt2>`) carry the IP while aruba parse rebinds onto em-named ports in canonical order.  Pair YAML already declares `interfaces[].name: lossy` with explicit "OPNsense zone labels do not survive on Aruba" rationale — the per-record IP drift is the second-order consequence the comparator misclassifies as bug. |
| `interfaces[].ipv6_addresses` | em1 source carries `2001:db8:10::1/64`, lands on em3 | **C** | Same as above. |

The radius-port loss is genuine.  The three interface drifts all stem from
the comparator computing per-record diffs by positional index after the
list has been reshuffled by an upstream `lossy`-classified field
(`interfaces[].name`).  A comparator fix that walks the per-record diff by
canonical-name JOIN rather than positional index would dissolve the three
Bucket-C entries.

## Top 3 fixes (priority order)

1. **`netconfig/migration/codecs/fortigate_cli/parse.py:268`** — extend
   `_apply_system_dns` to capture `set domain` from the `config system
   dns` block (`intent.domain = block.settings["domain"][0]` when
   present).  Five-line change, kills 5 of 10 OPNsense-sourced bugs.
   Mirror unit test:
   `tests/unit/migration/codecs/fortigate_cli/test_parse.py::
   test_parse_system_dns_domain` constructing a `config system dns / set
   domain "example.com" / end` block and asserting
   `parse(...).domain == "example.com"`.

2. **`tools/run_phase4_reconciliation.py` (or its comparator helper)** —
   when a parent-list field carries `lossy` per the YAML and the per-record
   diff would be empty under a name-keyed JOIN, suppress per-sub-field
   CODEC_BUG attribution.  Eliminates the three opnsense → aruba interface
   bucket-C rows AND likely a population of similar phantom drifts on the
   juniper / aruba and juniper / arista source pairs.  Pure tooling fix,
   no codec change.

3. **`netconfig/migration/codecs/aruba_aoss/{render,parse}.py`** — render
   `radius-server host <ip> auth-port <port> acct-port <port> key
   "<key>"` whenever the canonical record carries non-default ports;
   extend `_RADIUS_HOST_RE` (parse.py:156) to optionally capture the
   port tokens.  Single bug cleared but it's a real wire-loss that
   YAMLs currently obscure.  Lower-priority than 1 and 2 because it's
   one bug, but mechanically cheap.

The arista RADIUS gap (1 bug) is acknowledged but deferred — implementing
the full EOS RADIUS surface is a feature lift, not a bug fix; the cheap
alternative (YAML reclassify to `unsupported`) is a Bucket-B-style edit
the next phase-4d wave should pick up after the codec backlog is reviewed.

## See also

- `tests/fixtures/real/PHASE4_RECONCILIATION.md` — overall matrix and the
  per-pair counts that drove this scope
- `tests/fixtures/real/_phase4_runs/latest.json` — per-cell raw data
- `tests/fixtures/cross_vendor_expectations/opnsense__fortigate_cli.yaml`,
  `opnsense__arista_eos.yaml`, `opnsense__aruba_aoss.yaml` — Phase 3
  expectation YAMLs reconciled against
- `netconfig/migration/codecs/fortigate_cli/parse.py:268` — locus of the
  domain parse gap (top fix)
- `netconfig/migration/codecs/aruba_aoss/render.py:368-374` and
  `parse.py:156-161` — locus of the RADIUS port omission
- `netconfig/migration/codecs/arista_eos/` — RADIUS surface entirely
  absent; either implement or YAML-reclassify
