"""ReDoS hardening guard for the parse.py regexes CodeQL flagged
(``py/polynomial-redos`` alerts #124-#128, plus #151 — the arista_eos VRF
description regex that #327 reintroduced with the same lazy shape).

Each pattern paired a ``\\s+`` separator (or a greedy ``(\\S+)`` next-hop) with a
value group whose character class OVERLAPPED it (``.+`` / ``.+?`` / ``.*`` all
match whitespace; ``.`` matches the same non-space the next-hop did), so the
engine could split the same run two ways -> polynomial backtracking on a long
attacker-controlled line (the migrate / sanitize API parses pasted config text).

The fix anchors the value boundary on a disjoint class (``\\S`` for the
value-capturing patterns, ``\\s`` for the static-route trailing group), which is
unambiguous AND behaviour-identical because every consumer ``.split()``s or
``.strip()``s the captured group.  This guard pins BOTH halves:

* the patterns still CAPTURE the right value on representative real lines, and
* the exact attack strings CodeQL named complete in linear time (a regression to
  a catastrophic pattern would blow the budget).
"""
from __future__ import annotations

import time

import pytest

from netcanon.migration.codecs.arista_eos.parse import (
    _DHCP_DNS_SERVER_RE,
)
from netcanon.migration.codecs.arista_eos.parse import (
    _VRF_DESC_RE as _ARISTA_VRF_DESC_RE,
)
from netcanon.migration.codecs.arista_eos.parse import (
    _VRRP_DESCRIPTION_RE as _ARISTA_VRRP_DESCRIPTION_RE,
)
from netcanon.migration.codecs.aruba_aoscx.parse import _VLAN_TRUNK_ALLOWED_RE
from netcanon.migration.codecs.aruba_aoss.parse import _VRRP_AUTH_PLAINTEXT_RE
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    _STATIC_ROUTE_RE,
)
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    _VRF_DESCRIPTION_RE as _IOSXE_VRF_DESCRIPTION_RE,
)
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    _VRRP_DESCRIPTION_RE as _IOSXE_VRRP_DESCRIPTION_RE,
)
from netcanon.migration.codecs.cisco_nxos.parse import (
    _VRF_DESCRIPTION_RE as _NXOS_VRF_DESCRIPTION_RE,
)
from netcanon.migration.codecs.fortigate_cli.parse import (
    _CONFIG_HEADER_RE,
    _EDIT_HEADER_RE,
)

pytestmark = pytest.mark.unit

#: Generous ceiling: the hardened patterns are linear (microseconds on these
#: inputs); a polynomial/exponential regression would take seconds-to-minutes.
_BUDGET_S = 1.0
_REPS = 200_000


def _timed_match(rx, text):
    start = time.perf_counter()
    m = rx.match(text)
    return m, time.perf_counter() - start


# ---------------------------------------------------------------------------
# Behaviour preserved: the hardened patterns still capture the right value.
# ---------------------------------------------------------------------------


def test_dns_server_still_captures():
    m = _DHCP_DNS_SERVER_RE.match("   dns-server   8.8.8.8   1.1.1.1  ")
    assert m and m.group(1).split() == ["8.8.8.8", "1.1.1.1"]


def test_vlan_trunk_allowed_still_captures():
    assert _VLAN_TRUNK_ALLOWED_RE.match("   vlan trunk allowed 10-20,30 ").group(1).strip() == "10-20,30"
    assert _VLAN_TRUNK_ALLOWED_RE.match("   vlan trunk allowed all").group(1).strip() == "all"


def test_vrf_description_still_captures():
    # arista_eos joined this set in #151 — #327 reintroduced the lazy
    # ``(.+?)\\s*$`` shape the #124-#128 pass had eliminated everywhere else.
    for rx in (
        _NXOS_VRF_DESCRIPTION_RE,
        _IOSXE_VRF_DESCRIPTION_RE,
        _ARISTA_VRF_DESC_RE,
    ):
        assert rx.match("  description   Uplink to core  ").group(1).strip() == "Uplink to core"


