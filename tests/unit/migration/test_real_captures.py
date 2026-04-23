"""
Real-capture validation harness.

Purpose
-------
Exercise each codec's ``parse()`` against configs we didn't author.  The
per-vendor synthetic fixtures in ``tests/fixtures/<vendor>/`` prove our
codecs handle what we designed them for.  This module proves they also
survive what the *real world* looks like — carrier IOS with VRFs and
QoS, grammar kitchen-sink snippets from Batfish's parser tests, and
anything else we can get our hands on under a permissive license.

What's asserted (hard gate)
---------------------------
For every ``(codec, fixture)`` pair discovered:

1. ``codec.parse(raw)`` does not raise — real configs must never crash
   the pipeline.  Specific ParseError cases that are KNOWN-unsupported
   can be whitelisted via ``_KNOWN_UNSUPPORTED`` below; all others are a
   test failure.
2. The returned object is a ``CanonicalIntent``.
3. The parse yielded *something* — at least one xpath comes out of
   ``iter_xpaths``.  A silent return of an empty intent when the input
   clearly carries config is almost always a parser regression.

What's reported (soft, printed)
-------------------------------
Per fixture the test prints a small table showing how many of each
canonical field got populated — useful for eyeballing coverage
regressions across runs even when nothing breaks.  The
``tests/fixtures/real/RESULTS.md`` file in this tree is a
human-curated snapshot of those numbers as of the last known-good run.

Fixtures are discovered by directory name → codec mapping in
``_VENDOR_TO_CODEC`` below.  Drop new files into the right dir and they
show up automatically — see ``tests/fixtures/real/NOTICE.md`` for the
contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from netconfig.migration.canonical.intent import CanonicalIntent
from netconfig.migration.codecs.base import ParseError

pytestmark = pytest.mark.unit


REAL_FIXTURES_ROOT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "real"
)

# Directory name (vendor) -> codec class loader.  Loaders are callables
# so we don't import every codec eagerly when only one vendor's fixtures
# exist.
def _cisco_iosxe_cli_codec() -> Any:
    from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
    return CiscoIOSXECLICodec()


def _aruba_aoss_codec() -> Any:
    from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
    return ArubaAOSSCodec()


def _fortigate_codec() -> Any:
    from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
    return FortiGateCLICodec()


def _opnsense_codec() -> Any:
    from netconfig.migration.codecs.opnsense import OPNsenseCodec
    return OPNsenseCodec()


def _mikrotik_codec() -> Any:
    from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
    return MikroTikRouterOSCodec()


def _arista_eos_codec() -> Any:
    from netconfig.migration.codecs.arista_eos import AristaEOSCodec
    return AristaEOSCodec()


_VENDOR_TO_CODEC = {
    "cisco_iosxe": _cisco_iosxe_cli_codec,
    "aruba_aoss": _aruba_aoss_codec,
    "fortigate": _fortigate_codec,
    "opnsense": _opnsense_codec,
    "mikrotik": _mikrotik_codec,
    "arista_eos": _arista_eos_codec,
}

# (fixture_path, reason) pairs where we KNOW the file exercises a codec
# input the codec doesn't yet pretend to handle.  Everything else must
# parse cleanly.
_KNOWN_UNSUPPORTED: dict[str, str] = {
    # Empty — no whitelists today.  Every fixture committed should parse.
}

# (fixture_path, reason) pairs where the fixture PARSES cleanly but the
# codec's render path can't reproduce the canonical tree bit-for-bit on
# a round-trip.  These are TODOs on the codec, not the harness — the
# fixture stays in the corpus for parse-coverage validation.
_KNOWN_ROUNDTRIP_GAPS: dict[str, str] = {
    # Empty — previously-tracked gaps (bridge render, VLAN name
    # preservation) were both fixed as Fidelity Polish items.
}


def _discover_fixtures() -> list[tuple[str, Path]]:
    """Return ``[(codec_key, path), ...]`` for every fixture found
    under ``tests/fixtures/real/<vendor>/``.  Filters out NOTICE /
    RESULTS / hidden files."""
    out: list[tuple[str, Path]] = []
    if not REAL_FIXTURES_ROOT.is_dir():
        return out
    for vendor_dir in sorted(REAL_FIXTURES_ROOT.iterdir()):
        if not vendor_dir.is_dir():
            continue
        codec_key = vendor_dir.name
        if codec_key not in _VENDOR_TO_CODEC:
            continue
        for path in sorted(vendor_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            # Per-vendor native extensions.  .rsc = RouterOS export,
            # .conf = FortiOS-style, .cfg = Aruba/IOS, .xml = OPNsense.
            if path.suffix.lower() not in {".txt", ".cfg", ".xml", ".conf", ".rsc"}:
                continue
            out.append((codec_key, path))
    return out


_FIXTURE_PARAMS = _discover_fixtures()


def _param_id(p: tuple[str, Path]) -> str:
    codec_key, path = p
    return f"{codec_key}::{path.name}"


def _coverage(intent: CanonicalIntent) -> dict[str, int]:
    """Summarise how much canonical data got extracted — useful for
    detecting silent-drop regressions across runs."""
    return {
        "hostname": 1 if intent.hostname else 0,
        "dns_servers": len(intent.dns_servers),
        "ntp_servers": len(intent.ntp_servers),
        "interfaces": len(intent.interfaces),
        "vlans": len(intent.vlans),
        "static_routes": len(intent.static_routes),
        "lags": len(intent.lags),
        "dhcp_servers": len(intent.dhcp_servers),
        "local_users": len(intent.local_users),
        "radius_servers": len(intent.radius_servers),
        "snmp_set": 1 if intent.snmp is not None else 0,
    }


# ---------------------------------------------------------------------------
# Hard assertions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="no real-capture fixtures present yet",
)
@pytest.mark.parametrize(
    "codec_key,path",
    _FIXTURE_PARAMS,
    ids=[_param_id(p) for p in _FIXTURE_PARAMS],
)
def test_real_capture_parses_cleanly(
    codec_key: str, path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Every committed real capture must parse without raising (unless
    explicitly whitelisted) and produce a non-trivial CanonicalIntent."""
    codec = _VENDOR_TO_CODEC[codec_key]()
    raw = path.read_text(encoding="utf-8", errors="replace")

    whitelist_reason = _KNOWN_UNSUPPORTED.get(str(path.relative_to(REAL_FIXTURES_ROOT)))
    try:
        intent = codec.parse(raw)
    except ParseError as exc:
        if whitelist_reason is not None:
            pytest.skip(f"known-unsupported: {whitelist_reason} ({exc})")
        pytest.fail(
            f"{codec_key} raised ParseError on {path.name}: {exc}\n"
            f"First 200 chars: {raw[:200]!r}"
        )

    assert isinstance(intent, CanonicalIntent), (
        f"{codec_key}.parse({path.name}) returned "
        f"{type(intent).__name__}, expected CanonicalIntent"
    )

    # Must extract at least SOMETHING.  A zero-coverage parse of a
    # non-empty config is the silent-drop regression signature we're
    # hunting.
    coverage = _coverage(intent)
    total_extracted = sum(coverage.values())
    assert total_extracted > 0, (
        f"{codec_key}.parse({path.name}) emitted a CanonicalIntent with "
        f"zero populated fields — silent drop?  Coverage: {coverage}"
    )

    # Emit coverage on stdout so -s runs show a human-readable matrix.
    summary = ", ".join(
        f"{k}={v}" for k, v in coverage.items() if v > 0
    )
    print(f"[real-capture] {codec_key}::{path.name}  {summary}")


