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
  (``_esc``) + parse-side (widened regex + ``_unquote`` unescape).  That
  fix wrote ``\\"``, which no HPE page documents (only ``banner motd``
  takes escape characters, Basic Operation Guide 16.10 p.11), so a
  ``"`` in an AOS-S label or description is now written ``'`` and said
  (``_one_value.one_value_tree``, ``no_escape``) -- pinned in
  :class:`TestAossHasNoEscape` below, out of the round-trip table.
* ``mikrotik_routeros`` — ``_escape`` escaped ``"`` but NOT ``\\``
  (CODEC-3), and ``_KV_RE`` / ``_parse_kv`` couldn't span an escaped
  quote.  Fixed both sides.

VyOS is deliberately absent: its config validator rejects an embedded
double-quote in a value string *even when escaped* (vyos.dev/T1246), so
the correct fix there is sanitisation, not escaping — tracked separately.

Each device documentedly uses ``\\`` as the in-quote escape introducer
(Junos ``display set``, FortiOS CLI, RouterOS scripting), so the rendered
output is deployment-valid, and the matched parse-side unescape keeps the
netcanon round-trip byte-stable.
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


class TestAossHasNoEscape:
    """AOS-S quotes a VLAN name and a description and documents no escape
    inside the quotes, so a ``"`` is written ``'``, and the output says so
    in a review line for each place.  A value with no quote round-trips
    verbatim, white space and all."""

    @staticmethod
    def _render(desc: str, vlan_name: str) -> str:
        return ArubaAOSSCodec().render(CanonicalIntent(
            hostname="sw1",
            interfaces=[CanonicalInterface(name="1", description=desc)],
            vlans=[CanonicalVlan(id=10, name=vlan_name)],
        ))

    def test_a_quote_is_written_as_an_apostrophe_and_said(self):
        out = self._render('say "zqhi"', 'the "zqcore" vlan')
        assert "   name \"say 'zqhi'\"" in out
        assert "   name \"the 'zqcore' vlan\"" in out
        assert '\\"' not in out
        reviews = [
            ln for ln in out.splitlines()
            if ln.startswith(";") and "review:" in ln
        ]
        assert len(reviews) == 2
        assert any(ln.startswith("; the name of VLAN 10 ") for ln in reviews)
        assert any(
            ln.startswith("; the description of interface 1 ") for ln in reviews)
        # A review line names the place, never the value.
        assert not any("zq" in ln for ln in reviews)
        reparsed = ArubaAOSSCodec().parse(out)
        assert reparsed.interfaces[0].description == "say 'zqhi'"
        assert [v.name for v in reparsed.vlans if v.id == 10] == [
            "the 'zqcore' vlan"]

    def test_a_value_with_no_quote_round_trips(self):
        out = self._render("plain description", "the core vlan")
        assert "review:" not in out
        reparsed = ArubaAOSSCodec().parse(out)
        assert reparsed.interfaces[0].description == "plain description"
        assert [v.name for v in reparsed.vlans if v.id == 10] == [
            "the core vlan"]
