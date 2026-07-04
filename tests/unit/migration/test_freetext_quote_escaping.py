"""Free-text quote / backslash escaping round-trips (CODEC-1 / CODEC-3).

2026-07-03 Fable review, "hardened path / un-hardened sibling":
``juniper_junos`` escapes ``"`` and ``\\`` inside its quoted free-text
fields (``_quote_if_needed``/``_quote_always``) so a description like
``Link "A"`` renders as valid, round-trip-stable config.  Three siblings
did not:

* ``fortigate_cli`` — emitted ``set alias "Link "A""`` (the inner quote
  closes the literal early); the FortiOS ``shlex``-based parser then read
  it back mangled.  Fixed render-side (``_esc``); parse already unescapes
  via ``shlex.split(posix=True)``.
* ``aruba_aoss`` — emitted ``name "Link "A""`` and the ``"?([^"\\n]+)"?``
  name regex truncated at the first inner quote.  Fixed render-side
  (``_esc``) + parse-side (widened regex + ``_unquote`` unescape).
* ``mikrotik_routeros`` — ``_escape`` escaped ``"`` but NOT ``\\``
  (CODEC-3), and ``_KV_RE`` / ``_parse_kv`` couldn't span an escaped
  quote.  Fixed both sides.

VyOS is deliberately absent: its config validator rejects an embedded
double-quote in a value string *even when escaped* (vyos.dev/T1246), so
the correct fix there is sanitisation, not escaping — tracked separately.

Each device documentedly uses ``\\`` as the in-quote escape introducer
(Junos ``display set``, FortiOS CLI, RouterOS scripting, AOS-S variable
files), so the rendered output is deployment-valid, and the matched
parse-side unescape keeps the netcanon round-trip byte-stable.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalVlan,
)
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.fortigate_cli.codec import FortiGateCLICodec
from netcanon.migration.codecs.mikrotik_routeros.codec import (
    MikroTikRouterOSCodec,
)

pytestmark = pytest.mark.unit


# (codec factory, description-length cap the codec applies, or None)
_CODECS = [
    pytest.param(FortiGateCLICodec, 25, id="fortigate_cli"),
    pytest.param(ArubaAOSSCodec, None, id="aruba_aoss"),
    pytest.param(MikroTikRouterOSCodec, None, id="mikrotik_routeros"),
]

# Free-text values that stress the two escape-significant characters.
_VALUES = [
    "plain description",
    'has a "quoted" word',
    'ends with a quote"',
    '"starts with a quote',
    "has a back\\slash",
    'both a "quote" and a \\ backslash',
    "trailing backslash\\",
    "just one quote \"",
]


def _rt_description(codec, desc: str) -> str | None:
    intent = CanonicalIntent(
        hostname="sw1",
        interfaces=[CanonicalInterface(name="eth0", description=desc)],
    )
    reparsed = codec.parse(codec.render(intent))
    return next((i.description for i in reparsed.interfaces), None)


class TestFreeTextRoundTrip:
    @pytest.mark.parametrize("codec_cls, cap", _CODECS)
    @pytest.mark.parametrize("value", _VALUES)
    def test_description_round_trips(self, codec_cls, cap, value):
        expected = value[:cap] if cap is not None else value
        assert _rt_description(codec_cls(), value) == expected

    @pytest.mark.parametrize("codec_cls, cap", _CODECS)
    def test_embedded_quote_is_escaped_in_render(self, codec_cls, cap):
        """The rendered config must escape the inner quote (``\\"``) rather
        than emit a bare ``"`` that closes the quoted literal early — that
        is what makes the output valid on a real device."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(name="eth0", description='say "hi"'),
            ],
        )
        out = codec_cls().render(intent)
        # The escaped sequence appears; a bare unescaped ``"hi"`` fragment
        # (quote-word-quote with no preceding backslash) does not.
        assert '\\"' in out
        assert 'say "hi"' not in out


class TestVlanNameRoundTrip:
    """aruba_aoss quotes the VLAN *name* free-text field too, and (unlike
    mikrotik, which stores the human label on ``vlan.description`` and uses
    the iface name as ``vlan.name`` by design) round-trips it verbatim."""

    def test_aoss_vlan_name_with_quote_round_trips(self):
        intent = CanonicalIntent(
            hostname="sw1",
            vlans=[CanonicalVlan(id=10, name='the "core" vlan')],
        )
        out = ArubaAOSSCodec().render(intent)
        reparsed = ArubaAOSSCodec().parse(out)
        v10 = next((v for v in reparsed.vlans if v.id == 10), None)
        assert v10 is not None
        assert v10.name == 'the "core" vlan'
