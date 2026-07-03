"""Guard: no codec ``parse()`` leaks a raw pydantic ``ValidationError``.

A codec builds :class:`CanonicalIntent` models from parsed input.  When a
*parsed* value violates a field constraint — a VLAN id > 4094, an IPv4
prefix length > 32, a VRRP priority > 254, an HSRP group-id out of range —
pydantic raises a raw ``ValidationError``.  Left unhandled that leaks out of
``parse``: the HTTP routes 500, the CLI dumps a pydantic traceback.

``CodecBase.__init_subclass__`` wraps every codec's ``parse`` at the class
boundary so such a failure surfaces as the documented :class:`ParseError`
instead — one uniform boundary that generalises #229's single
sanitize-boundary conversion to *every* codec and *every* caller (pipeline,
mesh, sanitize, CLI, tests).

These tests lock the boundary in two ways:

* generically — a synthetic ``CodecBase`` subclass whose ``parse`` builds an
  out-of-range model must raise ``ParseError`` (proves the wrap applies to
  ANY subclass, not just the vendors probed below), and
* through real parse paths — vendor inputs that were verified to raise a raw
  ``ValidationError`` before the wrap must now raise ``ParseError``.
"""

from __future__ import annotations

from typing import Any

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalVlan
from netcanon.migration.codecs.base import CodecBase, ParseError
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import CapabilityMatrix

pytestmark = pytest.mark.unit


# Real vendor parse paths that construct an OUT-OF-RANGE canonical value.
# Each was verified to raise a raw pydantic ValidationError BEFORE the
# boundary wrap (repro 2026-07); the boundary must turn every one into a
# ParseError whose message names the offending canonical field.
# (codec, label, raw, expected loc-fragment in the message)
_OUT_OF_RANGE_INPUTS = [
    ("cisco_nxos", "vlan-id-gt-4094",
     "hostname n\nvlan 5000\n  name X\n", "id"),
    ("cisco_nxos", "ipv4-prefix-gt-32",
     "hostname n\ninterface Vlan10\n  ip address 10.0.0.1/33\n", "prefix_length"),
    ("cisco_nxos", "hsrp-priority-gt-254",
     "hostname n\ninterface Vlan10\n  hsrp 10\n    priority 300\n", "priority"),
    ("cisco_iosxe_cli", "vlan-id-gt-4094",
     "hostname n\nvlan 5000\n name X\n", "id"),
    ("cisco_iosxe_cli", "vrrp-priority-gt-254",
     "hostname n\ninterface Vlan10\n vrrp 10 priority 300\n vrrp 10 ip 10.0.0.1\n",
     "priority"),
    ("arista_eos", "vlan-id-gt-4094",
     "hostname n\nvlan 5000\n   name X\n", "id"),
]


@pytest.mark.parametrize(
    "codec_name,label,raw,loc",
    _OUT_OF_RANGE_INPUTS,
    ids=[f"{c}-{lab}" for c, lab, *_ in _OUT_OF_RANGE_INPUTS],
)
def test_out_of_range_parse_raises_parse_error(codec_name, label, raw, loc):
    """A vendor parse path that builds an out-of-range model surfaces a
    ``ParseError`` — never a raw pydantic ``ValidationError``.

    ``pytest.raises(ParseError)`` also fails if a ``ValidationError`` leaks
    (it is not a ``ParseError`` subclass), so this asserts the conversion.
    """
    codec = get_codec(codec_name)
    with pytest.raises(ParseError) as excinfo:
        codec.parse(raw)
    msg = str(excinfo.value)
    assert "could not be represented" in msg
    assert codec_name in msg
    assert loc in msg
    # The originating ValidationError is chained for debuggability.
    assert excinfo.value.__cause__ is not None


# ---------------------------------------------------------------------------
# Synthetic subclasses — prove the boundary is generic (applies to ANY codec)
# and transparent (passes valid input + pre-raised ParseErrors through).
# Defining a CodecBase subclass does NOT register it (registration is the
# explicit @register decorator), so these are inert throwaways.
# ---------------------------------------------------------------------------


class _RaisingCodec(CodecBase):
    """parse() builds an out-of-range model (VLAN id 9999 > le=4094)."""

    name = "raising_boundary_test_codec"

    @property
    def capabilities(self) -> CapabilityMatrix:
        return CapabilityMatrix(adapter=self.name)

    def parse(self, raw: str) -> CanonicalIntent:
        return CanonicalIntent(vlans=[CanonicalVlan(id=9999)])

    def render(self, tree: Any) -> str:
        return ""


class _PassthroughParseErrorCodec(CodecBase):
    """parse() raises ParseError directly — must pass through unaltered."""

    name = "passthrough_boundary_test_codec"

    @property
    def capabilities(self) -> CapabilityMatrix:
        return CapabilityMatrix(adapter=self.name)

    def parse(self, raw: str) -> CanonicalIntent:
        raise ParseError("original boom", path="ifaces/0", snippet="line 1")

    def render(self, tree: Any) -> str:
        return ""


class _ValidInputCodec(CodecBase):
    """parse() returns a valid model — the wrap must be transparent."""

    name = "valid_boundary_test_codec"

    @property
    def capabilities(self) -> CapabilityMatrix:
        return CapabilityMatrix(adapter=self.name)

    def parse(self, raw: str) -> CanonicalIntent:
        return CanonicalIntent(hostname="host-1", vlans=[CanonicalVlan(id=10)])

    def render(self, tree: Any) -> str:
        return ""


def test_boundary_wraps_arbitrary_subclass():
    """The __init_subclass__ wrap fires for ANY CodecBase subclass, not just
    the shipped vendors — an out-of-range model becomes a named ParseError."""
    with pytest.raises(ParseError) as excinfo:
        _RaisingCodec().parse("anything")
    msg = str(excinfo.value)
    assert "raising_boundary_test_codec" in msg
    assert "could not be represented" in msg
    assert "id" in msg


def test_boundary_passes_parse_error_through_unaltered():
    """A ParseError raised by parse() is not re-wrapped — message, path and
    snippet survive so the caller keeps the codec's own diagnostics."""
    with pytest.raises(ParseError) as excinfo:
        _PassthroughParseErrorCodec().parse("x")
    assert str(excinfo.value) == "original boom"
    assert excinfo.value.path == "ifaces/0"
    assert excinfo.value.snippet == "line 1"


def test_boundary_transparent_for_valid_input():
    """Valid input round-trips through the wrap with no behaviour change."""
    intent = _ValidInputCodec().parse("x")
    assert intent.hostname == "host-1"
    assert intent.vlans[0].id == 10


def test_every_registered_codec_parse_is_wrapped():
    """Structural guard: every shipped codec's own ``parse`` carries the
    boundary marker, so a future codec that forgets it can't slip through
    (the wrap is applied by __init_subclass__, not opt-in per codec)."""
    from netcanon.migration.codecs.registry import list_codecs

    unwrapped = []
    for name in list_codecs():
        codec = get_codec(name)
        parse_fn = type(codec).__dict__.get("parse")
        # Only codecs that define their OWN parse need the marker; any that
        # inherit it are covered on the class that defined it.
        if parse_fn is not None and not getattr(
            parse_fn, "_nc_parse_wrapped", False
        ):
            unwrapped.append(name)
    assert not unwrapped, (
        f"codec parse() not wrapped by the ValidationError boundary: "
        f"{unwrapped}"
    )
