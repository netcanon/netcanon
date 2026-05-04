"""
Full-mesh cross-codec translation matrix.

Auto-generates a parametrized test per ``(source, target)`` pair
where the two codecs share at least one :class:`DeviceClass`, using
each source codec's declared ``sample_input`` as the fixture.  A
pair is skipped when:

  * The pair shares no device class — the class guard correctly
    refuses to translate (e.g. a pure-firewall codec to a pure-
    switch codec).  This is expected, not a failure.
  * The source codec declares no sample_input — nothing to feed.
  * The target codec is ``parse_only`` — the pipeline would fail
    for a separate, well-tested reason (render-error).

Goal of the matrix is catching **cross-vendor regressions**: when
adding a new codec, or fixing one, changes to the canonical tree
or a renderer must not break any OTHER pair.  The matrix expands
to O(n²) as codecs are added, so running it on every CI pass is
still fast (all renderers are pure-function).

Historical precedent: the OPNsense renderer's bare-numeric
interface-name XML-tag bug was only caught by a hand-written
Aruba→OPNsense test.  This matrix would have caught it
immediately when the Aruba codec landed.
"""

from __future__ import annotations

from itertools import product

import pytest

import netconfig.migration  # noqa: F401 — side-effect: register codecs

from netconfig.migration.codecs.registry import get_codec, list_codecs
from netconfig.models.migration import MigrationJobStatus
from netconfig.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


def _pair_id(src_name: str, tgt_name: str) -> str:
    """Human-readable pytest test ID for a (source, target) pair."""
    return f"{src_name}__to__{tgt_name}"


def _enumerate_pairs() -> list[tuple[str, str]]:
    """Return every ordered (source, target) codec pair.

    We yield all pairs including self-pairs.  Compatibility checks
    (shared device class, parse/render directionality, sample
    availability) happen inside the test body so the matrix can
    pytest-skip with a clear reason per pair — that's more useful
    for debugging than filtering at collection time.
    """
    names = list_codecs()
    return list(product(names, names))


# Pre-enumerate so pytest parametrize sees a stable list.
_ALL_PAIRS = _enumerate_pairs()


@pytest.mark.parametrize(
    ("src_name", "tgt_name"),
    _ALL_PAIRS,
    ids=[_pair_id(s, t) for s, t in _ALL_PAIRS],
)
def test_cross_codec_translation_does_not_crash(
    src_name: str, tgt_name: str,
) -> None:
    """For every compatible pair, running ``src.sample_input`` through
    the pipeline must produce a ``completed`` job.

    Skip conditions make the matrix robust as the ecosystem grows:
        * src == tgt        — trivial (covered by per-codec round-trip)
        * no sample_input   — codec hasn't declared one
        * parse-only target — would fail on render-error, not on
                              a cross-vendor bug
        * disjoint classes  — class guard correctly refuses
    """
    if src_name == tgt_name:
        pytest.skip("self-pair covered by per-codec round-trip tests")

    # MockCodec's tree is a flat dict (its own non-canonical shape),
    # so mock-as-source can't feed CanonicalIntent-only renderers.
    # Mock pairs with mock only; excluded from the cross-vendor matrix.
    if src_name == "mock" or tgt_name == "mock":
        pytest.skip("mock codec uses a non-canonical flat-dict tree")

    src = get_codec(src_name)
    tgt = get_codec(tgt_name)

    sample = getattr(src, "sample_input", "")
    if not sample:
        pytest.skip(f"{src_name!r} has no sample_input")

    if getattr(tgt, "direction", "bidirectional") == "parse_only":
        pytest.skip(f"{tgt_name!r} is parse-only; cannot be a target")

    src_classes = set(src.capabilities.device_classes)
    tgt_classes = set(tgt.capabilities.device_classes)
    shared = src_classes & tgt_classes
    if not shared:
        pytest.skip(
            f"no shared device class: "
            f"{src_name}={sorted(c.value for c in src_classes)}, "
            f"{tgt_name}={sorted(c.value for c in tgt_classes)}"
        )

    job = run_plan(src, tgt, sample)

    # ``partial`` is a legitimate terminal state when the target
    # honestly declares some source surfaces as unsupported (e.g. the
    # cisco_iosxe NETCONF codec is a Phase 0.5 stub whose render emits
    # only the openconfig-interfaces subtree — Wave 10γ-2 lifted the
    # remaining surfaces from ``supported`` to ``unsupported``).  The
    # render still produced output; the job's validation flagged the
    # gap.  ``completed`` is the happy path; ``partial`` is the
    # honestly-declared narrow-coverage path.
    assert job.status in (
        MigrationJobStatus.completed,
        MigrationJobStatus.partial,
    ), (
        f"{_pair_id(src_name, tgt_name)}: expected terminal-success "
        f"(completed or partial), got {job.status.value}; "
        f"error={job.error!r}"
    )
    assert job.rendered, (
        f"{_pair_id(src_name, tgt_name)}: terminal-success but "
        f"rendered is empty"
    )


