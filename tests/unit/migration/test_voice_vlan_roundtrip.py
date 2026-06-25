"""Voice-VLAN (``switchport voice vlan N``) round-trip + cross-codec
disposition honesty — blind-audit ``65f9c01`` finding #11.

The renderer emitted ``switchport voice vlan N`` but the parser never
captured it, so a real Cisco config's per-port voice binding parsed to
``None`` and self-validation reported ``severity: ok`` with
``/interfaces/interface/voice-vlan`` defaulting to ``supported`` — the
``classify()`` default for an *undeclared* path. That is the silent-loss
class: a populated leaf the codec silently drops while claiming success.

The fix has two arms:

1. ``cisco_iosxe_cli`` gains the parse rule (``_SWITCHPORT_VOICE_RE``) so
   voice-vlan fully round-trips same-vendor, and declares it ``supported``.
2. Every codec that drops it on render declares it ``unsupported`` so the
   loss is *declared* (a validation banner), never silent. Critically:
   adding only arm 1 would let a now-parseable ``voice_vlan`` flow into
   those targets and silently vanish — arm 2 is what keeps the class
   closed, not just the named instance.

The honesty guard below triggers on a codec leaving voice-vlan at the
silent default (in neither the supported nor the unsupported list) — the
existence-trigger that catches a future codec which renders voice without
declaring it, OR a new codec that forgets the surface entirely.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.registry import get_codec, list_public_codecs

pytestmark = pytest.mark.unit

_VOICE_XPATH = "/interfaces/interface/voice-vlan"

#: The only codec that both parses AND renders voice-vlan → genuinely
#: round-trips it. Every other public codec drops it on render and must
#: declare it unsupported.
_SUPPORTING = {"cisco_iosxe_cli"}

_CFG = """hostname SW1
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
 switchport voice vlan 20
!
"""


def _gi(intent, name="GigabitEthernet1/0/1"):
    return next(i for i in intent.interfaces if i.name == name)


class TestVoiceVlanParse:
    def test_parse_captures_voice_vlan(self):
        gi = _gi(CiscoIOSXECLICodec().parse(_CFG))
        assert gi.voice_vlan == 20
        # Sibling access binding on the same line block is unaffected.
        assert gi.access_vlan == 10

    def test_round_trip_preserves_voice_vlan(self):
        c = CiscoIOSXECLICodec()
        intent = c.parse(_CFG)
        out = c.render(intent)
        assert "switchport voice vlan 20" in out
        assert _gi(c.parse(out)).voice_vlan == 20

    def test_absent_voice_line_parses_none(self):
        intent = CiscoIOSXECLICodec().parse(
            "interface GigabitEthernet1/0/2\n"
            " switchport access vlan 5\n!\n"
        )
        assert _gi(intent, "GigabitEthernet1/0/2").voice_vlan is None


class TestVoiceVlanDispositionHonesty:
    """Every public codec must EXPLICITLY classify voice-vlan — never ride
    the silent ``classify()`` 'supported' default (the #11 class)."""

    @pytest.mark.parametrize("name", list_public_codecs())
    def test_voice_vlan_is_explicitly_declared(self, name):
        m = get_codec(name).capabilities
        in_supported = _VOICE_XPATH in m.supported
        in_unsupported = _VOICE_XPATH in {u.path for u in m.unsupported}
        assert in_supported or in_unsupported, (
            f"{name}: voice-vlan is not explicitly declared in the capability "
            f"matrix -> it rides the classify() 'supported' default, so a "
            f"dropped voice binding reports severity:ok (the silent-loss class "
            f"#11). Declare it supported (codec round-trips it) or unsupported "
            f"(codec drops it on render)."
        )
        if name in _SUPPORTING:
            assert in_supported and not in_unsupported, (
                f"{name} parses+renders voice-vlan → must be 'supported'"
            )
        else:
            assert in_unsupported and not in_supported, (
                f"{name} drops voice-vlan on render → must be 'unsupported'"
            )
