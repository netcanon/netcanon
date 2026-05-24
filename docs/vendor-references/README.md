# Vendor reference cache

This directory caches downloaded vendor documentation referenced by the
per-pair YAML expectation files at
`tests/fixtures/cross_vendor_expectations/<source>__<target>.yaml`.
Local copies survive external URL rot; a curated markdown summary per
topic distills the relevant sections so a future contributor can
re-derive the per-field disposition without re-fetching every page.

## Layout

```
docs/vendor-references/
    README.md                                       (this file)
    <source_codec>_to_<target_codec>/
        _INDEX.md                                   (per-pair table of contents)
        <topic-1>.md                                (curated summary + citations)
        <topic-2>.md
        ...
        raw/<topic-N>.html                          (optional raw fetch — only when curation lossy)
```

One subdirectory per ordered (source, target) pair.  Pair directories
are named `<source_codec>_to_<target_codec>/` where the codec names
match `CodecBase.name` (e.g. `arista_eos`, `juniper_junos`,
`cisco_iosxe_cli`).  Reverse pairs (Junos → Arista as well as Arista →
Junos) get their own directory; expected dispositions are not
symmetric (a field that's "good" Arista → Junos may be "lossy" Junos →
Arista because Junos models richer detail that Arista flattens).

## Curated summary file convention

Each topic markdown file follows this template:

```markdown
# <Topic title>

Source: <vendor URL>
Retrieved: <YYYY-MM-DD>
Citation id: <id-used-in-yaml-references>

## Arista EOS form

```
<verbatim CLI snippet>
```

## Junos form

```
<verbatim set-line snippet>
```

## Mapping notes

<1-3 bullet points on how the canonical model bridges them>
```

Aim for ~1-2KB per topic — enough to anchor the per-field disposition
without re-pasting full vendor manuals.  When a topic is more nuanced
than that, link to a `raw/<topic>.html` companion under the same pair
directory.

## Citation convention

Per-pair YAML files reference these by relative path from repo root.
Each `references[].id` in the YAML is a stable handle that
`per_field_expectation` entries cite via `references: [<id>]`.  The
mapping `id → file → URL → retrieval-date` lives only in the YAML's
`meta.references` block, NOT in the markdown body — this keeps a
single source of truth for citation metadata.

## Re-fetch policy

URLs rot.  When a future contributor finds a 404, the workflow is:

1.  Search vendor TechHub / TechLibrary for the same topic on the
    current OS release.
2.  Replace the URL in the YAML's `meta.references` block with the
    current location and bump `retrieved` to today.
3.  Re-derive the curated markdown body if the syntax changed.

Don't delete the old markdown — it's the dated snapshot we authored
the per-field assessment against.

## See also

- [`tests/fixtures/cross_vendor_expectations/README.md`](../../tests/fixtures/cross_vendor_expectations/README.md)
  — schema spec for the per-pair YAML files this directory backs.
- [`tests/fixtures/real/CROSS_MESH_RESULTS.md`](../../tests/fixtures/real/CROSS_MESH_RESULTS.md)
  — Phase 1 mechanical fidelity matrix that motivates the per-pair
  grounding.
- [`tools/run_phase4_reconciliation.py`](../../tools/run_phase4_reconciliation.py)
  — the Phase 4a reconciler that joins the Phase 1 drift JSON with the
  per-pair expectation YAMLs this directory backs to bucket each cell
  into ALIGNED / CODEC_BUG / EXPECTED_LOSSY / etc.
