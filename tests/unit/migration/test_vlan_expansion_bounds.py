"""Regression: VLAN-list expanders must bound materialization to the valid
VLAN space (1..4094) BEFORE building the range, so an adversarial or
fat-fingered span (e.g. ``1-9999999999``) reachable via a trusted operator's
own config paste cannot OOM the single-worker process.

The clamp is lossless for valid configs: the kept set is exactly the
1..4094 intersection the downstream filter already produced — the fix only
moves the bound *ahead* of materialization.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs._helpers import merge_trunk_allowed
from netcanon.migration.codecs.arista_eos.parse import _expand_vlan_list as eos
from netcanon.migration.codecs.aruba_aoscx.parse import _parse_vlan_list as aoscx
from netcanon.migration.codecs.cisco_nxos.parse import _parse_vlan_list as nxos

pytestmark = pytest.mark.unit


def iosxe(spec: str) -> list[int]:
    # cisco_iosxe_cli expands a trunk allowed-list via the shared
    # ``merge_trunk_allowed`` bare path (default ``parse_ids`` is
    # ``_parse_vlan_list``), which carries the OOM clamp.
    return merge_trunk_allowed([], spec)


# Each codec's comma/range VLAN-list expander (cisco family + arista).
_EXPANDERS = [
    pytest.param(iosxe, id="cisco_iosxe_cli"),
    pytest.param(nxos, id="cisco_nxos"),
    pytest.param(aoscx, id="aruba_aoscx"),
    pytest.param(eos, id="arista_eos"),
]


@pytest.mark.parametrize("fn", _EXPANDERS)
def test_huge_range_is_clamped_not_oom(fn) -> None:
    # The whole valid VLAN space, NOT range(1, 10_000_000_000).
    assert fn("1-9999999999") == list(range(1, 4095))


@pytest.mark.parametrize("fn", _EXPANDERS)
def test_valid_range_unchanged(fn) -> None:
    assert fn("10-20") == [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]


@pytest.mark.parametrize("fn", _EXPANDERS)
def test_partial_overflow_keeps_valid_subrange(fn) -> None:
    # Upper bound past 4094 is clamped; the valid head is preserved.
    assert fn("4090-5000") == [4090, 4091, 4092, 4093, 4094]


@pytest.mark.parametrize("fn", _EXPANDERS)
def test_reversed_range_is_empty(fn) -> None:
    assert fn("20-10") == []


@pytest.mark.parametrize("fn", _EXPANDERS)
def test_non_numeric_range_is_skipped(fn) -> None:
    # Must not raise (the cisco_iosxe_cli variant previously had no guard).
    assert fn("a-b") == []
