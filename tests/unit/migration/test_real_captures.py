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


_VENDOR_TO_CODEC = {
    "cisco_iosxe": _cisco_iosxe_cli_codec,
    "aruba_aoss": _aruba_aoss_codec,
    "fortigate": _fortigate_codec,
    "opnsense": _opnsense_codec,
    "mikrotik": _mikrotik_codec,
}

# (fixture_path, reason) pairs where we KNOW the file exercises a codec
# input the codec doesn't yet pretend to handle.  Everything else must
# parse cleanly.
_KNOWN_UNSUPPORTED: dict[str, str] = {
    # Empty — no whitelists today.  Every fixture committed should parse.
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
            if path.suffix.lower() not in {".txt", ".cfg", ".xml", ".conf"}:
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
