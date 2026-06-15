"""Regression: case-mismatched LAG names must not round-trip into duplicate
CanonicalLAG records, and the Cisco-family LAG sort keys must be a total
order.

Root cause (2026-06-14 review): arista_eos renders a LAG as both a
``channel-group 3 mode active`` member binding AND a self-consistency stub
``interface Port-Channel3`` (capital C).  The Cisco-family parsers recorded
the stub verbatim while synthesising a different-cased name from the
channel-group line, so one source LAG became two target LAGs (``count drift
5 -> 10``).  The parse-time casing canonicalisation collapses them to one;
the total-order sort key makes the cross-mesh artifact deterministic even
if a tie ever re-forms.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
)
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    _lag_sort_key as _iosxe_key,
)
from netcanon.migration.codecs.cisco_iosxr.parse import _lag_sort_key as _iosxr_key
from netcanon.migration.codecs.cisco_nxos.parse import _lag_sort_key as _nxos_key
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


def _lag_intent() -> CanonicalIntent:
    return CanonicalIntent(
        hostname="r1",
        interfaces=[
            CanonicalInterface(name="Ethernet3", lag_member_of="Port-Channel3"),
            CanonicalInterface(name="Ethernet4", lag_member_of="Port-Channel3"),
        ],
        lags=[
            CanonicalLAG(
                name="Port-Channel3",
                members=["Ethernet3", "Ethernet4"],
                mode="active",
            )
        ],
    )


@pytest.mark.parametrize("target", ["cisco_nxos", "cisco_iosxe_cli"])
def test_arista_lag_not_duplicated_on_reparse(target: str) -> None:
    """arista_eos render (capital-C ``Port-Channel3`` stub) re-parsed by the
    Cisco family collapses to ONE LAG, not two case-differing twins."""
    arista_text = get_codec("arista_eos").render(_lag_intent())
    reparsed = get_codec(target).parse(arista_text)
    pc = [lag for lag in reparsed.lags if lag.name.lower() == "port-channel3"]
    assert len(pc) == 1, (
        f"{target}: expected 1 LAG, got {[lag.name for lag in reparsed.lags]}"
    )
    assert "Ethernet3" in pc[0].members and "Ethernet4" in pc[0].members


@pytest.mark.parametrize("target", ["cisco_nxos", "cisco_iosxe_cli"])
def test_case_variant_stub_merges_in_parse(target: str) -> None:
    """A capital-C ``interface Port-Channel3`` stub plus a ``channel-group 3``
    member binding collapse to one LAG."""
    text = (
        "interface Port-Channel3\n"
        "!\n"
        "interface Ethernet3\n"
        "   channel-group 3 mode active\n"
        "!\n"
    )
    lags = get_codec(target).parse(text).lags
    pc = [lag for lag in lags if lag.name.lower() == "port-channel3"]
    assert len(pc) == 1, f"{target}: expected 1 LAG, got {[lag.name for lag in lags]}"
    assert pc[0].members == ["Ethernet3"]


@pytest.mark.parametrize(
    "key_fn,names",
    [
        (_nxos_key, ["Port-Channel3", "port-channel3", "Port-channel5"]),
        (_iosxe_key, ["Port-Channel3", "port-channel3", "Port-channel5"]),
        (_iosxr_key, ["Bundle-Ether1", "bundle-ether1", "Bundle-Ether2"]),
    ],
)
def test_lag_sort_key_is_total_order(key_fn, names) -> None:
    """Distinct names yield distinct keys (the verbatim-name tiebreaker), so
    ``sorted()`` over a hash-randomised set union is deterministic."""
    keys = [key_fn(n) for n in names]
    assert len(set(keys)) == len(names), f"tied sort keys: {keys}"
    # And the key is comparable (no TypeError on mixed branches).
    assert sorted(names, key=key_fn) == sorted(names, key=key_fn)
