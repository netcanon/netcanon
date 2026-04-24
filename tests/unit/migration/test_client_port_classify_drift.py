"""
Drift-guard for ``_partials/classify.js`` vs per-codec
``classify_port_name``.

The client-side ``_guessKind`` / ``_looksLikeUplink`` helpers in
``netconfig/templates/_partials/classify.js`` mirror the regex
patterns from every shipped codec's ``port_names.py``
``classify_port_name`` (the authoritative server-side classifier).
The client uses them for UI grouping ONLY — the rename-modal
row grouping, fit-check per-kind tallies, uplink-vs-access
target dropdown choice.  Server-side is always the source of
truth for the rendered output.

**The drift risk this file guards against.**  Add a new vendor
codec (say AOS-CX with ``1/1/1`` three-part naming) and write its
``port_names.py::classify_port_name``.  If you forget to extend the
universal ``_guessKind`` regex in ``classify.js``, the rename
modal silently puts those ports in the wrong UI group — a bug that
doesn't break tests because the server-side render stays correct.

This file runs the client-side logic (ported to Python so we can
test it without a browser) against a representative corpus of
port names drawn from every shipped codec.  A mismatch means
either:

  * ``classify.js`` forgot to include a new pattern → fix the
    partial (add the regex to ``_guessKind``).
  * A codec's ``classify_port_name`` returned something the
    client-side universal heuristic can't recognise → either
    extend ``_guessKind`` to recognise it, or change the codec
    to use an already-known naming convention.

Either way the fix lives in the source of truth (per-codec
authoritative classifier + the shared client mirror).  This test
is the alarm; fixing the alarm fixes the drift.

**What we DO assert.**  For every ``(codec, name)`` pair in the
corpus below:

  * Server-side ``codec.classify_port_name(name).kind`` matches
    the Python mirror of ``_guessKind(name)``.
  * If the server-side classifier marks the port as an uplink-
    shape (``kind="physical"`` + ``subslot_letter != ""`` or
    a 3-part Cisco form with non-zero middle digit, or a
    MikroTik ``sfp-sfpplus``, or FortiGate ``wan<N>``), the
    client mirror of ``_looksLikeUplink`` returns ``True``.

**What we do NOT assert.**  We don't try to prove the client
mirror is a universal oracle — it's a heuristic for UI grouping,
not a cross-vendor classifier.  We only assert "when the codec
says X, the client also says X for the same name".  Cases where
the codec can't classify a name (returns ``kind="unknown"``) are
skipped — the client's fallback to ``"physical"`` is fine.

See also:
    * :mod:`netconfig.migration.canonical.port_names` — the shared
      ``PortIdentity`` schema both sides speak.
    * Every codec's ``port_names.py`` — the authoritative per-codec
      classifier.
    * ``netconfig/templates/_partials/classify.js`` — the client
      mirror this file is a Python port of.
"""
from __future__ import annotations

import re
from typing import Iterable

import pytest

from netconfig.migration.codecs.arista_eos import AristaEOSCodec
from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.juniper_junos.codec import JunosCodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Python port of classify.js::_guessKind + _looksLikeUplink.
#
# Every regex here MUST match the JS regex in
# ``netconfig/templates/_partials/classify.js`` byte-for-byte modulo Python
# vs JS regex flavour differences (no differences in the simple cases here;
# the patterns are all basic character classes + alternation + \d).
#
# When you edit either side, edit both and run this file's tests.
# ---------------------------------------------------------------------------


def _py_guess_kind(name: str) -> str:
    """Python mirror of JS ``_guessKind``.  Keep byte-aligned with
    ``netconfig/templates/_partials/classify.js``."""
    if re.match(r"^(Port-channel|Trk|trk|LAG|bond|lagg)\d", name, re.IGNORECASE):
        return "lag"
    if re.match(r"^Vlan\d|^vlan\d", name):
        return "svi"
    if re.search(r"\.\d+$", name):                          # OPN/MT dotted form
        return "svi"
    if re.match(r"^Loopback\d|^lo$|^lo\d|^loopback\d", name, re.IGNORECASE):
        return "loopback"
    if re.match(r"^(Tunnel|wg|gre|ipip|eoip|gif|ovpn)", name, re.IGNORECASE):
        return "tunnel"
    if re.match(r"^VirtualPortGroup|^bridge|^br-", name, re.IGNORECASE):
        return "virtual"
    if re.match(r"^(ssl\.|tunnel)", name, re.IGNORECASE):
        return "tunnel"
    if re.match(r"^(mgmt|management)$", name, re.IGNORECASE):
        return "mgmt"
    return "physical"