def test_static_route_still_captures_and_keeps_trailing_tokens():
    m = _STATIC_ROUTE_RE.match("ip route vrf RED 10.0.0.0 255.0.0.0 192.0.2.1 200 name UP")
    assert m.group(1, 2, 3, 4) == ("RED", "10.0.0.0", "255.0.0.0", "192.0.2.1")
    assert (m.group(5) or "").split() == ["200", "name", "UP"]
    # No trailing tokens -> next-hop is the last token, trailing group is empty.
    bare = _STATIC_ROUTE_RE.match("ip route 0.0.0.0 0.0.0.0 192.0.2.1")
    assert bare.group(2, 3, 4) == ("0.0.0.0", "0.0.0.0", "192.0.2.1")
    assert (bare.group(5) or "").split() == []


# --- #337-follow-up siblings: the same lazy ``(.+?)\s*$`` shape survived in
#     five more parse.py patterns (fortigate config/edit headers, arista + iosxe
#     inline VRRP descriptions, aoss plaintext-password) -- all now ``(\S.*)$``.


def test_config_edit_headers_still_capture():
    # fortigate section/edit headers -- consumer .strip().strip('"').strip("'").
    assert _CONFIG_HEADER_RE.match("config system global  ").group(1).strip() == "system global"
    assert _EDIT_HEADER_RE.match('edit "port1"').group(1).strip().strip('"') == "port1"


def test_vrrp_description_still_captures():
    # arista has no leading indent (``^vrrp``); iosxe requires it (``^\s+vrrp``).
    assert _ARISTA_VRRP_DESCRIPTION_RE.match("vrrp 5 description core gw  ").group(2).strip() == "core gw"
    assert _IOSXE_VRRP_DESCRIPTION_RE.match(" vrrp 5 description core gw  ").group("text").strip() == "core gw"


def test_vrrp_plaintext_auth_still_captures():
    # aoss captures the value verbatim (incl. any surrounding quotes); the
    # consumer ``.strip().strip('"')``s it -- quoted / bare / trailing-space
    # all normalise to the same token.
    for line, want in [
        ('authentication mode plaintext-password "secret"', "secret"),
        ("authentication mode plaintext-password secret", "secret"),
        ("authentication mode plaintext-password secret   ", "secret"),
    ]:
        assert _VRRP_AUTH_PLAINTEXT_RE.match(line).group(1).strip().strip('"') == want


# ---------------------------------------------------------------------------
# ReDoS gone: CodeQL's own attack strings complete in linear time.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rx", "attack"),
    [
        (_DHCP_DNS_SERVER_RE, "   dns-server " + "  " * _REPS),          # #124
        (_VLAN_TRUNK_ALLOWED_RE, "   vlan trunk allowed " + "  " * _REPS),  # #125
        (_NXOS_VRF_DESCRIPTION_RE, "   description " + "  " * _REPS),     # #126
        (_IOSXE_VRF_DESCRIPTION_RE, "   description " + "  " * _REPS),    # #127
        (_STATIC_ROUTE_RE, "ip route 9.9.9.9 9.9.9.9 !" + "!!" * _REPS),  # #128
        # arista lazy ``(.+?)\s*$`` blows up specifically when the value
        # STARTS with a non-space so the greedy ``\s+`` can't absorb the run;
        # the trailing ``!`` defeats ``\s*$`` and forces the O(n^2) rescan.
        (_ARISTA_VRF_DESC_RE, "   description a" + " " * _REPS + "!"),    # #151
        # #337-follow-up siblings (same value-then-padding-then-non-space shape).
        (_CONFIG_HEADER_RE, "config a" + " " * _REPS + "!"),
        (_EDIT_HEADER_RE, "edit a" + " " * _REPS + "!"),
        (_ARISTA_VRRP_DESCRIPTION_RE, "vrrp 1 description a" + " " * _REPS + "!"),
        (_IOSXE_VRRP_DESCRIPTION_RE, " vrrp 1 description a" + " " * _REPS + "!"),
        (_VRRP_AUTH_PLAINTEXT_RE, "authentication mode plaintext-password a" + " " * _REPS + "!"),
    ],
    ids=["dns-server", "vlan-trunk", "nxos-desc", "iosxe-desc", "static-route",
         "arista-desc", "fg-config-header", "fg-edit-header", "arista-vrrp-desc",
         "iosxe-vrrp-desc", "aoss-plaintext-auth"],
)
def test_attack_string_is_linear_time(rx, attack):
    _m, elapsed = _timed_match(rx, attack)
    assert elapsed < _BUDGET_S, (
        f"regex took {elapsed:.3f}s on a {len(attack)}-char attack line "
        f"-- possible ReDoS regression (budget {_BUDGET_S}s)"
    )
