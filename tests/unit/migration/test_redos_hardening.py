"""ReDoS hardening guard for the five parse.py regexes CodeQL flagged
(``py/polynomial-redos`` alerts #124-#128).

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

from netcanon.migration.codecs.arista_eos.parse import _DHCP_DNS_SERVER_RE
from netcanon.migration.codecs.aruba_aoscx.parse import _VLAN_TRUNK_ALLOWED_RE
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    _STATIC_ROUTE_RE,
)
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    _VRF_DESCRIPTION_RE as _IOSXE_VRF_DESCRIPTION_RE,
)
from netcanon.migration.codecs.cisco_nxos.parse import (
    _VRF_DESCRIPTION_RE as _NXOS_VRF_DESCRIPTION_RE,
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
    for rx in (_NXOS_VRF_DESCRIPTION_RE, _IOSXE_VRF_DESCRIPTION_RE):
        assert rx.match("  description   Uplink to core  ").group(1).strip() == "Uplink to core"


def test_static_route_still_captures_and_keeps_trailing_tokens():
    m = _STATIC_ROUTE_RE.match("ip route vrf RED 10.0.0.0 255.0.0.0 192.0.2.1 200 name UP")
    assert m.group(1, 2, 3, 4) == ("RED", "10.0.0.0", "255.0.0.0", "192.0.2.1")
    assert (m.group(5) or "").split() == ["200", "name", "UP"]
    # No trailing tokens -> next-hop is the last token, trailing group is empty.
    bare = _STATIC_ROUTE_RE.match("ip route 0.0.0.0 0.0.0.0 192.0.2.1")
    assert bare.group(2, 3, 4) == ("0.0.0.0", "0.0.0.0", "192.0.2.1")
    assert (bare.group(5) or "").split() == []


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
    ],
    ids=["dns-server", "vlan-trunk", "nxos-desc", "iosxe-desc", "static-route"],
)
def test_attack_string_is_linear_time(rx, attack):
    _m, elapsed = _timed_match(rx, attack)
    assert elapsed < _BUDGET_S, (
        f"regex took {elapsed:.3f}s on a {len(attack)}-char attack line "
        f"-- possible ReDoS regression (budget {_BUDGET_S}s)"
    )