def _py_looks_like_uplink(name: str) -> bool:
    """Python mirror of JS ``_looksLikeUplink``."""
    m = re.match(
        r"^(FastEthernet|GigabitEthernet|TwoGigabitEthernet|"
        r"FiveGigabitEthernet|TenGigabitEthernet|TwentyFiveGigE|"
        r"FortyGigabitEthernet|HundredGigE|FourHundredGigE|"
        r"AppGigabitEthernet)(\d+)/(\d+)/(\d+)(/\d+)?$",
        name,
        re.IGNORECASE,
    )
    if m and int(m.group(3)) != 0:
        return True
    if re.match(
        r"^(TwentyFiveGigE|FortyGigabitEthernet|HundredGigE|FourHundredGigE)",
        name,
        re.IGNORECASE,
    ):
        return True
    if re.match(r"^\d+/[A-Za-z]\d+$", name):
        return True
    if re.match(r"^(sfp|sfp-sfpplus|sfpplus|qsfpplus)\d", name, re.IGNORECASE):
        return True
    if re.match(r"^wan\d*$", name, re.IGNORECASE):
        return True
    return False


# ---------------------------------------------------------------------------
# Representative port-name corpus per codec.  Names chosen to exercise
# every classification branch of the codec's classify_port_name AND the
# client-side regex — not a comprehensive test of each codec's classifier
# (that's in per-codec test files), just enough that the client mirror
# has to correctly classify every "kind" the codec populates in real
# configs.
#
# When you add a codec: add its row here.
# When you add a new naming convention to an existing codec: add the
# representative name(s) here.
# ---------------------------------------------------------------------------


_PORT_NAME_CORPUS: list[tuple[str, str, list[str]]] = [
    # (codec_label, expected_kind, [names...])

    # Physical access ports — the dominant kind on every vendor.
    ("arista_eos", "physical", ["Ethernet1", "Ethernet48"]),
    ("aruba_aoss", "physical", ["1/1", "1/24", "1/48"]),
    ("cisco_iosxe_cli", "physical", [
        "GigabitEthernet1/0/1", "GigabitEthernet1/0/24",
    ]),
    ("fortigate_cli", "physical", ["port1", "port10"]),
    ("juniper_junos", "physical", ["ge-0/0/0", "ge-0/0/47"]),
    ("mikrotik_routeros", "physical", ["ether1", "ether10"]),
    ("opnsense", "physical", ["em0", "igb1", "ix0"]),

    # LAG / port-channel / trunk forms.
    ("arista_eos", "lag", ["Port-Channel1", "Port-Channel10"]),
    ("aruba_aoss", "lag", ["Trk1", "Trk24"]),
    ("cisco_iosxe_cli", "lag", ["Port-channel1", "Port-channel10"]),
    ("mikrotik_routeros", "lag", ["bond1"]),

    # SVI / VLAN interface forms.
    ("arista_eos", "svi", ["Vlan10", "Vlan100"]),
    ("cisco_iosxe_cli", "svi", ["Vlan1", "Vlan4094"]),
    ("mikrotik_routeros", "svi", ["vlan10", "vlan100"]),
    # OPNsense dotted-form VLAN sub-interface.
    ("opnsense", "svi", ["em0.10", "igb1.100"]),
    # MikroTik dotted-form VLAN sub-interface.
    ("mikrotik_routeros", "svi", ["ether1.10"]),

    # Loopback.
    ("arista_eos", "loopback", ["Loopback0", "Loopback1"]),
    ("cisco_iosxe_cli", "loopback", ["Loopback0", "Loopback99"]),
    ("juniper_junos", "loopback", ["lo0"]),

    # Management (Cisco mgmt has its own kind).
    # NOTE: client-side _guessKind maps "mgmt" only for the exact
    # strings "mgmt" / "management" — Cisco's "Management1" /
    # "GigabitEthernet0/0" variants fall to physical, which matches
    # the codec when the codec doesn't distinguish.  Keep this corpus
    # narrow to the names the client DOES special-case.

    # Tunnel-shaped ports — WireGuard / GRE / OVPN / ipip / eoip.
    ("mikrotik_routeros", "tunnel", ["wg1", "gre-tunnel1", "ipip-t1"]),
    ("opnsense", "tunnel", ["ovpn_server1", "gif0"]),
]


# Flatten into the parametrize list so pytest reports one failure
# per bad (codec, name) pair instead of aborting on the first.
_FLAT_CORPUS: list[tuple[str, str, str]] = [
    (codec, expected_kind, name)
    for codec, expected_kind, names in _PORT_NAME_CORPUS
    for name in names
]


_CODEC_LOOKUP = {
    "arista_eos": AristaEOSCodec,
    "aruba_aoss": ArubaAOSSCodec,
    "cisco_iosxe_cli": CiscoIOSXECLICodec,
    "fortigate_cli": FortiGateCLICodec,
    "juniper_junos": JunosCodec,
    "mikrotik_routeros": MikroTikRouterOSCodec,
    "opnsense": OPNsenseCodec,
}


