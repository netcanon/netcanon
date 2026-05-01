"""Load + validate per-pair cross-vendor expectation YAML files.

Walks ``tests/fixtures/cross_vendor_expectations/*.yaml`` and validates
the schema documented in
``tests/fixtures/cross_vendor_expectations/README.md``.  Run from the
repo root::

    python tools/load_cross_vendor_expectations.py

Exits non-zero if any file fails validation; prints a summary table
of (pair, certainty, field-count, disposition-breakdown) on success.

This is a lint-style utility — the test suite wires equivalent checks
into ``tests/unit/migration/test_cross_vendor_expectations.py`` (when
that file exists; not required for Phase 3a).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


VALID_DISPOSITIONS = {"good", "lossy", "unsupported", "not_applicable"}
VALID_CERTAINTY = {"high", "medium", "low"}


def validate_one(path: Path) -> tuple[str, dict]:
    """Validate a single YAML file; return (pair_id, summary_dict).

    Raises ``ValueError`` on schema violation.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: top-level must be a mapping")

    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise ValueError(f"{path.name}: missing 'meta' block")
    for key in ("source_vendor", "target_vendor", "primary_use_case", "certainty"):
        if key not in meta:
            raise ValueError(f"{path.name}: meta.{key} required")
    if meta["certainty"] not in VALID_CERTAINTY:
        raise ValueError(
            f"{path.name}: meta.certainty must be one of "
            f"{sorted(VALID_CERTAINTY)}, got {meta['certainty']!r}"
        )

    refs = meta.get("references", [])
    if not isinstance(refs, list):
        raise ValueError(f"{path.name}: meta.references must be a list")
    ref_ids = set()
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError(f"{path.name}: each reference must be a mapping")
        for key in ("id", "path", "title", "source_url", "retrieved"):
            if key not in ref:
                raise ValueError(
                    f"{path.name}: reference missing {key!r}: {ref}"
                )
        if ref["id"] in ref_ids:
            raise ValueError(f"{path.name}: duplicate reference id {ref['id']!r}")
        ref_ids.add(ref["id"])

    fields = data.get("per_field_expectation")
    if not isinstance(fields, dict):
        raise ValueError(f"{path.name}: missing 'per_field_expectation' block")

    breakdown = {k: 0 for k in VALID_DISPOSITIONS}
    for field_name, entry in fields.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"{path.name}: per_field_expectation[{field_name!r}] must be a mapping"
            )
        disp = entry.get("disposition")
        if disp not in VALID_DISPOSITIONS:
            raise ValueError(
                f"{path.name}: {field_name!r} disposition must be one of "
                f"{sorted(VALID_DISPOSITIONS)}, got {disp!r}"
            )
        breakdown[disp] += 1
        if disp in ("lossy", "unsupported") and "reason" not in entry:
            raise ValueError(
                f"{path.name}: {field_name!r} disposition={disp} requires 'reason'"
            )
        cited = entry.get("references", [])
        if not isinstance(cited, list):
            raise ValueError(
                f"{path.name}: {field_name!r} references must be a list"
            )
        for cite in cited:
            if cite not in ref_ids:
                raise ValueError(
                    f"{path.name}: {field_name!r} cites unknown reference id {cite!r}"
                )

    pair_id = f"{meta['source_vendor']}__{meta['target_vendor']}"
    return pair_id, {
        "certainty": meta["certainty"],
        "field_count": len(fields),
        "breakdown": breakdown,
    }


def main(argv: list[str]) -> int:
    base = Path(__file__).resolve().parent.parent
    fixtures = base / "tests" / "fixtures" / "cross_vendor_expectations"
    if not fixtures.is_dir():
        print(f"ERROR: {fixtures} not found", file=sys.stderr)
        return 2

    yaml_files = sorted(fixtures.glob("*.yaml"))
    if not yaml_files:
        print(f"No YAML files under {fixtures} — nothing to validate.")
        return 0

    failures = []
    summaries = []
    for path in yaml_files:
        try:
            pair_id, summary = validate_one(path)
        except (yaml.YAMLError, ValueError) as exc:
            failures.append((path.name, str(exc)))
            continue
        summaries.append((pair_id, summary))

    if failures:
        for name, err in failures:
            print(f"FAIL {name}: {err}", file=sys.stderr)
        return 1

    print(f"Validated {len(summaries)} pair(s):")
    for pair_id, summary in summaries:
        b = summary["breakdown"]
        print(
            f"  {pair_id:50s} certainty={summary['certainty']:6s}  "
            f"fields={summary['field_count']:3d}  "
            f"good={b['good']:3d} lossy={b['lossy']:3d} "
            f"unsupported={b['unsupported']:3d} N/A={b['not_applicable']:3d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
