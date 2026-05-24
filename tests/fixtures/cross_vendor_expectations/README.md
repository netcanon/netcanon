# Cross-vendor expectation YAML — schema spec

This directory holds **per-pair vendor-doc-grounded expectations** for
cross-vendor translation fidelity.  One YAML file per ordered
(source, target) codec pair, named `<source>__<target>.yaml` (double
underscore separator).

These files turn the mechanical drift matrix in
`tests/fixtures/real/CROSS_MESH_RESULTS.md` into actionable judgement:
"this field drifted because Junos doesn't model it" vs "this field
drifted and that's a codec bug".  Each per-field record cites the
vendor documentation that grounds the assessment; cited docs are
cached in `docs/vendor-references/<source>_to_<target>/` so external
URL rot doesn't invalidate the audit.

## File naming

```
<source_codec>__<target_codec>.yaml
```

Where the codec names match `CodecBase.name` (e.g. `arista_eos`,
`juniper_junos`, `cisco_iosxe_cli`).  Use a double underscore to
separate; single underscores appear inside multi-word codec names.

Reverse pairs are independent files — `arista_eos__juniper_junos.yaml`
and `juniper_junos__arista_eos.yaml` are not assumed symmetric.  A
field can be "good" one way and "lossy" the other (e.g. Junos models
per-unit interface detail Arista doesn't, so Junos → Arista loses
detail Arista → Junos doesn't have to lose).

## Schema

```yaml
meta:
  source_vendor: <codec_name>           # CodecBase.name of the source codec
  target_vendor: <codec_name>           # CodecBase.name of the target codec
  primary_use_case: <free-text>         # what migration this pair is most relevant to
  certainty: high | medium | low        # confidence calibration over the per-field assessments
  references:
    - id: <stable-handle>               # used by per_field_expectation entries
      path: <repo-relative path to curated markdown>
      title: <human-readable doc title>
      source_url: <vendor doc URL>
      retrieved: <YYYY-MM-DD>
      excerpt: <optional 1-2 sentence quote>      # optional

per_field_expectation:
  <canonical-field-key>:
    disposition: good | lossy | unsupported | not_applicable
    note: <optional positive note>                # optional, present on 'good' or 'lossy'
    reason: <required for lossy / unsupported>    # absent for 'good' / 'not_applicable'
    references: [<id>, <id>, ...]                 # optional list of meta.references[].id
```

### Field keys

Field keys mirror the dotted path through `CanonicalIntent`.  Top-level
scalars use their direct name (`hostname`, `domain`).  List fields can
be addressed at the list level (`syslog_servers`) when the disposition
applies uniformly, OR at a sub-field level using `[].field` notation
(`interfaces[].name`, `vlans[].name`, `vxlan_vnis[].udp_port`).
Single-value sub-objects use dot notation (`snmp.communities`,
`snmp.v3_users`).

The full enumeration of top-level fields is the union of the public
attributes on `CanonicalIntent` in `netcanon/migration/canonical/intent.py`.
Every authored YAML file should walk the whole list — fields not
researched yet should still appear with `disposition: lossy` +
`reason: "deferred to subsequent audit pass"` rather than be silently
omitted, so the coverage gap is explicit.

### Disposition values

- **`good`** — both vendors model the concept, the canonical
  representation captures the cross-vendor surface, and a typical
  config round-trips with semantic preserved.  No `reason` required.
  Optional `note` for clarifying details.
- **`lossy`** — the canonical model carries the data but a typical
  cross-vendor render drops nuance the source had.  Common causes:
  vendor-specific syntax quirks, hash-format incompatibility,
  policy-statement plumbing that doesn't survive without a richer
  canonical model.  `reason` REQUIRED; cite at least one reference
  unless the loss is internally documented (e.g. a codec
  `CapabilityMatrix` `LossyPath` entry).
- **`unsupported`** — the target vendor doesn't model the concept at
  all (in the auto-render canonical-portable form), so the renderer
  emits a comment / TODO marker / nothing.  `reason` REQUIRED.
- **`not_applicable`** — the field is structurally absent on the
  source vendor's wire format (e.g. `apply_groups` is a Junos-only
  concept; sources from any other vendor never populate it).  `reason`
  not strictly required if obvious; `note` is fine for clarification.

### Certainty calibration

`meta.certainty` flags the whole pair's confidence:

- **`high`** — author has working DC experience with both vendors AND
  vendor docs were cited for every non-trivial field.  Tighten this
  bar over time as the cross-mesh audit matures.
- **`medium`** — most fields cited; some assessments derive from
  general principles (e.g. "both support standard NTP") without a
  per-field doc lookup.
- **`low`** — multiple fields tagged `lossy` with `reason: deferred`.
  Schedule a re-pass before relying on this file.

## Authoring workflow

1.  Read `netcanon/migration/canonical/intent.py` end-to-end to
    enumerate every top-level field.
2.  For each field, read the source codec's `CapabilityMatrix` (in
    `netcanon/migration/codecs/<source>/codec.py`) and the target
    codec's matrix.  Drift only matters when both list it as
    `supported`.
3.  Search vendor docs (Arista TechHub, Junos TechLibrary, Cisco
    Configuration Guides) for the canonical concept.  Use `WebFetch`
    to grab the page, summarise into
    `docs/vendor-references/<source>_to_<target>/<topic>.md`, and
    cite by `id` in the YAML.
4.  Honest classification beats optimistic.  When you can't decide
    after ~5 minutes, mark `lossy` with `reason: "deferred to
    subsequent audit pass"` and move on — `meta.certainty` already
    flags incomplete pairs.

## See also

- [`docs/vendor-references/README.md`](../../../docs/vendor-references/README.md)
  — citation cache layout.
- [`tests/fixtures/real/CROSS_MESH_RESULTS.md`](../real/CROSS_MESH_RESULTS.md)
  — the mechanical drift matrix these YAMLs interpret.
- [`netcanon/migration/canonical/intent.py`](../../../netcanon/migration/canonical/intent.py)
  — the canonical schema whose top-level fields drive the YAML key list.