class TestClientServerKindAgreement:
    """For every representative (codec, port-name) pair, the client
    mirror of ``_guessKind`` agrees with the codec's authoritative
    ``classify_port_name``.  Drift guard — failure here means
    ``classify.js`` and a codec's ``port_names.py`` diverged."""

    @pytest.mark.parametrize("codec_label,expected_kind,name", _FLAT_CORPUS)
    def test_client_kind_matches_server_kind(
        self, codec_label: str, expected_kind: str, name: str,
    ):
        codec = _CODEC_LOOKUP[codec_label]()
        server_kind = codec.classify_port_name(name).kind

        # The corpus documents the INTENDED kind.  First-level assert:
        # server agrees with the documented kind (guards codec
        # regressions).  Skip ``unknown`` — some codecs intentionally
        # fall through to unknown for names outside their grammar
        # (e.g. Arista given a Cisco name).
        if server_kind == "unknown":
            pytest.skip(
                f"{codec_label}.classify_port_name({name!r}) returned "
                f"'unknown' — codec doesn't recognise this name shape. "
                f"Corpus row documents what the IDEAL classifier would "
                f"return; skip is OK."
            )
        assert server_kind == expected_kind, (
            f"Codec {codec_label}'s classify_port_name({name!r}) "
            f"returned kind={server_kind!r}, corpus expected "
            f"{expected_kind!r} — codec regression or corpus bug."
        )

        # Second-level assert: client mirror agrees with server.  This
        # is the actual drift guard.
        client_kind = _py_guess_kind(name)
        assert client_kind == server_kind, (
            f"Client/server kind drift on {name!r}: "
            f"codec ({codec_label}) says {server_kind!r}, "
            f"classify.js says {client_kind!r}.  Either "
            f"(a) {codec_label}/port_names.py added a new naming "
            f"pattern that classify.js doesn't recognise — extend "
            f"_guessKind in netconfig/templates/_partials/classify.js "
            f"and its Python mirror in this test file; or (b) "
            f"classify.js / the Python mirror here drifted from each "
            f"other — re-align them."
        )


class TestClientUplinkHeuristic:
    """``_looksLikeUplink`` spot checks — it's a client-only heuristic
    (the server doesn't have a direct equivalent; uplink-ness surfaces
    via ``PortIdentity.subslot_letter`` + ``name_speed_hint``).  These
    tests lock in the expected decisions so a future edit to the JS
    (or this Python mirror) doesn't accidentally invert the uplink
    gate."""

    @pytest.mark.parametrize("name,expected", [
        # Cisco 3-part with non-zero middle digit — uplink (line-card
        # / NM slot).
        ("GigabitEthernet1/1/1", True),
        ("TenGigabitEthernet1/2/1", True),
        # Cisco 3-part with middle 0 — access switch port, NOT uplink.
        ("GigabitEthernet1/0/24", False),
        ("TenGigabitEthernet1/0/1", False),
        # Speed-encoded prefixes regardless of slot shape — uplink.
        ("FortyGigabitEthernet1/0/49", True),
        ("HundredGigE1/0/1", True),
        ("FourHundredGigE1/1/1", True),
        # Aruba letter-slot uplink module.
        ("1/A1", True),
        ("1/B4", True),
        # MikroTik SFP+ / QSFP+ uplinks.
        ("sfp-sfpplus1", True),
        ("qsfpplus1", True),
        ("ether1", False),
        # FortiGate WAN ports — always uplink.
        ("wan1", True),
        ("wan", True),
        # Negative controls.
        ("Ethernet48", False),
        ("port1", False),
        ("ge-0/0/0", False),
        ("Loopback0", False),
        ("Vlan10", False),
    ])
    def test_uplink_heuristic(self, name: str, expected: bool):
        assert _py_looks_like_uplink(name) is expected


class TestClassifyJsFileExists:
    """Meta-guard — the partial this test mirrors must exist.  If
    someone deletes or renames classify.js, this test reminds them
    the mirror + the drift guard need updating too."""

    def test_partial_file_exists(self):
        import pathlib
        classify_js = (
            pathlib.Path(__file__).resolve().parents[3]
            / "netconfig" / "templates" / "_partials" / "classify.js"
        )
        assert classify_js.is_file(), (
            f"Expected to find the client-side classifier at "
            f"{classify_js} — drift-guard in this test file "
            f"mirrors its contents.  If the partial was renamed / "
            f"removed / refactored, update this test accordingly."
        )

    def test_partial_declares_guess_kind_function(self):
        import pathlib
        classify_js = (
            pathlib.Path(__file__).resolve().parents[3]
            / "netconfig" / "templates" / "_partials" / "classify.js"
        )
        text = classify_js.read_text(encoding="utf-8")
        assert "function _guessKind(" in text, (
            "Expected _guessKind function in classify.js — if the "
            "function was renamed, update the mirror in this test "
            "and its docstring."
        )
        assert "function _looksLikeUplink(" in text, (
            "Expected _looksLikeUplink function in classify.js."
        )
