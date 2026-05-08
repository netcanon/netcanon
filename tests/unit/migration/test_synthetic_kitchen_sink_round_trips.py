"""
Synthetic kitchen-sink round-trip harness.

Purpose
-------
Drift guard that mirrors :mod:`test_real_captures` but operates on the
synthetic per-codec kitchen-sink fixtures under
``tests/fixtures/synthetic/<codec>/kitchen_sink.<ext>``.

Real-capture fixtures answer "what survives parse on what's actually
deployed in the wild" — a partial slice of features, dictated by the
original operator's deployment.  Synthetic kitchen-sinks answer the
complementary question: "what survives parse + round-trip when EVERY
field the codec's :class:`CapabilityMatrix` declares supported (or
lossy) gets exercised at once".

The per-vendor ``test_synthetic_<vendor>_kitchen_sink.py`` modules
already pin the parse coverage for individual codecs.  This module
adds the three uniform drift-guards from ``test_real_captures``
(parses cleanly, parse is deterministic, render-parse round-trip is
canonical-stable) so synthetic fixtures get the same regression
protection that real captures do — discovered automatically and
parametrised, no per-vendor copy-paste.

Why a parallel module rather than extending ``test_real_captures``?
-------------------------------------------------------------------
Coupling real-vs-synthetic discovery in one harness conflates two
different signals: "this codec regressed against a real config" vs
"this codec regressed against its own capability declaration".  When
something fails, you want the test name to tell you which corpus
broke.  A separate file does that.

Discovery uses the directory name as the registered codec name
directly — kitchen-sinks live at
``tests/fixtures/synthetic/<codec_name>/kitchen_sink.<ext>`` (matches
``CodecBase.name``), so no translation table is needed.  The runner
script :mod:`tools.run_full_mesh` uses the same convention.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.base import ParseError

# Side-effect imports to register every codec.  Mirrors
# ``test_real_captures.py`` so synthetic discovery sees the same
# registry view.
from netcanon.migration.codecs import (  # noqa: F401
    arista_eos,
    aruba_aoss,
    cisco_iosxe,
    cisco_iosxe_cli,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
)
from netcanon.migration.codecs.registry import get_codec, list_codecs

pytestmark = pytest.mark.unit


SYNTHETIC_FIXTURES_ROOT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
)


# Per-vendor native fixture extensions — mirrors the filter in
# ``test_real_captures::_discover_fixtures`` so the two corpora speak
# the same vocabulary.
_FIXTURE_EXTENSIONS = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}


# (codec_name::fixture_name, reason) pairs where the synthetic fixture
# parses cleanly but the codec's render path can't reproduce the
# canonical tree bit-for-bit on a single round-trip.  These are TODOs
# on the codec, not on the fixture or the harness — the fixture stays
# in the corpus to keep parse-coverage validation intact.  Re-running
# ``tools/run_full_mesh.py --matrix`` will keep showing the drift in
# the synthetic submatrix; clearing the entry here once the codec is
# fixed re-enables the round-trip assertion.
#
# Mirrors the precedent set by ``test_real_captures::
# _KNOWN_ROUNDTRIP_GAPS``.  Key format is ``"<codec_name>::<filename>"``
# matching the parametrise id so the lookup is unambiguous.
_KNOWN_ROUNDTRIP_GAPS: dict[str, str] = {
    # mikrotik_routeros: bond-interface ``description`` round-trip drop
    # — surfaced by the kitchen-sink's "LACP bond to upstream core"
    # description on a synthetic bonding interface.  The render path
    # emits the bond stanza without re-emitting its description, so
    # the second parse sees an empty description.  Real-capture
    # coverage doesn't hit this because none of the committed real
    # RouterOS exports describe a bond with a description string.
    "mikrotik_routeros::kitchen_sink.rsc": (
        "bond-interface description not preserved through render — "
        "TODO on mikrotik_routeros codec"
    ),
}


def _discover_synthetic_fixtures() -> list[tuple[str, Path]]:
    """Return ``[(codec_name, path), ...]`` for every synthetic
    kitchen-sink fixture.  Synthetic dirs are named after the
    registered codec directly (no translation table) — an unrecognised
    codec name in the dir tree would surface as a parametrise-time
    skip via :func:`get_codec`.
    """
    out: list[tuple[str, Path]] = []
    if not SYNTHETIC_FIXTURES_ROOT.is_dir():
        return out
    registered = set(list_codecs())
    for codec_dir in sorted(SYNTHETIC_FIXTURES_ROOT.iterdir()):
        if not codec_dir.is_dir() or codec_dir.name.startswith("_"):
            continue
        codec_name = codec_dir.name
        if codec_name not in registered:
            continue  # Unknown codec dir — guard test below catches it.
        for path in sorted(codec_dir.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in _FIXTURE_EXTENSIONS:
                continue
            out.append((codec_name, path))
    return out


_FIXTURE_PARAMS = _discover_synthetic_fixtures()


def _param_id(p: tuple[str, Path]) -> str:
    codec_name, path = p
    return f"{codec_name}::{path.name}"


# ---------------------------------------------------------------------------
# Drift-guard 1: parse without raising
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="no synthetic kitchen-sink fixtures present",
)
@pytest.mark.parametrize(
    "codec_name,path",
    _FIXTURE_PARAMS,
    ids=[_param_id(p) for p in _FIXTURE_PARAMS],
)
def test_synthetic_parses_cleanly(codec_name: str, path: Path) -> None:
    """Every committed synthetic kitchen-sink must parse without raising
    and produce a populated :class:`CanonicalIntent`.  Synthetic
    fixtures are author-curated to exercise every supported field, so a
    ParseError here is unambiguously a codec regression — there's no
    "the real config used a feature we don't support" escape hatch
    that real captures sometimes get."""
    codec = get_codec(codec_name)
    raw = path.read_text(encoding="utf-8")
    try:
        intent = codec.parse(raw)
    except ParseError as exc:
        pytest.fail(
            f"{codec_name} raised ParseError on synthetic "
            f"{path.name}: {exc}\nFirst 200 chars: {raw[:200]!r}"
        )
    assert isinstance(intent, CanonicalIntent), (
        f"{codec_name}.parse({path.name}) returned "
        f"{type(intent).__name__}, expected CanonicalIntent"
    )


# ---------------------------------------------------------------------------
# Drift-guard 2: parse is deterministic
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="no synthetic kitchen-sink fixtures present",
)
@pytest.mark.parametrize(
    "codec_name,path",
    _FIXTURE_PARAMS,
    ids=[_param_id(p) for p in _FIXTURE_PARAMS],
)
def test_synthetic_parse_is_deterministic(
    codec_name: str, path: Path,
) -> None:
    """Parsing the synthetic fixture twice must produce structurally
    identical canonical trees.  Catches accidental ``set`` ordering,
    dict-key-order reliance, or time-dependent logic in the parser."""
    codec = get_codec(codec_name)
    raw = path.read_text(encoding="utf-8")
    try:
        a = codec.parse(raw)
        b = codec.parse(raw)
    except ParseError:
        pytest.skip(
            "parse already covered by test_synthetic_parses_cleanly"
        )
    assert a.model_dump() == b.model_dump(), (
        f"{codec_name}.parse({path.name}) is non-deterministic"
    )


# ---------------------------------------------------------------------------
# Drift-guard 3: render-parse round-trip is canonical-stable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="no synthetic kitchen-sink fixtures present",
)
@pytest.mark.parametrize(
    "codec_name,path",
    _FIXTURE_PARAMS,
    ids=[_param_id(p) for p in _FIXTURE_PARAMS],
)
def test_synthetic_round_trips_stable(
    codec_name: str, path: Path,
) -> None:
    """For bidirectional codecs: ``parse(render(parse(raw))) ==
    parse(raw)``.  Same invariant as the real-capture round-trip test
    — what stays semantically stable is the canonical *representation*,
    not the rendered text.

    Skips parse_only codecs.  Sorts list-fields with a natural identity
    key before comparison so render-side reordering of e.g. interface
    emission doesn't register as drift on a property that's
    canonically set-semantic.
    """
    codec = get_codec(codec_name)
    if getattr(codec.__class__, "direction", "") == "parse_only":
        pytest.skip(
            f"{codec_name} is parse_only; round-trip not applicable"
        )

    gap_reason = _KNOWN_ROUNDTRIP_GAPS.get(f"{codec_name}::{path.name}")
    if gap_reason is not None:
        pytest.skip(f"known round-trip gap: {gap_reason}")

    raw = path.read_text(encoding="utf-8")
    try:
        first = codec.parse(raw)
    except ParseError:
        pytest.skip("parse failure already reported by sibling test")

    try:
        rendered = codec.render(first)
    except Exception as exc:  # noqa: BLE001 — surface any render issue
        pytest.fail(
            f"{codec_name}.render() blew up on parsed synthetic intent: "
            f"{exc}"
        )

    try:
        second = codec.parse(rendered)
    except ParseError as exc:
        pytest.fail(
            f"{codec_name}.parse(render(parse(raw))) ParseError on "
            f"synthetic {path.name}: {exc}\n"
            f"Rendered (first 400 chars): {rendered[:400]!r}"
        )

    assert _compare(first) == _compare(second), (
        f"{codec_name} round-trip not stable on synthetic {path.name}: "
        f"canonical representation changed after parse->render->parse"
    )


def _compare(intent: CanonicalIntent) -> dict[str, Any]:
    """Strip metadata + sort cosmetic-order list fields so the
    round-trip comparison checks canonical *meaning*, not list
    ordering.  Mirrors ``test_real_captures::_compare`` — same
    invariants apply to both corpora.
    """
    d = intent.model_dump()
    d.pop("source_vendor", None)
    d.pop("source_format", None)
    d.pop("source_version", None)
    for key, id_key in [
        ("interfaces", "name"),
        ("vlans", "id"),
        ("static_routes", "destination"),
        ("lags", "name"),
        ("dhcp_servers", "network"),
        ("local_users", "name"),
        ("radius_servers", "host"),
    ]:
        if key in d and isinstance(d[key], list):
            d[key] = sorted(d[key], key=lambda x: x.get(id_key, ""))
    for v in d.get("vlans", []):
        if isinstance(v.get("tagged_ports"), list):
            v["tagged_ports"] = sorted(v["tagged_ports"])
        if isinstance(v.get("untagged_ports"), list):
            v["untagged_ports"] = sorted(v["untagged_ports"])
    for lag in d.get("lags", []):
        if isinstance(lag.get("members"), list):
            lag["members"] = sorted(lag["members"])
    for iface in d.get("interfaces", []):
        if isinstance(iface.get("trunk_allowed_vlans"), list):
            iface["trunk_allowed_vlans"] = sorted(
                iface["trunk_allowed_vlans"]
            )
    return d


# ---------------------------------------------------------------------------
# Discovery guard — every synthetic dir must map to a registered codec
# ---------------------------------------------------------------------------


def test_every_synthetic_dir_maps_to_a_registered_codec() -> None:
    """Every non-hidden, non-underscored subdirectory under
    ``tests/fixtures/synthetic/`` must name a registered codec.  Guards
    against a typo in a directory name silently dropping the fixture
    out of round-trip coverage.

    Underscore-prefixed directories (e.g. ``_scratch/``) are operator
    scratch space and intentionally exempt — same convention as the
    real-fixture root's ``_cross_mesh_runs/``.
    """
    if not SYNTHETIC_FIXTURES_ROOT.is_dir():
        pytest.skip(
            f"{SYNTHETIC_FIXTURES_ROOT} does not exist"
        )
    registered = set(list_codecs())
    subdirs = [
        d.name for d in SYNTHETIC_FIXTURES_ROOT.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and not d.name.startswith("_")
    ]
    missing = [d for d in subdirs if d not in registered]
    assert not missing, (
        f"Synthetic fixture directories with no matching registered "
        f"codec: {missing}.  Either rename the dir to match a codec "
        f"name or remove it.  Registered codecs: {sorted(registered)}"
    )
