"""Pin that the cross-mesh audit scores against the PRE-render source tree.

``process_cell`` performs ``parse -> render -> parse -> compare``.  ``render``
is not guaranteed to leave its argument alone: the three port-centric render
paths call ``project_vlan_to_switchport(tree)``
(``netcanon/migration/canonical/transforms.py``), which APPENDS synthesised
``CanonicalInterface`` records into the caller's tree **in place**.

Pre-fix bug (found 2026-09-23): the live tree sat on both sides of the
comparison, so for those cells the audit compared the target against a source
the render had just back-filled with exactly the records it was about to emit.
``interfaces`` matched *by construction*.  Measured scope: 15 of the 1339 cells
(five ``aruba_aoss`` fixtures x three targets).  The aggregate effect of
correcting it was ALIGNED -24, STRUCTURAL_ONLY +70, METHODOLOGY_under -19,
TRIVIAL_EMPTY -30, EXPECTED_LOSSY +3; CODEC_BUG was unchanged at 5.

Post-fix: ``process_cell`` deep-copies the source before rendering and scores
against the copy.

These assertions deliberately do NOT encode whether ``render`` mutates.  That
is current product behaviour, not a contract — asserting it would rot-fail the
moment someone makes the transform non-mutating (the trap recorded in
``feedback_documented_gap_dicts``).  What is pinned is the harness invariant:
the recorded source-side counts equal a FRESH parse of the fixture, whatever
render does to the tree it is handed.

See ``docs/reviews/2026-09-22-api-full-mesh/40-api-identity-settled.md``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNNER_PATH = _REPO_ROOT / "tools" / "run_full_mesh.py"
_spec = importlib.util.spec_from_file_location(
    "run_full_mesh_snapshot", _RUNNER_PATH,
)
assert _spec is not None and _spec.loader is not None
run_full_mesh = importlib.util.module_from_spec(_spec)
sys.modules["run_full_mesh_snapshot"] = run_full_mesh
_spec.loader.exec_module(run_full_mesh)


# An aruba_aoss capture whose VLAN port-membership lists name many ports that
# have no ``interface`` stanza of their own — the shape that makes the
# port-centric renderers synthesise, and the shape the bug hid behind.
_FIXTURE = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "real"
    / "aruba_aoss"
    / "user_contrib_2930m_wc1611.cfg"
)

# The three render paths that call project_vlan_to_switchport.
_SYNTHESISING_TARGETS = ("arista_eos", "cisco_iosxe_cli", "juniper_junos")


def _fresh_source_interface_count() -> int:
    raw = _FIXTURE.read_text(encoding="utf-8", errors="replace")
    return len(get_codec("aruba_aoss").parse(raw).interfaces)


def test_fixture_still_has_the_shape_this_test_depends_on() -> None:
    """Guard the guard: if the capture or the aruba parser changes so that
    the fixture no longer exercises synthesis, the assertions below would
    pass vacuously.  Fail loudly instead."""
    assert _FIXTURE.exists(), f"fixture moved: {_FIXTURE}"
    raw = _FIXTURE.read_text(encoding="utf-8", errors="replace")
    intent = get_codec("aruba_aoss").parse(raw)
    ports_named_by_vlans: set[str] = set()
    for vlan in intent.vlans:
        ports_named_by_vlans.update(vlan.tagged_ports)
        ports_named_by_vlans.update(vlan.untagged_ports)
    unbacked = ports_named_by_vlans - {i.name for i in intent.interfaces}
    assert unbacked, (
        "fixture no longer names VLAN member ports that lack an interface "
        "stanza — it can no longer trigger render-side synthesis, so this "
        "module would pass vacuously"
    )


@pytest.mark.parametrize("target_name", _SYNTHESISING_TARGETS)
def test_source_counts_match_a_fresh_parse(target_name: str) -> None:
    """The recorded source-side count is the fixture's own, not the
    render's back-fill."""
    expected = _fresh_source_interface_count()

    cell = run_full_mesh.process_cell(
        fixture_path=_FIXTURE,
        source_codec=get_codec("aruba_aoss"),
        source_codec_name="aruba_aoss",
        target_codec=get_codec(target_name),
        target_codec_name=target_name,
        fixture_kind="real",
    )

    assert cell["render_status"] == "ok", cell.get("error")
    record = cell["field_disposition"]["interfaces"]
    assert record["source_count"] == expected, (
        f"{target_name}: audit recorded source_count="
        f"{record['source_count']} but a fresh parse of the fixture yields "
        f"{expected} — the source snapshot was mutated by render()"
    )


@pytest.mark.parametrize("target_name", _SYNTHESISING_TARGETS)
def test_process_cell_does_not_leak_into_the_next_cell(
    target_name: str,
) -> None:
    """Two consecutive cells over one codec instance must record the same
    source counts.  Pins that nothing accumulates across calls."""
    kwargs = {
        "fixture_path": _FIXTURE,
        "source_codec": get_codec("aruba_aoss"),
        "source_codec_name": "aruba_aoss",
        "target_codec": get_codec(target_name),
        "target_codec_name": target_name,
        "fixture_kind": "real",
    }
    first = run_full_mesh.process_cell(**kwargs)
    second = run_full_mesh.process_cell(**kwargs)

    assert (
        first["field_disposition"]["interfaces"]["source_count"]
        == second["field_disposition"]["interfaces"]["source_count"]
    )
