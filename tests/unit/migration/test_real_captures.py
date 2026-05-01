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

# Side-effect imports to auto-register every codec with the registry
# so ``get_codec(name)`` below can look them up by name.  If you add a
# new codec package, add its import here.
from netconfig.migration.codecs import (  # noqa: F401
    arista_eos,
    aruba_aoss,
    cisco_iosxe_cli,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
)
from netconfig.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


REAL_FIXTURES_ROOT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "real"
)

#: Fixture-directory name → registered codec name.  The fixture-tree
#: layout uses human-short labels (``fortigate`` / ``mikrotik`` /
#: ``junos``) while the codec registry uses format-qualified names
#: (``fortigate_cli`` / ``mikrotik_routeros`` / ``juniper_junos``)
#: — the mapping bridges the two vocabularies.
#:
#: When adding a fixture directory: add a row here.  The
#: ``test_every_fixture_dir_has_codec_mapping`` guard below fails
#: loud if you forget.
_DIR_TO_CODEC_NAME: dict[str, str] = {
    "cisco_iosxe":  "cisco_iosxe_cli",
    "aruba_aoss":   "aruba_aoss",
    "fortigate":    "fortigate_cli",
    "opnsense":     "opnsense",
    "mikrotik":     "mikrotik_routeros",
    "arista_eos":   "arista_eos",
    "junos":        "juniper_junos",
}


def _codec_for_dir(vendor_dir: str) -> Any:
    """Return a fresh codec instance for the *vendor_dir* fixture
    directory.  Looks up the mapping + delegates to the registry.
    Replaces the seven near-identical loader callables this module
    previously hand-maintained.
    """
    codec_name = _DIR_TO_CODEC_NAME[vendor_dir]
    return get_codec(codec_name)


