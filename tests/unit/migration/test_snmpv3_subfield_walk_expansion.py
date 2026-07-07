"""PR-2a (audit e5b77d7) walk-expansion guard for the SNMPv3 USM sub-fields.

The four SNMPv3 sub-field leaves (auth_protocol / priv_protocol /
priv_passphrase / group) were tracked ``KNOWN_GAP`` exemptions in
``test_walker_completeness.py``: the anchor (``/snmp/v3-user``) was walked but
these sub-paths were not, so ``classify()`` fail-opened any codec that drops or
downgrades them to ``supported`` -- a silent SNMPv3 crypto downgrade reported
``severity: ok``.

PR-2a walks them and adds the per-codec dispositions.  This guard pins BOTH
halves so a regression -- un-walking a path, or dropping a declaration so
``classify()`` silently fail-opens again -- turns RED.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.xpath_walker import _walk_canonical
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from tests.unit.migration.test_registry_capability_honesty import _maximal_intent

_SUBPATHS = [
    "/snmp/v3-user/auth-protocol",
    "/snmp/v3-user/priv-protocol",
    "/snmp/v3-user/priv-passphrase",
    "/snmp/v3-user/group",
]

# Verified disposition matrix (PR-2a).  A codec ABSENT from a leaf's dict relies
# on the classify() supported default BECAUSE it renders the field faithfully
# (verified against each codec's render.py); a codec LISTED here must carry an
# explicit lossy/unsupported declaration or the silent loss returns.
_EXPECTED: dict[str, dict[str, str]] = {
    "/snmp/v3-user/auth-protocol": {
        "aruba_aoscx": "lossy", "aruba_aoss": "lossy",
        "mikrotik_routeros": "lossy", "vyos": "lossy",
        "cisco_iosxe": "unsupported", "cisco_iosxr": "unsupported",
        "opnsense": "unsupported",
    },
    "/snmp/v3-user/priv-protocol": {
        "aruba_aoscx": "lossy", "aruba_aoss": "lossy", "fortigate_cli": "lossy",
        "mikrotik_routeros": "lossy", "vyos": "lossy",
        "cisco_iosxe": "unsupported", "cisco_iosxr": "unsupported",
        "opnsense": "unsupported",
    },
    "/snmp/v3-user/priv-passphrase": {
        "aruba_aoscx": "lossy", "cisco_nxos": "lossy", "vyos": "lossy",
        "cisco_iosxe": "unsupported", "cisco_iosxr": "unsupported",
        "opnsense": "unsupported",
    },
    "/snmp/v3-user/group": {
        "aruba_aoscx": "lossy", "fortigate_cli": "lossy",
        "mikrotik_routeros": "lossy",
        "cisco_iosxe": "unsupported", "cisco_iosxr": "unsupported",
        "opnsense": "unsupported",
    },
}


@pytest.mark.parametrize("path", _SUBPATHS)
def test_subpath_is_walked(path: str) -> None:
    """The maximal intent populates a full v3 user, so every sub-path must be
    emitted by the walker (else classify() never sees it = silent loss)."""
    walked = set(_walk_canonical(_maximal_intent()))
    assert path in walked, f"{path} is no longer walked -- PR-2a regressed"


@pytest.mark.parametrize("path", _SUBPATHS)
def test_every_codec_declares_or_faithfully_supports(path: str) -> None:
    """Every codec classifies each sub-path per the verified matrix; a codec
    that drops or downgrades the field must NOT silently rely on the supported
    default (that is exactly the silent loss the walk-expansion closes)."""
    for name in list_public_codecs():
        got = get_codec(name).capabilities.classify(path)
        exp = _EXPECTED[path].get(name, "supported")
        assert got == exp, (
            f"{name} classifies {path} as {got!r}, expected {exp!r} "
            f"(PR-2a disposition regression)"
        )
