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
forms like ``"+10"`` that the canonical ``str.isdecimal()`` gate rejects).
The final test documents that divergence so a future contributor does not
"finish the job" and silently change arista's behaviour.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs._helpers import (
    VLAN_IDS,
    _coalesce_vlan_ids,
    _parse_vlan_list,
    sole_vlan_id,
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
from netcanon.migration.codecs.cisco_nxos.parse import (
    _parse_vlan_list as _nxos_parse,
)
from netcanon.migration.codecs.cisco_nxos.render import (
    _coalesce_vlan_ids as _nxos_coalesce,
)
from netcanon.migration.limits import charge

# Inline copies that the shared _parse_vlan_list must reproduce exactly.
# (cisco_iosxe_cli no longer imports _parse_vlan_list directly -- its only
# caller, the trunk allowed-vlan line, now routes through the shared
# ``merge_trunk_allowed`` helper -- so it is no longer a surviving copy.)
_PARSE_INLINE_COPIES = (_nxos_parse, _aoscx_parse)
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
    "\u00b2",         # a digit that is not decimal: int() refuses it
    "1\u00b2,7",
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
@pytest.mark.parametrize("text", [*_PARSE_SWEEP, "7-7", "7-7,7", "3,", ",3", "0", "9-", "-9", "5-3,8", "4094-9000"])
def test_sole_vlan_id_is_the_list_of_one(text: str) -> None:
    """It answers "does this list name exactly one id, and which"
    without making the list.  The answer has to be the one the list
    gives, for every text: a caller swapped one for the other."""
    ids = _parse_vlan_list(text)
    assert sole_vlan_id(text) == (ids[0] if len(ids) == 1 else None), text


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

    It accepts ``int(chunk)`` forms the canonical ``str.isdecimal()`` gate
    rejects, so it must keep its own copy until that divergence is
    deliberately reconciled.  This asserts the known difference so the
    exclusion is intentional, not an oversight.
    """
    assert _parse_vlan_list("+10") == []
    assert _arista_expand("+10") == [10]


#: A config for each parser that reads its VLAN lists with the shared
#: helper, with ``{ids}`` where the list goes.
_READS_THE_LIST = {
    "aruba_aoss": (
        '; J9727A Configuration Editor; Created on release #WB.16.08.0001\nhostname "sw"\n'
        "vlan 1\n   untagged 1-6\n   exit\ninterface 3\n   tagged vlan {ids}\n   exit\n"
        "interface 4 tagged vlan {ids}\n"
    ),
    "cisco_nxos": (
        "hostname sw\nvlan 10\ninterface Ethernet1/1\n  switchport\n  switchport mode trunk\n"
        "  switchport trunk allowed vlan {ids}\n"
    ),
    "aruba_aoscx": (
        "hostname sw\nvlan 10\ninterface 1/1/1\n    no shutdown\n    no routing\n"
        "    vlan trunk native 1\n    vlan trunk allowed {ids}\n"
    ),
    "cisco_iosxe_cli": (
        "hostname sw\nvlan 10\ninterface GigabitEthernet1/0/1\n switchport mode trunk\n"
        " switchport trunk allowed vlan {ids}\n"
    ),
}


@pytest.mark.unit
@pytest.mark.parametrize("codec", list(_READS_THE_LIST))
@pytest.mark.parametrize(
    "ids", ["\u00b2", "1\u00b2", "10,\u00b2", "9" * 5000],
    ids=["superscript", "after-a-digit", "in-a-list", "5000-digits"],
)
def test_an_id_int_cannot_read_ends_no_job(codec: str, ids: str) -> None:
    """A token that reads as digits and that ``int`` refuses -- a
    superscript digit, a run longer than ``int`` converts -- is not a
    VLAN id.  It used to end the job with "unexpected error in stage
    parsing", for every parser that reads its lists with the helper."""
    from netcanon.migration.codecs.registry import get_codec
    from netcanon.services.migration_pipeline import run_plan_with_checked_names

    own = get_codec(codec)
    job = run_plan_with_checked_names(own, own, _READS_THE_LIST[codec].format(ids=ids), port_rename_map={})
    assert job.status != "failed", (job.status, job.error)


@pytest.mark.unit
def test_more_digits_than_int_converts_is_no_id() -> None:
    assert _parse_vlan_list("9" * 5000) == [] and sole_vlan_id("9" * 5000) is None
    assert _parse_vlan_list("10," + "9" * 5000) == [10] and sole_vlan_id("10," + "9" * 5000) == 10



def _the_isdigit_gate(text: str) -> list[int]:
    """The helper as it was: a token ``isdigit`` takes is handed to
    ``int``.  Its names are the helper module's, where it is run."""
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                lo_i, hi_i = int(lo.strip()), int(hi.strip())
            except ValueError:
                continue
            lo_i, hi_i = max(1, lo_i), min(4094, hi_i)
            if lo_i <= hi_i:
                charge("vlan_ids", hi_i - lo_i + 1, part)
                result.extend(VLAN_IDS[lo_i:hi_i + 1])
        elif part.isdigit():
            result.append(int(part))
    return result


@pytest.mark.unit
@pytest.mark.parametrize("codec", list(_READS_THE_LIST))
def test_the_job_check_fails_with_the_isdigit_gate(codec: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect put back in the one function every parser holds (a
    default argument among them): its code, not a name that points at
    it."""
    monkeypatch.setattr(_parse_vlan_list, "__code__", _the_isdigit_gate.__code__)
    with pytest.raises(AssertionError):
        test_an_id_int_cannot_read_ends_no_job(codec, "1" + chr(0xB2))
