#!/usr/bin/env python
"""
Cross-mesh translation fidelity runner (Phase 1 of the audit).

Walks every committed fixture (both real-world captures and synthetic
hand-authored kitchen-sinks) × every bidirectional codec in the registry,
performs ``target_codec.parse(target_codec.render(source_codec.parse(raw)))``,
and records per-canonical-field drift between the source-side canonical
tree and the round-tripped target-side canonical tree.

What this is
------------
A *mechanical* drift report.  It tells you which top-level
:class:`CanonicalIntent` fields survived a parse-render-parse trip
through each target codec, and which dropped or mutated.  It does NOT
yet tell you whether that drift is expected (target vendor genuinely
has no concept of feature X) or a codec defect.  Phase 3 of the audit
adds vendor-doc-grounded expectations to interpret the matrix; this
script is the foundation it consumes.

Operator usage
--------------

    python tools/run_full_mesh.py [--matrix]

Outputs a timestamped JSON file under
``tests/fixtures/real/_cross_mesh_runs/<timestamp>.json``.  Pass
``--matrix`` to ALSO regenerate ``tests/fixtures/real/CROSS_MESH_RESULTS.md``
from that JSON (the operator commits the .md manually; per-run JSON is
gitignored).

Architecture
------------
* Real fixture source-codec discovery mirrors
  ``tests/unit/migration/test_real_captures.py::_DIR_TO_CODEC_NAME``
  (human-short labels bridged to format-qualified codec names).
* Synthetic fixture discovery uses the directory name as the codec name
  directly — kitchen-sinks live at
  ``tests/fixtures/synthetic/<codec_name>/kitchen_sink.<ext>`` and the
  parent dir IS the registered ``CodecBase.name``.
* Target-codec discovery walks the codec registry and filters to
  ``direction == "bidirectional"`` (skips parse_only + the mock codec).
* Drift is computed via :func:`compute_field_disposition`, exposed for
  unit testing.
* "fields_unsupported_in_target" is derived from each target codec's
  ``CapabilityMatrix.unsupported`` declaration (vxlan_vnis declared
  unsupported on aruba_aoss → drift on that field is expected, not a
  codec bug).
* ``trivially_preserved`` flags — Wave 10α.  Per-field bool flagging
  cells where both source and target sides are in zero-state (empty
  list, empty dict, None / "" / 0 scalar).  Phase 4's reconciler routes
  these to ``TRIVIAL_EMPTY`` so they don't masquerade as
  ``METHODOLOGY_ISSUE_under``.
* ``subfields_with_data`` — Wave 10γ.  On list-parent records, the
  union of sub-field names that have non-empty data on at least one
  record across both sides.  Phase 4's sub-field cascade reads this
  set so a list with rows but no data on a given sub-field
  (e.g. ``interfaces`` populated but every row's ``switchport_mode``
  is None) routes to ``TRIVIAL_EMPTY``.

Constraints honoured
--------------------
* Standalone executable — no pytest dependency at runtime.
* Self-contained — no internet, no external API calls.
* Honest about misses — fixtures with no source-codec mapping are
  reported in the JSON's ``unmapped_fixtures`` field, not silently
  dropped.
* Idempotent — re-running produces a new timestamped JSON; the matrix
  .md gets overwritten when ``--matrix`` is passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make repo root importable when invoked directly via
# ``python tools/run_full_mesh.py`` from any working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Side-effect imports register every codec with the registry.
from netcanon.migration.codecs import (  # noqa: E402, F401
    arista_eos,
    aruba_aoss,
    cisco_iosxe,
    cisco_iosxe_cli,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
)
from netcanon.migration.codecs.base import CodecBase  # noqa: E402
from netcanon.migration.codecs.registry import (  # noqa: E402
    get_codec,
    list_codecs,
)
from netcanon.migration.canonical.intent import CanonicalIntent  # noqa: E402


REAL_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "real"
SYNTHETIC_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "synthetic"
RUNS_DIR = REAL_FIXTURES_ROOT / "_cross_mesh_runs"
MATRIX_PATH = REAL_FIXTURES_ROOT / "CROSS_MESH_RESULTS.md"


# Mirror of test_real_captures.py::_DIR_TO_CODEC_NAME.  Replicated rather
# than imported so this script can run without the test harness in scope
# (and so the script itself is honest about which fixture directories it
# knows how to source-classify).
_DIR_TO_CODEC_NAME: dict[str, str] = {
    "cisco_iosxe":  "cisco_iosxe_cli",
    "aruba_aoss":   "aruba_aoss",
    "fortigate":    "fortigate_cli",
    "opnsense":     "opnsense",
    "mikrotik":     "mikrotik_routeros",
    "arista_eos":   "arista_eos",
    "junos":        "juniper_junos",
}

#: Per-vendor native fixture extensions.  Mirrors the filter in
#: ``test_real_captures.py::_discover_fixtures``.
_FIXTURE_EXTENSIONS = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}


# Top-level CanonicalIntent fields we audit drift on.  Intentionally
# excludes the metadata fields (source_vendor / source_format /
# source_version) — those describe WHICH parser ran, not what survived.
_AUDITED_FIELDS: tuple[str, ...] = (
    "hostname",
    "domain",
    "dns_servers",
    "ntp_servers",
    "timezone",
    "syslog_servers",
    "interfaces",
    "vlans",
    "static_routes",
    "dhcp_servers",
    "snmp",
    "lags",
    "local_users",
    "radius_servers",
    "vxlan_vnis",
    "evpn_type5_routes",
    "routing_instances",
    "raw_sections",
    "apply_groups",
    "group_content",
)


# Mapping from canonical field name → the prefix used by the codec's
# CapabilityMatrix.unsupported xpaths.  When EVERY xpath under that
# prefix is declared unsupported, the field is considered "unsupported
# by design" for the target — drift on it is expected, not a defect.
#
# Matches the existing xpath shapes in the codec capability matrices
# (see e.g. aruba_aoss declaring ``/vxlan-vnis/vni`` +
# ``/vxlan-vnis/source-interface`` + ``/vxlan-vnis/udp-port``).
_FIELD_TO_XPATH_PREFIX: dict[str, str] = {
    "vxlan_vnis": "/vxlan-vnis/",
    "evpn_type5_routes": "/evpn-type5/",
    "routing_instances": "/routing-instances/",
    # Other fields don't have a stable xpath-prefix convention in the
    # current matrix — leave them keyed only by direct equality below.
}


# ---------------------------------------------------------------------------
# Field-comparison helpers
# ---------------------------------------------------------------------------


def _normalise_records(items: list[dict[str, Any]], id_keys: list[str]) -> list[dict[str, Any]]:
    """Sort a list of dict records by the first available identity key
    so set-equality comparison is order-independent.

    Mirrors the sort logic used by ``test_real_captures.py::_compare``.
    """
    def _key(rec: dict[str, Any]) -> str:
        for k in id_keys:
            v = rec.get(k)
            if v is not None and v != "":
                return str(v)
        # Fallback — JSON-serialise the whole record for a stable order.
        return json.dumps(rec, sort_keys=True, default=str)
    return sorted(items, key=_key)


# Per-list-field identity keys (the "natural" key by which two records
# are considered the same record).  Mirrors ``test_real_captures.py::
# _compare`` so this script speaks the same drift vocabulary the rest
# of the test corpus does.
_LIST_ID_KEYS: dict[str, list[str]] = {
    "interfaces":         ["name"],
    "vlans":              ["id", "name"],
    "static_routes":      ["destination"],
    "lags":               ["name"],
    "dhcp_servers":       ["network"],
    "local_users":        ["name"],
    "radius_servers":     ["host"],
    "vxlan_vnis":         ["vni", "vlan_id"],
    "evpn_type5_routes":  ["prefix", "vrf"],
    "routing_instances":  ["name"],
}


def _set_equal_lists(a: list[Any], b: list[Any]) -> bool:
    """Set-equality comparison for two lists, treating elements as
    equal when their JSON serialisations match (handles dicts, scalars,
    nested lists)."""
    norm_a = sorted(json.dumps(x, sort_keys=True, default=str) for x in a)
    norm_b = sorted(json.dumps(x, sort_keys=True, default=str) for x in b)
    return norm_a == norm_b


def _scalar_summary(value: Any) -> Any:
    """Render a scalar / list / dict value into a JSON-friendly summary.

    Lists of dicts get truncated to the first three records to keep the
    JSON output legible; scalars pass through.  Phase 4 can re-derive
    full state from the source fixture if needed — this summary is
    operator-readable, not lossless.
    """
    if isinstance(value, list):
        if not value:
            return []
        if len(value) <= 3:
            return value
        return value[:3] + [f"... and {len(value) - 3} more"]
    return value


# ---------------------------------------------------------------------------
# Per-field drift computation
# ---------------------------------------------------------------------------


def compute_field_disposition(
    source: CanonicalIntent,
    target: CanonicalIntent,
    target_unsupported_xpaths: Iterable[str] = (),
) -> dict[str, Any]:
    """Compare two canonical intents field-by-field.

    Returns a dict keyed by canonical-intent field name with each value
    being a dict carrying:

    * ``preserved`` — bool (True iff the field round-tripped intact)
    * ``unsupported_in_target`` — bool (True iff the target codec
      declares this field's xpath family as unsupported by design)
    * ``source`` / ``target`` — JSON-friendly summaries (truncated for
      large lists; the operator can drill into the source fixture if
      they need the full state)
    * ``source_count`` / ``target_count`` — for list fields
    * ``drift`` — narrowest-possible explanation of WHAT drifted (e.g.
      ``"all VNIs dropped"``, ``"vlans[0].name: 'Tenant_100' → ''"``)

    The function is pure and platform-agnostic — unit-tested via
    ``tests/unit/audit/test_run_full_mesh.py``.
    """
    src_dump = source.model_dump()
    tgt_dump = target.model_dump()
    unsupported_xpaths = list(target_unsupported_xpaths)

    out: dict[str, Any] = {}
    for field in _AUDITED_FIELDS:
        src_val = src_dump.get(field)
        tgt_val = tgt_dump.get(field)

        # Determine whether the target codec has declared this field
        # family as unsupported by design.  Exact-match against direct
        # field names AND prefix-match against the documented prefix
        # convention for the schema-extension fields.
        unsupported = False
        prefix = _FIELD_TO_XPATH_PREFIX.get(field)
        if prefix:
            unsupported = any(
                xp.startswith(prefix) for xp in unsupported_xpaths
            )
        # Also accept exact xpath ``/<field>`` — some codecs declare at
        # field level rather than per-leaf.
        if not unsupported:
            unsupported = f"/{field}" in unsupported_xpaths

        record: dict[str, Any] = {
            "unsupported_in_target": unsupported,
        }

        if isinstance(src_val, list) and isinstance(tgt_val, list):
            id_keys = _LIST_ID_KEYS.get(field, [])
            if id_keys:
                norm_src = _normalise_records(src_val, id_keys)
                norm_tgt = _normalise_records(tgt_val, id_keys)
                preserved = norm_src == norm_tgt
            else:
                preserved = _set_equal_lists(src_val, tgt_val)
            record["preserved"] = preserved
            record["source_count"] = len(src_val)
            record["target_count"] = len(tgt_val)
            # Wave 10γ: list parent-records carry the union of sub-field
            # names that have non-empty data on at least one record across
            # BOTH sides.  Phase 4's sub-field cascade consults this set
            # so a list with rows but no data on a particular sub-field
            # (e.g. ``interfaces`` populated but every row's
            # ``switchport_mode`` is None) routes to TRIVIAL_EMPTY rather
            # than ALIGNED / METHODOLOGY_under.  Empty lists skip the
            # field — the parent's ``trivially_preserved`` flag already
            # drives the cascade.
            if src_val or tgt_val:
                record["subfields_with_data"] = _subfields_with_data(
                    src_val, tgt_val,
                )
            if preserved and not src_val and not tgt_val:
                # Both lists empty — preservation is trivial; the YAML's
                # disposition claim couldn't be tested against any data.
                # Phase 4 routes these to TRIVIAL_EMPTY so they don't
                # masquerade as METHODOLOGY_ISSUE_under noise.  See
                # Wave 10α.
                record["trivially_preserved"] = True
            if not preserved:
                drift = _list_drift_summary(field, src_val, tgt_val)
                record["drift"] = drift
                record["source"] = _scalar_summary(src_val)
                record["target"] = _scalar_summary(tgt_val)
        elif isinstance(src_val, dict) and isinstance(tgt_val, dict):
            preserved = src_val == tgt_val
            record["preserved"] = preserved
            record["source_count"] = len(src_val)
            record["target_count"] = len(tgt_val)
            if preserved and not src_val and not tgt_val:
                # Both dicts empty — same semantics as the empty-list
                # case above.  See Wave 10α.
                record["trivially_preserved"] = True
            if not preserved:
                record["drift"] = _dict_drift_summary(src_val, tgt_val)
                # Store the FULL source/target dicts (not key-lists) so
                # the Phase 4 reconciler's ``_subfield_drift_in_dict``
                # can resolve per-attribute drift instead of bailing
                # out and conservatively flagging every attribute as
                # drifted.  Without this, a single ``snmp.v3_users``
                # difference manifested as four spurious CODEC_BUG
                # cells (community / location / contact / trap_hosts)
                # for cross-vendor pairs that actually preserved those
                # scalars — see Wave 9 α.  The display layer
                # (``_md_inline``) JSON-serialises and truncates dicts
                # to 200 chars, so size impact on the matrix .md is
                # bounded.
                record["source"] = src_val
                record["target"] = tgt_val
        else:
            # Scalar or None vs structured.  None-vs-empty is treated
            # as preserved (the canonical model uses None for "snmp
            # never declared" but renders as missing — semantically the
            # same as an empty surface).
            preserved = _scalar_equal(src_val, tgt_val)
            record["preserved"] = preserved
            if preserved and _is_empty_zero_state(src_val) and _is_empty_zero_state(tgt_val):
                # Both scalars in their zero state (None / "" / 0 / []).
                # Same TRIVIAL_EMPTY semantics — see Wave 10α.
                record["trivially_preserved"] = True
            if not preserved:
                record["source"] = _scalar_summary(src_val)
                record["target"] = _scalar_summary(tgt_val)
                record["drift"] = (
                    f"{field}: {src_val!r} → {tgt_val!r}"
                )

        out[field] = record

    return out


def _subfields_with_data(
    src: list[Any], tgt: list[Any],
) -> list[str]:
    """Return a sorted list of sub-field names that have non-empty data
    on at least one record across the union of ``src`` and ``tgt``.

    Used by :func:`compute_field_disposition` to populate the
    ``subfields_with_data`` field on list parent-records (Wave 10γ).
    Phase 4's sub-field cascade reads this set to detect the case where
    a parent list has rows but a particular sub-field is empty on every
    row — those sub-fields cascade to TRIVIAL_EMPTY rather than
    masquerading as METHODOLOGY_under.

    Non-dict records (e.g. ``dns_servers`` is a list of strings) carry
    no addressable sub-fields; this returns ``[]`` in that case so the
    cascade falls back to plain ``preserved``.
    """
    out: set[str] = set()
    for rec in (*src, *tgt):
        if not isinstance(rec, dict):
            continue
        for k, v in rec.items():
            if not _is_empty_zero_state(v):
                out.add(k)
    return sorted(out)


def _is_empty_zero_state(value: Any) -> bool:
    """True iff ``value`` is in its zero state — None, empty string,
    integer zero, or an empty list / dict / set / tuple.

    Used by :func:`compute_field_disposition` to flag the Wave 10α
    ``trivially_preserved`` case: both source and target sides have NO
    data on this field, so the cell aligns benignly by absence rather
    than by real round-trip preservation.  Phase 4 routes these to
    TRIVIAL_EMPTY so they stop polluting METHODOLOGY_ISSUE_under.

    Mixed-type defence mirrors :func:`_scalar_equal`: unhashable
    container values are checked via ``len`` rather than membership.
    """
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value) == 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 0
    return False


def _scalar_equal(a: Any, b: Any) -> bool:
    """Semantic scalar equality treating None / "" / empty-list as
    equivalent zero-states.  Reflects how codecs handle 'unset'.

    Defends against mixed-type inputs (e.g. one side returns a None
    while the other returns an empty dict from a Pydantic model dump):
    the membership test against ``empty`` only fires for hashable
    values, so unhashables like dicts / lists fall through to the
    final ``return False``.
    """
    if a == b:
        return True
    empties_hashable = {None, "", 0}
    try:
        if a in empties_hashable and b in empties_hashable:
            return True
    except TypeError:
        # Unhashable types (dict, list) — not part of the empties set.
        pass
    return False


def _list_drift_summary(
    field: str, src: list[Any], tgt: list[Any],
) -> Any:
    """Produce a compact human-readable explanation of HOW two lists
    diverged."""
    if src and not tgt:
        return f"all {len(src)} {field} dropped"
    if not src and tgt:
        return f"{len(tgt)} {field} appeared in target (parser bug?)"
    if len(src) != len(tgt):
        return (
            f"count drift: {len(src)} → {len(tgt)} "
            f"({field})"
        )
    # Same count — drill down to find which records differ.
    id_keys = _LIST_ID_KEYS.get(field, [])
    if id_keys and src and isinstance(src[0], dict):
        per_record: dict[str, Any] = {}
        norm_src = _normalise_records(src, id_keys)
        norm_tgt = _normalise_records(tgt, id_keys)
        for i, (s, t) in enumerate(zip(norm_src, norm_tgt)):
            if s != t:
                diff_fields = sorted(set(s.keys()) | set(t.keys()))
                diffs: dict[str, Any] = {}
                for k in diff_fields:
                    if s.get(k) != t.get(k):
                        diffs[k] = {
                            "source": _scalar_summary(s.get(k)),
                            "target": _scalar_summary(t.get(k)),
                        }
                # Identify which record this is by its id keys.
                ident = {k: s.get(k) for k in id_keys}
                per_record[f"{field}[{i}] {ident}"] = diffs
        # No cap on the drill-down — Phase 4's per-record drilldown
        # consumes this dict and earlier capping at 5 records hid
        # genuine sub-field drift on records 6+ (Wave 10β-A reported
        # the leaf2a fixture saturating the cap with 5 LAG drifts and
        # masking switchport_mode drifts on later records).
        # The matrix .md output's display-side truncation
        # (``_md_inline``) handles legibility — data capture must stay
        # lossless so Phase 4 sees every drift signal.
        return per_record
    return "list contents differ"


def _dict_drift_summary(src: dict[str, Any], tgt: dict[str, Any]) -> Any:
    """Compact summary of dict-vs-dict drift (e.g. raw_sections)."""
    only_src = sorted(set(src.keys()) - set(tgt.keys()))
    only_tgt = sorted(set(tgt.keys()) - set(src.keys()))
    common_diff = [
        k for k in (set(src.keys()) & set(tgt.keys()))
        if src[k] != tgt[k]
    ]
    return {
        "only_in_source": only_src[:5] + (
            ["...more"] if len(only_src) > 5 else []
        ),
        "only_in_target": only_tgt[:5] + (
            ["...more"] if len(only_tgt) > 5 else []
        ),
        "value_drift_keys": common_diff[:5] + (
            ["...more"] if len(common_diff) > 5 else []
        ),
    }


# ---------------------------------------------------------------------------
# Per-cell processing
# ---------------------------------------------------------------------------


def _summary_counts(
    field_disposition: dict[str, Any],
) -> dict[str, int]:
    total = len(field_disposition)
    preserved = sum(
        1 for r in field_disposition.values() if r.get("preserved")
    )
    unsupported_only = sum(
        1 for r in field_disposition.values()
        if not r.get("preserved") and r.get("unsupported_in_target")
    )
    drifted = sum(
        1 for r in field_disposition.values()
        if not r.get("preserved") and not r.get("unsupported_in_target")
    )
    return {
        "fields_total": total,
        "fields_preserved": preserved,
        "fields_drifted": drifted,
        "fields_unsupported_in_target": unsupported_only,
    }


def process_cell(
    fixture_path: Path,
    source_codec: CodecBase,
    source_codec_name: str,
    target_codec: CodecBase,
    target_codec_name: str,
    fixture_kind: str = "real",
) -> dict[str, Any]:
    """Run one (fixture, target_codec) cell.  Always returns a record;
    exceptions get captured into the record rather than propagating.

    ``fixture_kind`` is ``"real"`` for real-world captures or
    ``"synthetic"`` for hand-authored kitchen-sink fixtures.  Recorded
    on the cell so downstream consumers (the matrix renderer, future
    drift-trend tooling) can group and display them separately.
    """
    rel_fixture = fixture_path.relative_to(_REPO_ROOT).as_posix()
    cell: dict[str, Any] = {
        "fixture": rel_fixture,
        "fixture_kind": fixture_kind,
        "source_codec": source_codec_name,
        "target_codec": target_codec_name,
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
    }

    raw = fixture_path.read_text(encoding="utf-8", errors="replace")
    t0 = time.perf_counter()

    try:
        canonical_source = source_codec.parse(raw)
    except Exception as exc:  # noqa: BLE001 — runner is best-effort
        cell["render_status"] = "source_parse_error"
        cell["roundtrip_parse_status"] = "skipped"
        cell["error"] = f"source parse failed: {exc!r}"
        cell["traceback"] = traceback.format_exc(limit=4)
        cell["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return cell

    try:
        rendered = target_codec.render(canonical_source)
    except Exception as exc:  # noqa: BLE001
        cell["render_status"] = "render_error"
        cell["roundtrip_parse_status"] = "skipped"
        cell["error"] = f"render failed: {exc!r}"
        cell["traceback"] = traceback.format_exc(limit=4)
        cell["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return cell

    try:
        canonical_target = target_codec.parse(rendered)
    except Exception as exc:  # noqa: BLE001
        cell["roundtrip_parse_status"] = "parse_error"
        cell["error"] = f"reparse failed: {exc!r}"
        cell["traceback"] = traceback.format_exc(limit=4)
        cell["rendered_preview"] = rendered[:400]
        cell["duration_ms"] = int((time.perf_counter() - t0) * 1000)
        return cell

    target_unsupported = [
        u.path for u in target_codec.capabilities.unsupported
    ]
    field_disposition = compute_field_disposition(
        canonical_source, canonical_target, target_unsupported,
    )
    cell["field_disposition"] = field_disposition
    cell["summary"] = _summary_counts(field_disposition)
    cell["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    return cell


def cell_status(cell: dict[str, Any]) -> str:
    """Classify a cell into one of {OK, WARN, RENDER, PARSE, SOURCE}.

    * ``RENDER`` — render raised
    * ``PARSE``  — re-parse raised (render produced invalid syntax)
    * ``SOURCE`` — the source codec couldn't even parse its own fixture
    * ``OK``     — every field preserved (or unsupported-by-design)
    * ``WARN``   — at least one field drifted that ISN'T declared
                   unsupported by the target
    """
    if cell["render_status"] == "render_error":
        return "RENDER"
    if cell["render_status"] == "source_parse_error":
        return "SOURCE"
    if cell["roundtrip_parse_status"] == "parse_error":
        return "PARSE"
    summary = cell.get("summary", {})
    if summary.get("fields_drifted", 0) == 0:
        return "OK"
    return "WARN"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_fixtures() -> tuple[list[tuple[str, Path, str]], list[str]]:
    """Walk both fixture roots and return:
    * ``[(source_codec_name, fixture_path, fixture_kind), ...]`` for
      every recognised fixture, where ``fixture_kind`` is ``"real"`` or
      ``"synthetic"``
    * ``[unmapped_dir_path, ...]`` — directories present on disk but
      missing a known codec mapping (honest about misses)

    Discovery details
    -----------------
    * ``tests/fixtures/real/<vendor>/`` uses the human-short labels
      (``fortigate`` / ``mikrotik`` / ``junos``) bridged via
      ``_DIR_TO_CODEC_NAME`` to format-qualified codec names.
    * ``tests/fixtures/synthetic/<codec>/`` uses the registered codec
      name directly as the directory name (matches ``CodecBase.name``)
      — no translation table needed.  Each kitchen-sink fixture is
      named ``kitchen_sink.<ext>`` and the codec name is the parent
      directory name.
    """
    out: list[tuple[str, Path, str]] = []
    unmapped: list[str] = []

    # Real captures.
    for vendor_dir in sorted(REAL_FIXTURES_ROOT.iterdir()):
        if not vendor_dir.is_dir() or vendor_dir.name.startswith("_"):
            continue
        codec_name = _DIR_TO_CODEC_NAME.get(vendor_dir.name)
        if codec_name is None:
            unmapped.append(f"real/{vendor_dir.name}")
            continue
        for path in sorted(vendor_dir.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in _FIXTURE_EXTENSIONS:
                continue
            out.append((codec_name, path, "real"))

    # Synthetic kitchen-sinks.  Directory name IS the codec name —
    # one fixture per codec so no per-vendor translation table is
    # needed.  An unrecognised codec name surfaces in unmapped rather
    # than silently dropping coverage.
    if SYNTHETIC_FIXTURES_ROOT.is_dir():
        registered = set(list_codecs())
        for codec_dir in sorted(SYNTHETIC_FIXTURES_ROOT.iterdir()):
            if not codec_dir.is_dir() or codec_dir.name.startswith("_"):
                continue
            codec_name = codec_dir.name
            if codec_name not in registered:
                unmapped.append(f"synthetic/{codec_dir.name}")
                continue
            for path in sorted(codec_dir.iterdir()):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if path.suffix.lower() not in _FIXTURE_EXTENSIONS:
                    continue
                out.append((codec_name, path, "synthetic"))

    return out, unmapped


def discover_target_codecs() -> list[str]:
    """Return registered codec names that are bidirectional (skip
    parse-only codecs and the mock codec)."""
    out: list[str] = []
    for name in list_codecs():
        if name == "mock":
            continue
        codec = get_codec(name)
        direction = getattr(codec.__class__, "direction", "bidirectional")
        if direction != "bidirectional":
            continue
        out.append(name)
    return sorted(out)


# ---------------------------------------------------------------------------
# Run orchestration + JSON output
# ---------------------------------------------------------------------------


def run_full_mesh() -> dict[str, Any]:
    """Run every (fixture, target_codec) cell and return the structured
    result as a Python dict."""
    fixtures, unmapped = discover_fixtures()
    targets = discover_target_codecs()
    cells: list[dict[str, Any]] = []
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    for source_codec_name, fixture_path, fixture_kind in fixtures:
        source_codec = get_codec(source_codec_name)
        for target_name in targets:
            target_codec = get_codec(target_name)
            cell = process_cell(
                fixture_path=fixture_path,
                source_codec=source_codec,
                source_codec_name=source_codec_name,
                target_codec=target_codec,
                target_codec_name=target_name,
                fixture_kind=fixture_kind,
            )
            cells.append(cell)
    duration_s = round(time.perf_counter() - t0, 2)
    real_fixture_count = sum(1 for _, _, k in fixtures if k == "real")
    synthetic_fixture_count = sum(
        1 for _, _, k in fixtures if k == "synthetic"
    )
    return {
        "started_utc": started,
        "duration_s": duration_s,
        "cells_total": len(cells),
        "fixtures_count": len(fixtures),
        "real_fixtures_count": real_fixture_count,
        "synthetic_fixtures_count": synthetic_fixture_count,
        "targets_count": len(targets),
        "unmapped_fixture_dirs": unmapped,
        "targets": targets,
        "cells": cells,
    }


def write_json(result: dict[str, Any]) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RUNS_DIR / f"{timestamp}.json"
    out_path.write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    return out_path


# ---------------------------------------------------------------------------
# Markdown matrix rendering
# ---------------------------------------------------------------------------


def render_matrix_md(result: dict[str, Any]) -> str:
    """Render the structured run result as the human-readable
    ``CROSS_MESH_RESULTS.md`` body.

    Two matrices are emitted: the real-capture matrix (carrier configs,
    Batfish kitchen-sinks, vendor-published examples) and the synthetic
    kitchen-sink matrix (one hand-authored fixture per codec exercising
    every CapabilityMatrix-supported field).  Each gets its own
    fixture × target grid and its own drill-down section below.

    Real and synthetic fixtures answer different questions:

    * Real: "what survives translation when the source operator picked
      a partial slice of features?"  — driven by what's in the wild.
    * Synthetic: "what survives translation when EVERY supported field
      is exercised at once?"  — driven by capability matrices.

    Mixing them in one matrix would conflate "feature absent in source"
    with "feature dropped in translation", so they live in separate
    sections with separate drill-downs.
    """
    targets: list[str] = result["targets"]
    cells: list[dict[str, Any]] = result["cells"]

    real_cells = [c for c in cells if c.get("fixture_kind", "real") == "real"]
    synthetic_cells = [
        c for c in cells if c.get("fixture_kind") == "synthetic"
    ]

    real_fixtures_n = result.get(
        "real_fixtures_count",
        len({c["fixture"] for c in real_cells}),
    )
    synthetic_fixtures_n = result.get(
        "synthetic_fixtures_count",
        len({c["fixture"] for c in synthetic_cells}),
    )

    lines: list[str] = []
    lines.append("# Cross-mesh translation fidelity matrix\n")
    lines.append(
        f"Generated by `tools/run_full_mesh.py` on {result['started_utc']}.  "
        f"Run took {result['duration_s']}s for {result['cells_total']} cells "
        f"({real_fixtures_n} real + {synthetic_fixtures_n} synthetic fixtures "
        f"× {result['targets_count']} bidirectional targets)."
        "\n"
    )
    lines.append(
        "**This is mechanical drift only — Phase 3 of the audit will add "
        "vendor-doc-grounded expectations to interpret which drift is "
        "expected vs which is a codec defect.**  See "
        "`tests/fixtures/cross_vendor_expectations.yaml` (planned) for "
        "the eventual ground truth.  Until then, treat every WARN cell "
        "as 'unverified' rather than 'broken'.\n"
    )
    if result.get("unmapped_fixture_dirs"):
        lines.append(
            "Fixture directories present on disk with no source-codec "
            f"mapping: {result['unmapped_fixture_dirs']}.  Add them to "
            "`tools/run_full_mesh.py::_DIR_TO_CODEC_NAME` (real) or to "
            "the codec registry (synthetic) to bring them into the audit.\n"
        )

    lines.append("## Cell legend\n")
    lines.append(
        "- `OK N/M` — N of M canonical fields preserved through the round-trip.\n"
        "- `WARN N/M` — render succeeded but some field drifted that the "
        "target does NOT declare as unsupported by design.\n"
        "- `RENDER` — `target_codec.render()` raised an exception (codec bug).\n"
        "- `PARSE` — `target_codec.parse()` of the rendered output raised "
        "(render emitted invalid syntax — codec bug).\n"
        "- `SOURCE` — source codec couldn't parse its own fixture (parser regression).\n"
        "- The `N/M` count includes `fields_unsupported_in_target` as 'preserved' "
        "for cell-status purposes; per-field unsupported declarations show in the drill-down.\n"
    )

    # ---- Real-capture matrix ----
    lines.append("## Real-capture coverage matrix\n")
    lines.append(
        "Real configs from carriers, Batfish parser tests, and "
        "vendor-published examples.  Source slice is whatever the "
        "original operator chose to deploy — feature absence in a row "
        "doesn't mean the codec can't handle it, just that the fixture "
        "doesn't exercise it.  Use the synthetic matrix below to gauge "
        "feature-complete fidelity.\n"
    )
    lines.extend(
        _render_grid(real_cells, targets, prefix_strip="tests/fixtures/real/")
    )

    if synthetic_cells:
        lines.append("## Synthetic kitchen-sink coverage matrix\n")
        lines.append(
            "One hand-authored fixture per codec exercising every "
            "field the codec's :class:`CapabilityMatrix` declares as "
            "``supported`` or ``lossy``.  Drift here reflects the "
            "WORST-CASE feature-complete cross-translation; rows in "
            "the real matrix should be a strict subset of what the "
            "corresponding synthetic row hits.\n"
        )
        lines.extend(
            _render_grid(
                synthetic_cells,
                targets,
                prefix_strip="tests/fixtures/synthetic/",
            )
        )

    # ---- Roll-up: top drifted (source, target) pairs ----
    lines.append("## Top drifted (source codec → target codec) pairs\n")
    lines.append(
        "Combined across both matrices.  Sums every WARN cell's "
        "``fields_drifted`` count over all (source, target) pair "
        "occurrences.\n"
    )
    pair_drift: dict[tuple[str, str], int] = {}
    for c in cells:
        s = c["summary"] if "summary" in c else None
        if s is None:
            continue
        key = (c["source_codec"], c["target_codec"])
        pair_drift[key] = pair_drift.get(key, 0) + s.get(
            "fields_drifted", 0
        )
    top_pairs = sorted(
        pair_drift.items(), key=lambda kv: kv[1], reverse=True,
    )[:10]
    lines.append("| Rank | Source codec | Target codec | Σ drifted fields |")
    lines.append("|---:|---|---|---:|")
    for rank, ((src, tgt), n) in enumerate(top_pairs, start=1):
        lines.append(f"| {rank} | {src} | {tgt} | {n} |")
    lines.append("")

    if synthetic_cells:
        lines.append(
            "### Top drifted pairs — synthetic submatrix only\n"
        )
        lines.append(
            "Same roll-up but restricted to the synthetic kitchen-sink "
            "cells.  These pairs see EVERY supported field at once, so "
            "drift here is the most sensitive signal of codec "
            "translation gaps.\n"
        )
        synth_pair_drift: dict[tuple[str, str], int] = {}
        for c in synthetic_cells:
            s = c.get("summary")
            if s is None:
                continue
            key = (c["source_codec"], c["target_codec"])
            synth_pair_drift[key] = synth_pair_drift.get(
                key, 0,
            ) + s.get("fields_drifted", 0)
        top_synth = sorted(
            synth_pair_drift.items(), key=lambda kv: kv[1], reverse=True,
        )[:10]
        lines.append(
            "| Rank | Source codec | Target codec | Σ drifted fields |"
        )
        lines.append("|---:|---|---|---:|")
        for rank, ((src, tgt), n) in enumerate(top_synth, start=1):
            lines.append(f"| {rank} | {src} | {tgt} | {n} |")
        lines.append("")

    # ---- Per-cell drill-downs (real) ----
    lines.append("## Per-cell drill-downs — real captures\n")
    real_drill = [c for c in real_cells if cell_status(c) != "OK"]
    if not real_drill:
        lines.append("Every real-capture cell preserved every field.\n")
    else:
        lines.append(
            f"One section per non-OK real-capture cell ({len(real_drill)} "
            "total).  Sections are ordered by source fixture then target codec.\n"
        )
        for c in sorted(
            real_drill, key=lambda x: (x["fixture"], x["target_codec"]),
        ):
            lines.extend(_render_cell_drilldown(c))

    # ---- Per-cell drill-downs (synthetic) ----
    if synthetic_cells:
        lines.append("## Per-cell drill-downs — synthetic kitchen-sinks\n")
        synth_drill = [
            c for c in synthetic_cells if cell_status(c) != "OK"
        ]
        if not synth_drill:
            lines.append(
                "Every synthetic kitchen-sink cell preserved every field.\n"
            )
        else:
            lines.append(
                f"One section per non-OK synthetic cell "
                f"({len(synth_drill)} total).  Sections are ordered by "
                "source fixture then target codec.\n"
            )
            for c in sorted(
                synth_drill,
                key=lambda x: (x["fixture"], x["target_codec"]),
            ):
                lines.extend(_render_cell_drilldown(c))

    return "\n".join(lines) + "\n"


def _render_grid(
    cells: list[dict[str, Any]],
    targets: list[str],
    prefix_strip: str,
) -> list[str]:
    """Render a fixture × target grid for a subset of cells.  Pulled
    out of ``render_matrix_md`` so the same code drives both the real
    and synthetic submatrices.
    """
    if not cells:
        return ["(no fixtures in this category)\n"]
    by_key: dict[tuple[str, str], dict[str, Any]] = {
        (c["fixture"], c["target_codec"]): c for c in cells
    }
    fixtures = sorted({c["fixture"] for c in cells})
    out: list[str] = []
    header = ["Source fixture"] + targets
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "|".join(["---"] * len(header)) + "|")
    for fx in fixtures:
        row = [fx.removeprefix(prefix_strip)]
        for tgt in targets:
            cell = by_key.get((fx, tgt))
            if cell is None:
                row.append("—")
                continue
            status = cell_status(cell)
            if status in ("OK", "WARN"):
                summary = cell.get("summary", {})
                preserved = (
                    summary.get("fields_preserved", 0)
                    + summary.get("fields_unsupported_in_target", 0)
                )
                total = summary.get("fields_total", 0)
                row.append(f"{status} {preserved}/{total}")
            else:
                row.append(status)
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    return out


def _render_cell_drilldown(cell: dict[str, Any]) -> list[str]:
    """Render a single cell's per-field drift breakdown."""
    out: list[str] = []
    fx = cell["fixture"]
    for prefix in ("tests/fixtures/real/", "tests/fixtures/synthetic/"):
        if fx.startswith(prefix):
            fx = fx[len(prefix):]
            break
    tgt = cell["target_codec"]
    status = cell_status(cell)
    if status in ("OK", "WARN"):
        summary = cell.get("summary", {})
        preserved = (
            summary.get("fields_preserved", 0)
            + summary.get("fields_unsupported_in_target", 0)
        )
        total = summary.get("fields_total", 0)
        header = f"### {fx} → {tgt}  ({status} {preserved}/{total})"
    else:
        header = f"### {fx} → {tgt}  ({status})"
    out.append(header)
    out.append("")
    if status in ("RENDER", "PARSE", "SOURCE"):
        out.append(f"**Error:** {cell.get('error', '(no detail)')}")
        out.append("")
        if cell.get("traceback"):
            out.append("```")
            out.append(cell["traceback"].strip())
            out.append("```")
            out.append("")
        if cell.get("rendered_preview"):
            out.append("**Rendered preview (first 400 chars):**")
            out.append("```")
            out.append(cell["rendered_preview"])
            out.append("```")
            out.append("")
        return out
    # WARN cells: per-field disposition table.
    out.append("| Field | Disposition | Source | Target | Drift |")
    out.append("|---|---|---|---|---|")
    for field, rec in cell.get("field_disposition", {}).items():
        if rec.get("preserved"):
            disposition = "OK"
        elif rec.get("unsupported_in_target"):
            disposition = "UNSUPPORTED (by design)"
        else:
            disposition = "DRIFT"
        if disposition == "OK":
            continue  # only show the interesting rows
        src_summary = _md_inline(rec.get("source"))
        tgt_summary = _md_inline(rec.get("target"))
        drift = _md_inline(rec.get("drift"))
        out.append(
            f"| {field} | {disposition} | {src_summary} | {tgt_summary} | {drift} |"
        )
    out.append("")
    return out


def _md_inline(value: Any) -> str:
    """Format a value for inline markdown table display."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        s = json.dumps(value, default=str)
    else:
        s = str(value)
    s = s.replace("|", "\\|").replace("\n", " ")
    if len(s) > 200:
        s = s[:197] + "..."
    return s


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the cross-mesh translation fidelity audit.",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help=(
            "Also (re)generate tests/fixtures/real/CROSS_MESH_RESULTS.md "
            "from the run output."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress prints; only emit the final JSON path.",
    )
    args = parser.parse_args(argv)

    if not args.quiet:
        print("Running cross-mesh fidelity audit...", file=sys.stderr)

    result = run_full_mesh()
    json_path = write_json(result)

    if not args.quiet:
        print(
            f"Wrote {result['cells_total']} cells in "
            f"{result['duration_s']}s to {json_path}",
            file=sys.stderr,
        )

    if args.matrix:
        body = render_matrix_md(result)
        MATRIX_PATH.write_text(body, encoding="utf-8")
        if not args.quiet:
            print(f"Wrote matrix to {MATRIX_PATH}", file=sys.stderr)

    print(json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