# Legacy alias — kept because ``test_results_md.py`` imports it by
# name.  New code should use ``_codec_for_dir`` or the registry
# directly.
_VENDOR_TO_CODEC: dict[str, Any] = {
    vendor_dir: (lambda name=codec_name: get_codec(name))
    for vendor_dir, codec_name in _DIR_TO_CODEC_NAME.items()
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
            # .conf = FortiOS-style, .cfg = Aruba/IOS, .xml = OPNsense,
            # .set = Junos set-form (``show configuration | display set``).
            if path.suffix.lower() not in {
                ".txt", ".cfg", ".xml", ".conf", ".rsc", ".set",
            }:
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
        # Sort INNER port-membership lists on each VLAN.  These are
        # set-semantic in canonical (port X is or isn't a member of
        # VLAN Y; order is cosmetic).  Without this, a render that
        # reorders interface emission (e.g. natural port-name sort)
        # produces port lists in a different order than the source
        # file's order, even though set membership is identical.  The
        # round-trip property we care about is canonical *meaning*,
        # not list ordering.
        for v in d.get("vlans", []):
            if isinstance(v.get("tagged_ports"), list):
                v["tagged_ports"] = sorted(v["tagged_ports"])
            if isinstance(v.get("untagged_ports"), list):
                v["untagged_ports"] = sorted(v["untagged_ports"])
        # Same for LAG members + interface trunk-allowed lists.
        for lag in d.get("lags", []):
            if isinstance(lag.get("members"), list):
                lag["members"] = sorted(lag["members"])
        for iface in d.get("interfaces", []):
            if isinstance(iface.get("trunk_allowed_vlans"), list):
                iface["trunk_allowed_vlans"] = sorted(
                    iface["trunk_allowed_vlans"]
                )
        return d

    assert _compare(first) == _compare(second), (
        f"{codec_key} round-trip not stable on {path.name}: "
        f"canonical representation changed after parse->render->parse"
    )


# ---------------------------------------------------------------------------
# Drift guards — fail loud on structural mismatches between the
# fixture tree, the codec registry, and the mapping above.
# ---------------------------------------------------------------------------


def test_every_fixture_dir_has_codec_mapping() -> None:
    """Every non-hidden subdirectory under ``tests/fixtures/real/``
    must appear in ``_DIR_TO_CODEC_NAME``.  Guard against adding a
    new fixture directory (e.g. ``tests/fixtures/real/aos_cx/``)
    without wiring it to a codec — the old _discover_fixtures loop
    silently skipped unmapped directories, which means unmapped
    fixtures got zero validation coverage.
    """
    if not REAL_FIXTURES_ROOT.is_dir():
        pytest.skip(f"{REAL_FIXTURES_ROOT} does not exist")
    subdirs = [
        d.name for d in REAL_FIXTURES_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ]
    missing = [d for d in subdirs if d not in _DIR_TO_CODEC_NAME]
    assert not missing, (
        f"Fixture directories with no codec mapping: {missing}.  "
        f"Add them to ``_DIR_TO_CODEC_NAME`` at the top of this "
        f"file, or remove the directories.  Known mappings: "
        f"{sorted(_DIR_TO_CODEC_NAME.keys())}"
    )


def test_every_mapped_codec_is_registered() -> None:
    """Every codec name referenced by ``_DIR_TO_CODEC_NAME`` must
    exist in the registry.  Guards against typos + against removing
    a codec package without cleaning up this dict."""
    from netconfig.migration.codecs.registry import list_codecs
    registered = set(list_codecs())
    bad = [
        (vendor_dir, codec_name)
        for vendor_dir, codec_name in _DIR_TO_CODEC_NAME.items()
        if codec_name not in registered
    ]
    assert not bad, (
        f"Fixture-directory mappings reference unregistered codecs: "
        f"{bad}.  Registered codecs: {sorted(registered)}"
    )


# ---------------------------------------------------------------------------
# GAP-EVPN-2: VXLAN source-interface + udp-port survival on real captures.
#
# Asserts that switch-level VTEP settings (vxlan source-interface +
# vxlan udp-port on Arista; switch-options vtep-source-interface +
# vxlan-port on Junos) populate onto every CanonicalVxlan record at
# parse time.  Pinpointed regression guard against the silent-drop bug
# pattern (#2) flagged in translator-plans.txt.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_relpath,expected_source_interface",
    [
        # karneliuk_a_eos1_eos4260: ``vxlan source-interface Loopback0``
        ("arista_eos/karneliuk_a_eos1_eos4260.txt", "Loopback0"),
        # batfish_labval_dc1_leaf2a_eos4230: ``vxlan source-interface Loopback1``
        ("arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt", "Loopback1"),
    ],
)
def test_arista_vxlan_source_interface_survives_parse(
    fixture_relpath: str, expected_source_interface: str,
) -> None:
    """VXLAN source-interface must populate onto every CanonicalVxlan
    record when the fixture declares the switch-level setting."""
    path = REAL_FIXTURES_ROOT / fixture_relpath
    if not path.is_file():
        pytest.skip(f"fixture {fixture_relpath} not present")
    codec = get_codec("arista_eos")
    raw = path.read_text(encoding="utf-8", errors="replace")
    intent = codec.parse(raw)
    assert intent.vxlan_vnis, (
        f"{fixture_relpath} produced no CanonicalVxlan records — "
        f"VLAN-to-VNI parse regression?"
    )
    for rec in intent.vxlan_vnis:
        assert rec.source_interface == expected_source_interface, (
            f"{fixture_relpath}: VNI {rec.vni} parsed with "
            f"source_interface={rec.source_interface!r}, expected "
            f"{expected_source_interface!r}"
        )
        assert rec.udp_port == 4789  # both fixtures use the IANA default


# ---------------------------------------------------------------------------
# GAP-EVPN-1: ``router bgp / vlan N / rd ... / route-target both ...``
# populates a CanonicalRoutingInstance keyed by the matching
# CanonicalVlan.name with ``instance_type="mac-vrf"``.  Regression
# guard against the silent-drop bug pattern (#1) flagged in
# translator-plans.txt.
# ---------------------------------------------------------------------------


