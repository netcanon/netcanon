"""Every kitchen-sink fixture must have an assertion module beside it.

A synthetic ``kitchen_sink.*`` fixture reached only by the shared round-trip
sweep proves canonical *stability*, not *correctness*: if the fixture lost a
surface, the round-trip would still pass on the smaller tree and every
content assertion elsewhere reads inline sample strings instead.  The
per-codec ``test_synthetic_<codec>_kitchen_sink.py`` modules exist to close
that hole by asserting each fixture's CONTENT.

That set drifted once already.  The 2026-09-21 audit measured 13 fixtures
against 9 assertion modules — the four newest codecs (``aruba_aoscx``,
``cisco_iosxr``, ``cisco_nxos``, ``vyos``) shipped fixtures with no content
coverage, and nothing failed.  The gap closed over two waves; this module is
what stops it reopening, because the next new codec will add a fixture and
CI will now say so.

Deliberately a parity test, not a count: a hard-coded "13" would rot the
moment a codec lands.  The invariant is the correspondence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import list_public_codecs

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = _ROOT / "fixtures" / "synthetic"
_MODULE_DIR = Path(__file__).parent

_MODULE_RE = re.compile(r"^test_synthetic_(?P<codec>.+)_kitchen_sink\.py$")


def _fixture_codecs() -> set[str]:
    """Codec names that ship a synthetic kitchen-sink fixture."""
    return {
        path.parent.name
        for path in _FIXTURE_DIR.glob("*/kitchen_sink.*")
    }


def _module_codecs() -> set[str]:
    """Codec names that have a content-assertion module."""
    found = set()
    for path in _MODULE_DIR.glob("test_synthetic_*_kitchen_sink.py"):
        m = _MODULE_RE.match(path.name)
        if m:
            found.add(m.group("codec"))
    return found


def test_the_discovery_globs_find_something() -> None:
    """Guard the guard: a typo in either glob would make this module pass
    vacuously by comparing two empty sets."""
    assert _fixture_codecs(), f"no kitchen-sink fixtures under {_FIXTURE_DIR}"
    assert _module_codecs(), f"no assertion modules under {_MODULE_DIR}"


def test_every_fixture_has_an_assertion_module() -> None:
    missing = sorted(_fixture_codecs() - _module_codecs())
    assert not missing, (
        "kitchen-sink fixture(s) with no content-assertion module: "
        f"{missing}.  Add tests/unit/migration/test_synthetic_<codec>_"
        "kitchen_sink.py asserting the fixture's CONTENT — the shared "
        "round-trip sweep only proves canonical stability, so a fixture "
        "that silently loses a surface would keep the suite green.  Derive "
        "the expected values from a MEASURED parse, not by reading the "
        "config text."
    )


def test_every_assertion_module_has_a_fixture() -> None:
    """The reverse direction — a module whose fixture was renamed or removed
    is dead weight that still reports as coverage."""
    orphans = sorted(_module_codecs() - _fixture_codecs())
    assert not orphans, (
        f"assertion module(s) with no matching fixture: {orphans}"
    )


def test_every_public_codec_ships_a_kitchen_sink() -> None:
    """The set is only meaningful if it tracks the codec roster.

    A codec with neither fixture nor module would satisfy both parity tests
    above while having no kitchen-sink coverage at all.
    """
    uncovered = sorted(set(list_public_codecs()) - _fixture_codecs())
    assert not uncovered, (
        f"public codec(s) with no synthetic kitchen-sink fixture: "
        f"{uncovered}"
    )
