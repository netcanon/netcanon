"""PR-2b (audit e5b77d7) walk-expansion guard for the VRRP/FHRP sub-fields.

The seven VRRP sub-field leaves (mode / priority / preempt /
advertisement_interval / authentication / virtual_ipv6s / description) were
tracked ``KNOWN_GAP`` exemptions in ``test_walker_completeness.py``: the group
anchor (``/interfaces/interface/vrrp-groups/group``) was walked but these
sub-paths were not, so ``classify()`` fail-opened any codec that downgrades or
drops them to ``supported`` -- a silent FHRP loss reported ``severity: ok``
(a cross-family mode reinterpretation, a dropped election parameter, etc.).

PR-2b walks them and adds the per-codec dispositions.  This guard pins BOTH
halves so a regression -- un-walking a path, or dropping a declaration so
``classify()`` silently fail-opens again -- turns RED.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.xpath_walker import _walk_canonical
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from tests.unit.migration.test_registry_capability_honesty import _maximal_intent

_BASE = "/interfaces/interface/vrrp-groups/group/"
_SUBPATHS = [
    _BASE + leaf for leaf in (
        "mode", "priority", "preempt", "advertisement-interval",
        "authentication", "virtual-ipv6s", "description",
    )
]

# The four codecs that render no FHRP at all -> every sub-path is unsupported.
_NO_FHRP = ("aruba_aoscx", "cisco_iosxe", "cisco_iosxr", "vyos")

# Verified disposition matrix (PR-2b).  A codec ABSENT from a leaf's dict
# relies on the classify() supported default BECAUSE it renders the field
# faithfully (verified against each codec's render.py); a codec LISTED here
# must carry an explicit lossy/unsupported declaration or the silent loss
# returns.  `mode` is lossy/unsupported on ALL 12 -- no codec renders every
# FHRP family, so the family discriminator never round-trips guaranteed.
_EXPECTED: dict[str, dict[str, str]] = {
    _BASE + "mode": dict.fromkeys(_NO_FHRP, "unsupported") | dict.fromkeys(
        (
            "arista_eos", "aruba_aoss", "cisco_iosxe_cli", "cisco_nxos",
            "fortigate_cli", "juniper_junos", "mikrotik_routeros", "opnsense",
        ),
        "lossy",
    ),
    _BASE + "priority": dict.fromkeys(_NO_FHRP, "unsupported"),
    _BASE + "preempt": dict.fromkeys(_NO_FHRP, "unsupported") | {"opnsense": "lossy"},
    _BASE + "advertisement-interval": dict.fromkeys(_NO_FHRP, "unsupported") | {
        "aruba_aoss": "lossy", "cisco_nxos": "lossy",
    },
    _BASE + "authentication": dict.fromkeys(_NO_FHRP, "unsupported") | {
        "aruba_aoss": "lossy",
    },
    _BASE + "virtual-ipv6s": dict.fromkeys(_NO_FHRP, "unsupported") | {
        "aruba_aoss": "lossy", "cisco_nxos": "lossy",
    },
    _BASE + "description": dict.fromkeys(_NO_FHRP, "unsupported") | {
        "aruba_aoss": "lossy", "cisco_nxos": "lossy",
        "fortigate_cli": "lossy", "mikrotik_routeros": "lossy",
    },
}


@pytest.mark.parametrize("path", _SUBPATHS)
def test_subpath_is_walked(path: str) -> None:
    """The maximal intent populates a full VRRP group, so every sub-path must
    be emitted by the walker (else classify() never sees it = silent loss)."""
    walked = set(_walk_canonical(_maximal_intent()))
    assert path in walked, f"{path} is no longer walked -- PR-2b regressed"


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
            f"(PR-2b disposition regression)"
        )


def test_mode_is_never_silently_supported() -> None:
    """The FHRP family discriminator can never round-trip guaranteed (no codec
    renders all of VRRP/HSRP/CARP), so EVERY codec must declare it lossy or
    unsupported -- never the supported fail-open default."""
    for name in list_public_codecs():
        d = get_codec(name).capabilities.classify(_BASE + "mode")
        assert d in {"lossy", "unsupported"}, (
            f"{name} classifies VRRP mode as {d!r} -- a cross-family FHRP "
            f"reinterpretation would report severity:ok"
        )
