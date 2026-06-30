"""audit bb47f21 T0-1 — LAG ``mode`` value-fidelity guard.

The Arista parser used to discard the ``channel-group N mode <X>`` token and
hard-code ``mode="active"`` at LAG materialisation, so a ``passive`` / static
(``on``) Arista LAG round-tripped to ``active`` while the live validator
reported ``severity: ok`` — the silent-loss class, value-corruption variant
(audit bb47f21 T0-1, the 10th recurrence).

The walker DOES yield ``/lags/lag/mode``, but ``classify()`` fails open, so a
codec that drops or downgrades the mode on render→re-parse must declare it
lossy/unsupported — otherwise live validation says ``ok`` while the LACP mode
is silently corrupted.

This guard is **reachability-based** (naming-independent): for each codec, if
a LAG round-trips at all (survives render→re-parse) but a given ``mode`` value
does NOT survive, the codec MUST declare ``/lags/lag/mode`` lossy/unsupported.
Codecs that round-trip the mode need no declaration (the ``supported`` default
is honest). Codecs whose LAG drops entirely on the shared synthetic (vendor
name mismatch / no standalone LAG model — cisco_iosxe stub, vyos) are skipped:
that is a separate whole-LAG-support concern, not a mode-fidelity one.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
)
from netcanon.migration.codecs import (  # noqa: F401  (register all codecs)
    arista_eos,
    aruba_aoscx,
    aruba_aoss,
    cisco_iosxe,
    cisco_iosxe_cli,
    cisco_iosxr,
    cisco_nxos,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
    vyos,
)
from netcanon.migration.codecs.registry import get_codec, list_codecs
from tests.unit.migration.test_registry_capability_honesty import _maximal_intent

pytestmark = pytest.mark.unit

_MODE_PATH = "/lags/lag/mode"
#: Non-default canonical LAG modes that a faithful codec should preserve.
_TEST_MODES = ("passive", "static")


def _codec_names() -> list[str]:
    return sorted(n for n in list_codecs() if n != "mock")


@pytest.mark.parametrize("name", _codec_names())
def test_lag_mode_drop_is_declared_lossy(name: str) -> None:
    codec = get_codec(name)
    caps = codec.capabilities
    declared = (
        _MODE_PATH in {lp.path for lp in caps.lossy}
        or _MODE_PATH in {u.path for u in caps.unsupported}
    )

    lost: list[str] = []
    for mode in _TEST_MODES:
        intent = _maximal_intent()
        for lag in intent.lags:
            lag.mode = mode
        reparsed = codec.parse(codec.render(intent))
        if not reparsed.lags:
            continue  # whole LAG dropped (naming / no LAG model) — out of scope
        if mode not in {lag.mode for lag in reparsed.lags}:
            lost.append(mode)

    assert not (lost and not declared), (
        f"{name}: a round-tripped LAG loses mode(s) {lost} (re-parses to a "
        f"different value) yet the matrix declares {_MODE_PATH} neither lossy "
        f"nor unsupported, so live validation reports 'ok' while the LACP mode "
        f"is silently corrupted. Capture the mode on parse, or add a "
        f"LossyPath({_MODE_PATH}) (mirror the vyos pattern)."
    )


def test_arista_lag_mode_round_trips() -> None:
    """T0-1 regression pin: the Arista codec must round-trip active / passive /
    static (it used to discard the ``channel-group`` mode token and hard-code
    ``active``, silently promoting passive + static bundles)."""
    codec = get_codec("arista_eos")
    for mode in ("active", "passive", "static"):
        tree = CanonicalIntent(
            hostname="sw1",
            interfaces=[CanonicalInterface(
                name="Ethernet1", lag_member_of="Port-Channel7")],
            lags=[CanonicalLAG(
                name="Port-Channel7", members=["Ethernet1"], mode=mode)],
        )
        reparsed = codec.parse(codec.render(tree))
        got = reparsed.lags[0].mode if reparsed.lags else "(no lag)"
        assert got == mode, (
            f"Arista LAG mode {mode!r} did not round-trip (got {got!r}) — "
            f"the channel-group mode token must be captured on parse"
        )