def test_ipv6_addresses_survive_real_capture_parse() -> None:
    """GAP-EVPN-3: every real-capture fixture that carries static IPv6
    addresses must have those addresses survive on the canonical
    CanonicalInterface.ipv6_addresses field.

    Vendor coverage exercised here:
        * arista_eos / karneliuk_a_eos1_eos4260.txt — Management1
          carries ``ipv6 address fc00:192:168:100::62/64`` (the
          regression target).
        * cisco_iosxe / batfish_cisco_interface.txt — multiple v6
          addresses including a /128 loopback and a /64 SVI.
        * junos / buraglio_netlab_junos184.set — em0 + lo0 carry
          ``family inet6 address`` lines.
        * junos / batfish_evpntype5_router1_junos2541.set — fxp0
          v6 management address.

    The aruba real-capture has only ``ipv6 address dhcp full``
    (stateless DHCP) which doesn't represent a static address;
    fortigate's only v6 lines are the ``set ip6-address ::/0``
    placeholders that we filter; opnsense's v6 lines are
    ``dhcp6`` / ``idassoc6`` keyword markers that we also filter.
    Those vendors are deliberately not asserted here.
    """
    cases = [
        # (fixture_path, codec_id, expected_address, expected_prefix)
        (
            "arista_eos/karneliuk_a_eos1_eos4260.txt",
            "arista_eos",
            "fc00:192:168:100::62",
            64,
        ),
        (
            "cisco_iosxe/batfish_cisco_interface.txt",
            "cisco_iosxe_cli",
            "2001:60:0:C00::B",
            128,
        ),
        (
            "junos/buraglio_netlab_junos184.set",
            "juniper_junos",
            "2001:db8:293:1::fd",
            128,
        ),
        (
            "junos/batfish_evpntype5_router1_junos2541.set",
            "juniper_junos",
            "2001:db8::2",
            64,
        ),
    ]
    for fixture_rel, codec_id, expected_ip, expected_prefix in cases:
        path = REAL_FIXTURES_ROOT / fixture_rel
        if not path.is_file():
            continue
        codec = get_codec(codec_id)
        raw = path.read_text(encoding="utf-8", errors="replace")
        intent = codec.parse(raw)
        observed = [
            (a.ip, a.prefix_length)
            for iface in intent.interfaces
            for a in iface.ipv6_addresses
        ]
        assert (expected_ip, expected_prefix) in observed, (
            f"Expected ({expected_ip}, /{expected_prefix}) in "
            f"{fixture_rel}; observed={observed}"
        )


def test_arista_bgp_vlan_mac_vrf_survives_karneliuk_parse() -> None:
    """The karneliuk EOS 4.26 fixture declares
    ``router bgp 65033 / vlan 100 / rd 10.0.255.33:100 /
    route-target both 65000:100``.  All three pieces must populate a
    CanonicalRoutingInstance keyed ``Tenant_100`` (the matching
    CanonicalVlan.name)."""
    path = (
        REAL_FIXTURES_ROOT / "arista_eos" / "karneliuk_a_eos1_eos4260.txt"
    )
    if not path.is_file():
        pytest.skip("karneliuk fixture not present")
    codec = get_codec("arista_eos")
    raw = path.read_text(encoding="utf-8", errors="replace")
    intent = codec.parse(raw)
    ri = next(
        (r for r in intent.routing_instances if r.name == "Tenant_100"),
        None,
    )
    assert ri is not None, (
        f"Expected MAC-VRF for VLAN 100 named Tenant_100; got "
        f"routing_instances={[r.name for r in intent.routing_instances]}"
    )
    assert ri.instance_type == "mac-vrf"
    assert ri.route_distinguisher == "10.0.255.33:100"
    assert ri.rt_imports == ["65000:100"]
    assert ri.rt_exports == ["65000:100"]