# ---------------------------------------------------------------------------
# Additional invariant: parse output must be deterministic
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="no real-capture fixtures present yet",
)
@pytest.mark.parametrize(
    "codec_key,path",
    _FIXTURE_PARAMS,
    ids=[_param_id(p) for p in _FIXTURE_PARAMS],
)
def test_real_capture_parse_is_deterministic(
    codec_key: str, path: Path,
) -> None:
    """Parsing the same input twice must produce structurally-identical
    trees.  Catches accidental use of ``set`` ordering, ``dict`` key
    order reliance, or time-dependent logic."""
    codec = _VENDOR_TO_CODEC[codec_key]()
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        a = codec.parse(raw)
        b = codec.parse(raw)
    except ParseError:
        pytest.skip("parse already covered by test_real_capture_parses_cleanly")
    assert a.model_dump() == b.model_dump(), (
        f"{codec_key}.parse({path.name}) is non-deterministic"
    )


# ---------------------------------------------------------------------------
# Round-trip invariant for bidirectional codecs
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="no real-capture fixtures present yet",
)
@pytest.mark.parametrize(
    "codec_key,path",
    _FIXTURE_PARAMS,
    ids=[_param_id(p) for p in _FIXTURE_PARAMS],
)
def test_real_capture_round_trips_stable(
    codec_key: str, path: Path,
) -> None:
    """For bidirectional codecs: ``parse(render(parse(raw))) ==
    parse(raw)``.

    The render output isn't required to be byte-identical to the input
    (real configs carry comments, whitespace, unsupported directives we
    don't model).  What IS required is that the canonical
    *representation* we extract stabilises after one round-trip —
    otherwise the codec is either lossy in a way that compounds
    (bad) or non-deterministic in render (also bad).

    Skips parse_only codecs (cisco_iosxe_cli) and any fixture that
    already raised in parse (covered by the sibling test).
    """
    codec = _VENDOR_TO_CODEC[codec_key]()
    if getattr(codec.__class__, "direction", "") == "parse_only":
        pytest.skip(f"{codec_key} is parse_only; round-trip not applicable")

    gap_reason = _KNOWN_ROUNDTRIP_GAPS.get(
        str(path.relative_to(REAL_FIXTURES_ROOT)).replace("\\", "/")
    )
    if gap_reason is not None:
        pytest.skip(f"known round-trip gap: {gap_reason}")

    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        first = codec.parse(raw)
    except ParseError:
        pytest.skip("parse failure already reported by sibling test")

    try:
        rendered = codec.render(first)
    except Exception as exc:  # noqa: BLE001 — we want any render surprise
        pytest.fail(
            f"{codec_key}.render() blew up on the parsed-from-real intent: {exc}"
        )

    try:
        second = codec.parse(rendered)
    except ParseError as exc:
        pytest.fail(
            f"{codec_key}.parse(render(parse(raw))) ParseError: {exc}\n"
            f"Rendered (first 400 chars): {rendered[:400]!r}"
        )

    # Strip metadata that encodes WHICH parse produced the tree — it's
    # not a round-trip stability property.
    #
    # Also sort list fields where ordering is cosmetic (interfaces,
    # vlans, static_routes, lags): renderers may emit sections in a
    # different order than the source file (e.g. Aruba emits VLAN
    # stanzas before interfaces but templates often put interfaces
    # first), so a first parse sees a different list order than a
    # re-parse even though canonical meaning is identical.  Sorting
    # by the natural identity key for each type gives us the semantic
    # equality check we actually want.
    def _compare(intent: CanonicalIntent) -> dict[str, Any]:
        d = intent.model_dump()
        d.pop("source_vendor", None)
        d.pop("source_format", None)
        d.pop("source_version", None)
        # Sort collections by natural identity key.
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
        return d

    assert _compare(first) == _compare(second), (
        f"{codec_key} round-trip not stable on {path.name}: "
        f"canonical representation changed after parse->render->parse"
    )