@pytest.mark.parametrize(
    ("src_name", "tgt_name"),
    _ALL_PAIRS,
    ids=[_pair_id(s, t) for s, t in _ALL_PAIRS],
)
def test_every_source_ip_appears_in_rendered_output(
    src_name: str, tgt_name: str,
) -> None:
    """Silent-drop invariant: every IPv4 address in the parsed-source
    tree must appear as a literal substring in the target codec's
    rendered output.  If an IP vanishes between parse and render, the
    translator is losing data.

    Historical context: added after a user reported that
    `interface Vlan11 / ip address 192.168.11.252 ...` rendered to
    Aruba AOS-S produced a valid-looking config with the SVI IP
    entirely missing — the kind of silent data loss invisible
    unless you diff the trees.  See translator-plans.txt "KNOWN
    DATA-LOSS BUGS / BUG 1".

    The invariant is substring-based rather than re-parse based so
    it doesn't depend on the target's parser being able to consume
    foreign-vendor interface names (e.g. AOS-S's parser does not
    accept ``GigabitEthernet0/0/0`` because that's a Cisco-only name
    shape — but the IP on that interface still reaches the rendered
    text, which is what matters).

    Skip conditions match the sibling crash test: self-pairs, mock,
    parse-only targets, disjoint device classes, no sample IPs.
    """
    if src_name == tgt_name:
        pytest.skip("self-pair covered by per-codec round-trip tests")
    if src_name == "mock" or tgt_name == "mock":
        pytest.skip("mock codec uses a non-canonical flat-dict tree")

    src = get_codec(src_name)
    tgt = get_codec(tgt_name)

    sample = getattr(src, "sample_input", "")
    if not sample:
        pytest.skip(f"{src_name!r} has no sample_input")
    if getattr(tgt, "direction", "bidirectional") == "parse_only":
        pytest.skip(f"{tgt_name!r} is parse-only")

    src_classes = set(src.capabilities.device_classes)
    tgt_classes = set(tgt.capabilities.device_classes)
    if not (src_classes & tgt_classes):
        pytest.skip("no shared device class")

    # Collect every IPv4 address from the canonical source tree —
    # both on interfaces AND on VLAN SVI records.
    src_tree = src.parse(sample)
    source_ips = _collect_source_ips(src_tree)
    if not source_ips:
        pytest.skip(f"{src_name!r}'s sample has no IP addresses")

    rendered = tgt.render(src_tree)

    missing = [ip for ip in source_ips if ip not in rendered]
    assert not missing, (
        f"{_pair_id(src_name, tgt_name)}: translator silently dropped "
        f"{len(missing)} IP(s) during render: {missing}.  "
        f"Every IP from the source tree must appear in the rendered "
        f"output, otherwise data is being lost."
    )


def _collect_source_ips(tree) -> list[str]:
    """Every IP address in the canonical tree, de-duplicated.

    Covers addresses on interfaces AND on VLAN SVI records (IOS-XE
    CLI populates both when `interface Vlan<N>` has an IP).
    """
    seen: list[str] = []
    for iface in tree.interfaces:
        for addr in iface.ipv4_addresses:
            if addr.ip not in seen:
                seen.append(addr.ip)
    for vlan in tree.vlans:
        for addr in vlan.ipv4_addresses:
            if addr.ip not in seen:
                seen.append(addr.ip)
    return seen


def test_matrix_covers_at_least_fifteen_pairs():
    """Sanity check: once the ecosystem has 5+ real codecs, the
    compatible matrix should have at least 15 non-trivial pairs
    (every real-to-real pair that shares a device class)."""
    real_codecs = [
        name for name in list_codecs()
        if name != "mock"
    ]
    # Count pairs (src, tgt) where src != tgt AND they share a class
    # AND target is not parse-only AND source has a sample.
    covered = 0
    for src_name in real_codecs:
        for tgt_name in real_codecs:
            if src_name == tgt_name:
                continue
            src = get_codec(src_name)
            tgt = get_codec(tgt_name)
            if getattr(tgt, "direction", "bidirectional") == "parse_only":
                continue
            if not getattr(src, "sample_input", ""):
                continue
            src_c = set(src.capabilities.device_classes)
            tgt_c = set(tgt.capabilities.device_classes)
            if src_c & tgt_c:
                covered += 1
    assert covered >= 15, (
        f"only {covered} real-to-real cross-vendor pairs compatible; "
        f"add more codecs or broaden device_classes"
    )
