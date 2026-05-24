# Cluster D — Codec docstrings + file headers

## Scope

All Python files in `netcanon/migration/codecs/` — 45 files
across 7 production codecs + 1 stub + the mock codec:

```
netcanon/migration/codecs/
  arista_eos/        (5 .py)
  aruba_aoss/        (6 .py)
  cisco_iosxe/       (2 .py — NETCONF Phase-0.5 stub)
  cisco_iosxe_cli/   (5 .py)
  fortigate_cli/     (6 .py)
  juniper_junos/     (5 .py)
  mikrotik_routeros/ (5 .py)
  opnsense/          (5 .py)
  _mock/             (2 .py — test scaffolding)
```

Plus any shared codec infrastructure: `base.py`, `__init__.py`,
`port_lists.py`, `codec_helpers/`, etc.

## Out of scope

* Non-codec netcanon Python files (handled by Cluster E)
* Test files exercising the codecs (handled by Cluster F)
* Codec capability matrices declared in `_CAPS` — accuracy of
  `_CAPS` vs `_WIRED_UP_BY_CODEC` is covered by Cluster B's
  capability-matrix audit
* The `_mock` codec — read for shape only; not production code

## What to verify

1. **Module-level docstrings.**  Each `.py` file should have a
   module docstring (triple-quoted at top, after imports).  For
   each codec module, the docstring conventionally enumerates:
   * Purpose / what the module covers
   * Public surface (functions/classes contributors should
     import from outside the module)
   * Wave / version annotations where relevant ("Wave B adds
     CARP groups...")
   * Cross-references to the canonical model + AGENTS.md hard rules
   Verify these enumerations match what's actually in the file.

2. **Class docstrings.**  Each public class (CodecBase subclasses,
   parser/renderer helper classes) should have a docstring
   describing role + relationship to the codec's parse/render
   surface.

3. **Function docstrings — Google-style sections.**  Per AGENTS.md
   doc-sync row ("A function gains a new parameter or changes
   return shape | Its docstring (Google-style sections for
   Args / Returns / Raises)"), public functions should have:
   * One-line summary
   * Args: (with type + meaning per parameter)
   * Returns: (shape + type)
   * Raises: (per documented exception)
   Verify present + accurate for public surface.  Private functions
   (`_prefix`) may have shorter or no docstrings — that's a style
   preference, surface as INCOMPLETE only if the function is
   non-obvious.

4. **"Public surface" lists in module docstrings.**  Several codec
   modules enumerate their public surface explicitly (e.g.
   "Public surface (consumed by codec.py's parse() method):
   * parse_intent — one-shot parse entry...").  Verify the
   enumeration matches actual exports.  Missing entries = MISSING;
   stale entries (functions removed but still listed) = WRONG.

5. **Top-of-file purpose comments.**  Some files have a comment
   block above the module docstring (license header, ASCII-art
   section dividers).  Verify these are consistent across codecs
   — outliers worth noting.

6. **Wave-version annotations.**  Several modules cite "Wave A
   adds X", "Wave B adds Y" inline.  Verify these annotations are
   chronologically consistent + the cited features are present at
   the cited locations.

7. **Sibling-module consistency.**  Each codec follows the same
   layout: `__init__.py`, `codec.py` (CodecBase subclass +
   `_CAPS`), `parse.py`, `render.py`, `port_names.py`.  Verify the
   module set is consistent; surface outliers.  Some codecs have
   extra modules (e.g. `aruba_aoss/` has a 6th file) — verify
   those have purpose docstrings.

8. **`ET` import comments.**  Per the v0.1.2 defusedxml swap, the
   two affected codecs (`opnsense/parse.py`, `cisco_iosxe/codec.py`)
   should have explanatory comments on the safe-import pattern.
   Verify those comments still match the actual import.

## Methodology

* `Read` each codec file fully (or at least the module docstring +
  top of each class/function definition).
* `Grep` to find all function/class definitions per codec, then
  cross-check against documented "Public surface" lists.
* Use the `Grep` output for `^(class|def) ` to enumerate the actual
  public surface per file.

## Severity tagging

| Severity | Examples |
|---|---|
| **WRONG** | Module docstring lists a function that no longer exists; Args section describes a parameter that was renamed; Returns description contradicts actual return shape |
| **MISSING** | Public function with no docstring at all; public class with no docstring; module has no top-level docstring |
| **INCOMPLETE** | Function has a one-liner but no Args/Returns sections; class docstring describes role but not attributes; module docstring lacks "Public surface" enumeration |
| **STYLE** | Inconsistent docstring format across codecs; module description uses different terminology than the canonical |

## Output format

Write to: `docs/docs-audit/2026-05-21/01-investigation-D.md`

```markdown
# Cluster D — Codec docstrings + file headers

## Summary

(2-3 sentence verdict: total findings split by severity + by codec.)

## Per-codec audit

### arista_eos
* Module docstring shape: (verified / drift noted)
* "Public surface" list accuracy: ...
* Function-level audit: (counts, key findings)
* Findings table:

| # | Path:Line | Severity | Finding | Fix shape |

### aruba_aoss
... (same pattern)

### cisco_iosxe (NETCONF stub)
...

### cisco_iosxe_cli
...

### fortigate_cli
...

### juniper_junos
...

### mikrotik_routeros
...

### opnsense
...

## Cross-cutting observations

(Patterns across codecs: e.g. "all codecs declare _CAPS at the top
of codec.py — opnsense uses a different name"; recurring docstring
gaps; sibling-module consistency.)
```

## Constraints

* **READ-ONLY.**  Single output file.
* Hard rules from `AGENTS.md`.  ESPECIALLY:
  * "Pipeline-stage signature changes — DON'T (frozen)" — if you
    find a frozen signature with stale docstring, flag separately
    so Stage 2 doesn't accidentally touch the signature itself.
* Time budget: largest cluster by file count; ~60-90 min.
  Reading 45 files + cross-checking surfaces is real work.
* For very long files (e.g. `aruba_aoss/parse.py` may be > 1000
  lines), focus on the docstring/header surface + spot-check
  function docstrings; don't read every line.
