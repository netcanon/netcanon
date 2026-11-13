"""An AOS-S port range is the ports it names, however many.

Nothing in the parser knows which ports the switch has, so ``tagged
1-1001`` is 1,001 ports to everything downstream.  Up to 0.7.7 a range
of more than 1,025 ports was read as its two end ports instead:
``tagged 1-1026`` was ports 1 and 1026, a VLAN on two ports the line
does not name, in a job that said nothing of it.  A range is now read
whole, and what it makes is held to the limits in force: past
``memberships`` it is refused before one port of it is made, past
``ports`` once its different ports are counted.

Each check here is handed the parser as it was, and fails.
"""

from __future__ import annotations

import re
import time

import pytest

from netcanon.migration import limits as L
from netcanon.migration.codecs import get_codec
from netcanon.migration.codecs.aruba_aoss import parse as aoss_parse

pytestmark = pytest.mark.unit

_HEAD = 'hostname "sw"\n'


def _vlan(ports: str) -> str:
    return _HEAD + f'vlan 10\n   name "TEN"\n   tagged {ports}\n   exit\n'


def _parse(text: str, limits: str | None = None):
    with L.limits_scope(limits):
        return get_codec("aruba_aoss").parse(text)


def _tagged(text: str, limits: str | None = None) -> list[str]:
    return next(v.tagged_ports for v in _parse(text, limits).vlans if v.id == 10)


def _members(text: str) -> list[str]:
    return [member for lag in _parse(text).lags for member in lag.members]


def _refused(text: str, limits: str | None = None) -> L.LimitExceeded:
    with L.limits_scope(limits), pytest.raises(L.LimitExceeded) as caught:
        get_codec("aruba_aoss").parse(text)
    return caught.value


class TestARangeIsItsPorts:
    @pytest.mark.parametrize("hi", [1025, 1026, 2000])
    def test_a_vlan_list(self, hi: int) -> None:
        tagged = _tagged(_vlan(f"1-{hi}"))
        assert len(tagged) == hi
        assert set(tagged) == {str(n) for n in range(1, hi + 1)}

    def test_a_lettered_range(self) -> None:
        tagged = _tagged(_vlan("A1-A1100"))
        assert set(tagged) == {f"A{n}" for n in range(1, 1101)}

    def test_a_stack_members_range(self) -> None:
        tagged = _tagged(_vlan("2/1-2/1500"))
        assert set(tagged) == {f"2/{n}" for n in range(1, 1501)}

    def test_beside_other_names(self) -> None:
        tagged = _tagged(_vlan("1-1100,A1"))
        assert set(tagged) == {str(n) for n in range(1, 1101)} | {"A1"}

    def test_a_trunk_line(self) -> None:
        members = _members(_HEAD + "trunk 1-1100 trk1 lacp\n")
        assert len(members) == 1100
        assert set(members) == {str(n) for n in range(1, 1101)}


class TestWhatARangeMakesIsCounted:
    def test_past_memberships_it_is_refused_before_it_is_made(self) -> None:
        # A billion ports in a dozen bytes: refused at once, not made.
        start = time.perf_counter()
        refusal = _refused(_vlan("1-999999999"))
        assert time.perf_counter() - start < 2.0
        assert refusal.kind == "memberships"

    def test_past_ports_it_is_refused(self) -> None:
        # Under ``small`` 3,000 memberships are allowed and 3,000
        # different ports are not.
        refusal = _refused(_vlan("1-3000"), "small")
        assert refusal.kind == "ports"

    def test_within_the_limits_it_is_read(self) -> None:
        assert len(_tagged(_vlan("1-2000"), "small")) == 2000


def _as_it_was(original):
    """The expander up to 0.7.7: a range of more than 1,025 ports is
    its two end ports."""

    def expand(lo: str, hi: str) -> list[str]:
        m_lo, m_hi = re.match(r"^(.*?)(\d+)$", lo), re.match(r"^(.*?)(\d+)$", hi)
        if m_lo and m_hi and int(m_hi.group(2)) - int(m_lo.group(2)) > 1024:
            return [lo, hi]
        return original(lo, hi)

    return expand


class TestTheChecksCanFail:
    def test_the_two_end_ports_fail_the_reading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(aoss_parse, "_expand_port_range", _as_it_was(aoss_parse._expand_port_range))
        reading = TestARangeIsItsPorts()
        for check in (
            lambda: reading.test_a_vlan_list(1026),
            reading.test_a_lettered_range,
            reading.test_a_stack_members_range,
            reading.test_beside_other_names,
            reading.test_a_trunk_line,
        ):
            with pytest.raises(AssertionError):
                check()
        # A range of 1,025 ports was read whole before as well.
        reading.test_a_vlan_list(1025)

    def test_the_two_end_ports_fail_the_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(aoss_parse, "_expand_port_range", _as_it_was(aoss_parse._expand_port_range))
        counted = TestWhatARangeMakesIsCounted()
        for check in (
            counted.test_past_memberships_it_is_refused_before_it_is_made,
            counted.test_past_ports_it_is_refused,
        ):
            with pytest.raises(pytest.fail.Exception):
                check()
        with pytest.raises(AssertionError):
            counted.test_within_the_limits_it_is_read()
