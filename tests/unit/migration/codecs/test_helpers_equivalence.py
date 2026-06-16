"""Golden-equivalence tests for the shared VLAN-list helpers.

v0.2.0 Stage 2, PR 1 is deliberately *additive*: it lifts the
byte-identical private copies of the VLAN id-list parse / coalesce
helpers into ``codecs/_helpers.py`` but DELETES no inline copy yet.

These tests freeze the equivalence between the new shared helper and each
surviving inline copy over a deliberate input sweep, so a later per-codec
PR can delete an inline copy as a *proven* behaviour-preserving swap (the
swap PR stays green by construction against this frozen golden).

The arista_eos ``_expand_vlan_list`` near-twin is intentionally NOT
converged here: it diverges on edge cases (it accepts ``int(chunk)``
forms like ``"+10"`` that the canonical ``str.isdigit()`` gate rejects).
The final test documents that divergence so a future contributor does not
"finish the job" and silently change arista's behaviour.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs._helpers import (
    _coalesce_vlan_ids,
    _parse_vlan_list,
)
from netcanon.migration.codecs.arista_eos.parse import (
    _expand_vlan_list as _arista_expand,
)
from netcanon.migration.codecs.aruba_aoscx.parse import (
    _parse_vlan_list as _aoscx_parse,
)
from netcanon.migration.codecs.aruba_aoscx.render import (
    _coalesce_vlan_ids as _aoscx_coalesce,
)
from netcanon.migration.codecs.cisco_iosxe_cli.parse import (
    _parse_vlan_list as _iosxe_parse,
)
from netcanon.migration.codecs.cisco_nxos.parse import (
    _parse_vlan_list as _nxos_parse,
)
from netcanon.migration.codecs.cisco_nxos.render import (
    _coalesce_vlan_ids as _nxos_coalesce,
)

# Inline copies that the shared _parse_vlan_list must reproduce exactly.
_PARSE_INLINE_COPIES = (_nxos_parse, _iosxe_parse, _aoscx_parse)
# Inline copies that the shared _coalesce_vlan_ids must reproduce exactly.
_COALESCE_INLINE_COPIES = (_nxos_coalesce, _aoscx_coalesce)

_PARSE_SWEEP = [
    "1",
    "0",
    "4094",
    "4095",
    "10,20,30",
    "10-20",
    "1,10,2000",
    "100-102",
    "10-20,30,40-42",
    " 10 , 20 ",
    "",
    "10,,20",
    "abc",
    "1,abc,3",
    "5-3",            # inverted range -> empty
    "1-9999999999",   # OOM-guard: clamp to 1..4094, no MemoryError
    "0-5",            # low clamp -> 1..5
    "4090-4100",      # high clamp -> 4090..4094
]

_COALESCE_SWEEP = [
    [],
    [1],
    [1, 2],
    [1, 2, 3],
    [1, 10, 11, 12, 20],
    [5],
    [100, 101],
    [4094],
    [1, 2, 3, 5, 6, 7, 10],
]


@pytest.mark.unit
@pytest.mark.parametrize("text", _PARSE_SWEEP)
def test_parse_vlan_list_matches_every_inline_copy(text: str) -> None:
    expected = _parse_vlan_list(text)
    for inline in _PARSE_INLINE_COPIES:
        assert inline(text) == expected, (
            f"{inline.__module__}._parse_vlan_list drifted from the shared "
            f"helper on {text!r}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("ids", _COALESCE_SWEEP)
def test_coalesce_vlan_ids_matches_every_inline_copy(ids: list[int]) -> None:
    expected = _coalesce_vlan_ids(ids)
    for inline in _COALESCE_INLINE_COPIES:
        assert inline(ids) == expected, (
            f"{inline.__module__}._coalesce_vlan_ids drifted from the shared "
            f"helper on {ids!r}"
        )


@pytest.mark.unit
def test_parse_coalesce_round_trip() -> None:
    """coalesce(parse(x)) re-parses to the same id set (inverse pair)."""
    for text in ("1,10-12,20", "100-102", "4090-4094"):
        ids = _parse_vlan_list(text)
        assert _parse_vlan_list(_coalesce_vlan_ids(ids)) == ids


@pytest.mark.unit
def test_arista_expand_divergence_is_documented() -> None:
    """arista_eos._expand_vlan_list is a near-twin that is NOT converged.

    It accepts ``int(chunk)`` forms the canonical ``str.isdigit()`` gate
    rejects, so it must keep its own copy until that divergence is
    deliberately reconciled.  This asserts the known difference so the
    exclusion is intentional, not an oversight.
    """
    assert _parse_vlan_list("+10") == []
    assert _arista_expand("+10") == [10]
