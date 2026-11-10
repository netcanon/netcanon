"""A Junos pool of several ranges is read as its largest run, and said.

A Junos address-assignment pool can state several ranges (``range <R>
low|high``), and Juniper's subscriber-management pages say every range
of a pool is searched for an address to hand out.  The tree holds one
run of a pool.  The parser read the first ``low`` and the first ``high``
the pool stated, whichever range each was in, and said nothing of the
rest; it read ``low <ip> high <ip>`` on one line (as Juniper's own
example types the legacy ``address-range``) as its ``low`` alone; and it left
out a pool that states one ``high`` and no network, and one that states
neither a network nor a range, with nothing said.

It now keeps each range by its name, keeps the largest run their
addresses make (the lower of two as large, as the RouterOS parser does),
and says the rest in a row of the sections not translated
(:mod:`netcanon.migration.codecs.juniper_junos.dhcp_pools`).  Every
config here is typed by hand.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.juniper_junos.dhcp_pools import one_range, pool_rows
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

JUNOS = get_codec("juniper_junos")
_POOL = "set access address-assignment pool {name} family inet"

_SEVERAL = (
    "access address-assignment pool {names}: family inet range -- more than one "
    "range; the tree holds one run of a pool, so the largest is kept and the "
    "others are not translated"
)
_NONE = (
    "access address-assignment pool {names}: family inet with no network and no "
    "range -- no address of it the tree can hold; not translated"
)


def _config(*lines: str, name: str = "P") -> str:
    return "\n".join(["set system host-name r1", *(line.format(pool=_POOL.format(name=name)) for line in lines), ""])


def _pools(text: str) -> list[tuple[str, str, str]]:
    return [(p.network, p.start_ip, p.end_ip) for p in JUNOS.parse(text).dhcp_servers]


def _rows(text: str) -> list[str]:
    return [row for row in JUNOS.parse(text).dropped_tier3_sections if "address-assignment" in row]


_NETWORK = "{pool} network 192.0.2.0/24"


class TestOneRange:
    def test_as_it_stands(self) -> None:
        text = _config(_NETWORK, "{pool} range r1 low 192.0.2.10", "{pool} range r1 high 192.0.2.50")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.50")]
        assert _rows(text) == []

    def test_both_ends_on_one_line(self) -> None:
        text = _config(_NETWORK, "{pool} range r1 low 192.0.2.10 high 192.0.2.50")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.50")]

    def test_an_end_set_again_replaces_the_one_before(self) -> None:
        text = _config(
            _NETWORK, "{pool} range r1 low 192.0.2.10", "{pool} range r1 high 192.0.2.50",
            "{pool} range r1 low 192.0.2.20",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.20", "192.0.2.50")]

    def test_the_legacy_range_on_one_line(self) -> None:
        text = _config("set system services dhcp pool 192.0.2.0/24 address-range low 192.0.2.10 high 192.0.2.50")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.50")]
        assert _rows(text) == []

    def test_the_legacy_range_on_two_lines(self) -> None:
        text = _config(
            "set system services dhcp pool 192.0.2.0/24 address-range low 192.0.2.10",
            "set system services dhcp pool 192.0.2.0/24 address-range high 192.0.2.50",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.50")]

    def test_a_range_line_that_sets_no_end_is_no_range(self) -> None:
        text = _config(
            _NETWORK, "{pool} range a low 192.0.2.10", "{pool} range a high 192.0.2.20", "{pool} range b other 1",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "192.0.2.20")]
        assert _rows(text) == []

    def test_an_end_the_range_does_not_state_stays_unstated(self) -> None:
        text = _config(_NETWORK, "{pool} range r1 low 192.0.2.10")
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.10", "")]


class TestSeveralRanges:
    @pytest.mark.parametrize(
        ("ranges", "kept", "said"),
        [
            pytest.param(
                [("a", "192.0.2.10", "192.0.2.20"), ("b", "192.0.2.100", "192.0.2.200")],
                ("192.0.2.100", "192.0.2.200"), True, id="apart: the larger",
            ),
            pytest.param(
                [("a", "192.0.2.100", "192.0.2.110"), ("b", "192.0.2.10", "192.0.2.20")],
                ("192.0.2.10", "192.0.2.20"), True, id="apart and as large: the lower",
            ),
            pytest.param(
                [("a", "192.0.2.10", "192.0.2.20"), ("b", "192.0.2.21", "192.0.2.30")],
                ("192.0.2.10", "192.0.2.30"), False, id="end to end: one run",
            ),
            pytest.param(
                [("a", "192.0.2.10", "192.0.2.40"), ("b", "192.0.2.30", "192.0.2.60")],
                ("192.0.2.10", "192.0.2.60"), False, id="overlapping: one run",
            ),
            pytest.param(
                [("a", "192.0.2.10", "192.0.2.20"), ("b", "192.0.2.90", "192.0.2.80")],
                ("192.0.2.10", "192.0.2.20"), True, id="one that cannot be read",
            ),
            pytest.param(
                [("a", "192.0.2.10", "192.0.2.20"), ("b", "192.0.2.200", "")],
                ("192.0.2.200", ""), True, id="one end: it stays unstated",
            ),
            pytest.param(
                [("a", "", "192.0.2.100"), ("b", "192.0.2.50", "")],
                ("", ""), False, id="together every host: no range",
            ),
            pytest.param(
                [("a", "192.0.2.10", "192.0.2.20"), ("b", "192.0.2.15", "192.0.2.20")],
                ("192.0.2.10", "192.0.2.20"), False, id="one inside the other",
            ),
        ],
    )
    def test_the_largest_run_is_kept(
        self, ranges: list[tuple[str, str, str]], kept: tuple[str, str], said: bool,
    ) -> None:
        lines = [_NETWORK]
        for name, low, high in ranges:
            if low:
                lines.append(f"{{pool}} range {name} low {low}")
            if high:
                lines.append(f"{{pool}} range {name} high {high}")
        text = _config(*lines)
        assert _pools(text) == [("192.0.2.0/24", *kept)]
        assert _rows(text) == ([_SEVERAL.format(names="P")] if said else [])

    def test_with_no_network_the_ends_as_they_are(self) -> None:
        # One end of a range and no network hands out nothing the tree
        # can count: the other range is the one kept.
        text = _config(
            "{pool} range a low 192.0.2.10", "{pool} range a high 192.0.2.20", "{pool} range b low 192.0.2.100",
        )
        assert _pools(text) == [("", "192.0.2.10", "192.0.2.20")]
        assert _rows(text) == [_SEVERAL.format(names="P")]

    def test_none_that_can_be_read(self) -> None:
        # Nothing to keep a run of: the first range as it stands, and
        # the row, so that a renderer says what it cannot write.
        text = _config("{pool} range a low 192.0.2.10", "{pool} range b high 192.0.2.20")
        assert _pools(text) == [("", "192.0.2.10", "")]
        assert _rows(text) == [_SEVERAL.format(names="P")]

    def test_a_range_of_a_group_and_one_of_the_config(self) -> None:
        # Junos composes an applied group's ranges with the config's.
        group = "set groups G access address-assignment pool P family inet"
        text = _config(
            _NETWORK, "{pool} range a low 192.0.2.10", "{pool} range a high 192.0.2.20",
            f"{group} range b low 192.0.2.100", f"{group} range b high 192.0.2.200", "set apply-groups G",
        )
        assert _pools(text) == [("192.0.2.0/24", "192.0.2.100", "192.0.2.200")]
        assert _rows(text) == [_SEVERAL.format(names="P")]


class TestNoAddress:
    def test_a_pool_with_options_alone_is_said(self) -> None:
        text = _config("{pool} dhcp-attributes router 192.0.2.1")
        assert _pools(text) == []
        assert _rows(text) == [_NONE.format(names="P")]

    def test_a_high_and_no_network_is_read(self) -> None:
        # Left out before; the renderers treat it as such a pool from
        # any source (a review line where it cannot be written).
        text = _config("{pool} range r1 high 192.0.2.50")
        assert _pools(text) == [("", "", "192.0.2.50")]
        assert _rows(text) == []


class TestTheRows:
    def test_a_few_named_and_the_rest_counted(self) -> None:
        names = [f"P{n}" for n in range(5)]
        assert pool_rows(names, names) == [
            _SEVERAL.format(names="P0, P1, P2 and 2 more"),
            _NONE.format(names="P0, P1, P2 and 2 more"),
        ]

    def test_a_name_is_shown_on_one_line_and_cut(self) -> None:
        row = pool_rows(["a  b\tc" + "x" * 60], [])[0]
        assert row.startswith("access address-assignment pool a b c" + "x" * 34 + "…: ")

    def test_no_address_is_shown(self) -> None:
        text = _config(
            _NETWORK, "{pool} range a low 192.0.2.10", "{pool} range a high 192.0.2.20",
            "{pool} range b low 192.0.2.100", "{pool} range b high 192.0.2.200",
        )
        assert not any("192.0.2" in row for row in _rows(text))

    def test_one_range_of_none(self) -> None:
        assert one_range({}, "192.0.2.0/24") == ("", "", False)


_SOURCE = _config(
    "set interfaces ge-0/0/1 unit 0 family inet address 192.0.2.1/24",
    _NETWORK,
    "{pool} range a low 192.0.2.10", "{pool} range a high 192.0.2.20",
    "{pool} range b low 192.0.2.100", "{pool} range b high 192.0.2.200",
    "{pool} dhcp-attributes router 192.0.2.1",
    "set system services dhcp-local-server group P interface ge-0/0/1.0",
)


@pytest.mark.parametrize("target", sorted(list_public_codecs()))
def test_every_job_says_the_ranges_left_out(target: str) -> None:
    job = run_plan_with_checked_names(JUNOS, get_codec(target), _SOURCE)
    assert _SEVERAL.format(names="P") in job.dropped_tier3_sections


def test_the_run_kept_reads_back_from_junos() -> None:
    job = run_plan_with_checked_names(JUNOS, JUNOS, _SOURCE)
    assert _pools(job.rendered) == [("192.0.2.0/24", "192.0.2.100", "192.0.2.200")]
    assert _rows(job.rendered) == []
