"""Truth-maintenance guard for the Tier-1 timezone / syslog docs (#1).

The 2026-07-06 Fable review found the Tier-1 promise (README, CAPABILITIES.md,
canonical/README.md, intent.py, several vendor pages) claimed ``timezone`` and
``syslog_servers`` round-trip on every shipped codec, while ``timezone`` is
wired on **none** and ``syslog_servers`` is declared-supported on **none**
(juniper_junos renders it via a fail-open undeclared path).  The docs were
corrected to say so.

These guards pin the underlying matrix facts so a future codec that wires
either field trips the test — forcing the Tier-1 docs to be updated in
lockstep rather than silently drifting back into the over-promise.  They also
lock the honesty property that ``timezone``'s drop is *declared* (so the
cross-vendor unsupported banner fires) rather than undeclared (fail-open =
silent loss).
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


def test_syslog_not_declared_supported_on_any_codec() -> None:
    """No codec lists `/system/syslog-server` under ``supported`` — the docs
    say it is wired narrowly (juniper_junos, via a fail-open undeclared
    path), not a cross-vendor Tier-1 guarantee.  If a codec adds it to
    ``supported``, update the Tier-1 docs alongside."""
    offenders = [
        c for c in _REAL_CODECS
        if _status(c, "/system/syslog-server") == "supported"
    ]
    assert not offenders, (
        f"/system/syslog-server is now 'supported' on {offenders} — update the "
        f"Tier-1 docs to reflect the broader wiring."
    )
