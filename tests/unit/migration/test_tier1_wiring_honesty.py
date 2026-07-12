"""Truth-maintenance guard for the Tier-1 timezone / syslog docs (#1).

The 2026-07-06 Fable review found the Tier-1 promise (README, CAPABILITIES.md,
canonical/README.md, intent.py, several vendor pages) claimed ``timezone`` and
``syslog_servers`` round-trip on every shipped codec, while ``timezone`` was
wired on **none** and ``syslog_servers`` on only ``juniper_junos`` (via a
fail-open undeclared path).  The docs were corrected to say so.

Since then the syslog surface graduated on two more codecs — ``cisco_iosxe_cli``
and ``arista_eos`` now parse-harvest + render ``logging host <ip>`` (promotions
#1/#11), and ``juniper_junos``'s existing round-trip was declared explicit — so
the roster is now ``{arista_eos, cisco_iosxe_cli, juniper_junos}``.

These guards pin the underlying matrix facts so a codec that wires (or
regresses) either field trips the test — forcing the Tier-1 docs to be updated
in lockstep rather than silently drifting.  They also lock the honesty property
that ``timezone``'s drop is *declared* (so the cross-vendor unsupported banner
fires) rather than undeclared (fail-open = silent loss).
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.registry import get_codec, list_codecs

pytestmark = pytest.mark.unit

# The mock codec has no real vendor capability matrix.
_REAL_CODECS = [c for c in list_codecs() if c != "mock"]


def _status(codec_name: str, path: str) -> str:
    m = get_codec(codec_name).capabilities
    if path in set(m.supported):
        return "supported"
    if any(p.path == path for p in m.lossy):
        return "lossy"
    if any(p.path == path for p in m.unsupported):
        return "unsupported"
    return "undeclared"


def test_timezone_declared_unsupported_on_every_codec() -> None:
    """`/system/timezone` must be declared ``unsupported`` on every shipped
    codec — this both pins the docs' "wired on no codec" claim and keeps the
    drop DECLARED (banner fires cross-vendor) rather than undeclared
    (fail-open silent loss)."""
    offenders = {
        c: _status(c, "/system/timezone")
        for c in _REAL_CODECS
        if _status(c, "/system/timezone") != "unsupported"
    }
    assert not offenders, (
        f"/system/timezone is no longer 'unsupported' on {offenders} — update "
        f"the Tier-1 docs (README / CAPABILITIES.md / canonical/README.md / "
        f"intent.py / vendor pages) to match before relaxing this guard."
    )


# Codecs that genuinely round-trip syslog (parse harvest + render emit) and
# therefore list `/system/syslog-server` in their EXPLICIT ``supported`` set.
# juniper_junos: ``set system syslog host <ip>``.  cisco_iosxe_cli + arista_eos:
# ``logging host <ip>`` (promotions #1/#11).
_SYSLOG_WIRED = {"arista_eos", "cisco_iosxe_cli", "juniper_junos"}


def test_syslog_declared_supported_matches_wired_roster() -> None:
    """`/system/syslog-server` is declared ``supported`` on EXACTLY the codecs
    that parse + render it.  Any drift from this roster means the Tier-1 docs
    (README / CAPABILITIES.md / canonical/README.md / intent.py / vendor pages)
    are stale — update them in the same change that moves a codec in or out."""
    declared = {
        c for c in _REAL_CODECS
        if _status(c, "/system/syslog-server") == "supported"
    }
    assert declared == _SYSLOG_WIRED, (
        f"syslog explicit-supported roster is {sorted(declared)}, expected "
        f"{sorted(_SYSLOG_WIRED)} — update the Tier-1 docs (README / "
        f"CAPABILITIES.md / canonical/README.md / intent.py / vendor pages) in "
        f"lockstep with this roster change."
    )
