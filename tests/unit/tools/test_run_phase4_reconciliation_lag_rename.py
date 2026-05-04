"""Wave 9 β — pin the LAG-name canonicalisation in the Phase 4
reconciler so vendor-correct LAG renames (``ae<N>`` ↔ ``Port-channel<N>``
↔ ``trk<N>``) don't fire spurious CODEC_BUG against fields whose YAML
expects ``good``.

Today the comparator treats the raw string token as load-bearing, so
Junos's ``ae1`` and Cisco's ``Port-channel1`` look like a drift even
when the underlying lag-bundle (members + mode) round-trips perfectly.
The fix introduces ``_canonical_lag_name`` and applies it inside
``actual_disposition`` for the two field-keys that carry LAG name
references:

* ``lags[].name`` — the LAG record itself
* ``interfaces[].lag_member_of`` — interfaces' parent-LAG cross-reference

Names that don't match a known LAG shape pass through unchanged, so
``Loopback0`` / ``Vlan100`` / ``xe-0/0/0`` / ``GigabitEthernet1/0/1``
keep their identity and don't accidentally collapse to a LAG token.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


_RUNNER_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "run_phase4_reconciliation.py"
)
_spec = importlib.util.spec_from_file_location(
    "run_phase4_reconciliation_lag", _RUNNER_PATH,
)
assert _spec is not None and _spec.loader is not None
recon = importlib.util.module_from_spec(_spec)
sys.modules["run_phase4_reconciliation_lag"] = recon
_spec.loader.exec_module(recon)


# ---------------------------------------------------------------------------
# _canonical_lag_name — name-shape recognition
# ---------------------------------------------------------------------------


def test_canonical_lag_name_recognises_juniper_form() -> None:
    """Junos ``ae<N>`` (and historic ``ae<N>.<unit>``-style references)
    canonicalise to a stable token."""
    assert recon._canonical_lag_name("ae0") == recon._canonical_lag_name(
        "Port-channel0"
    )
    assert recon._canonical_lag_name("ae10") == recon._canonical_lag_name(
        "Port-Channel10"
    )


def test_canonical_lag_name_recognises_cisco_arista_alias() -> None:
    """``Po<N>`` is the Cisco short-form alias for ``Port-channel<N>``."""
    assert recon._canonical_lag_name("Po1") == recon._canonical_lag_name(
        "Port-channel1"
    )


def test_canonical_lag_name_recognises_aruba_trk_form() -> None:
    """Aruba's ``trk<N>`` / ``Trk<N>`` (case difference is real — some
    AOS-S images emit one, some the other)."""
    assert recon._canonical_lag_name("trk1") == recon._canonical_lag_name(
        "Trk1"
    )
    assert recon._canonical_lag_name("trk1") == recon._canonical_lag_name(
        "Port-channel1"
    )


def test_canonical_lag_name_recognises_fortigate_agg_form() -> None:
    """FortiGate's aggregate-interface ``agg<N>`` is the vendor-native
    LAG name (per FortiOS CLI Reference ``config system interface``
    with ``type aggregate``).  Wave 10 γ-3 extended the regex so
    cross-vendor renames against ae<N> / Port-channel<N> don't fire
    spurious CODEC_BUG against ``interfaces[].lag_member_of``."""
    assert recon._canonical_lag_name("agg1") == recon._canonical_lag_name(
        "ae1"
    )
    assert recon._canonical_lag_name("agg2") == recon._canonical_lag_name(
        "Port-channel2"
    )


def test_canonical_lag_name_recognises_routeros_bond_form() -> None:
    """RouterOS bonding-interface ``bond<N>`` is the vendor-native LAG
    name (per RouterOS bonding-interface documentation).  Wave 10 γ-3
    extended the regex to recognise it as semantically equivalent to
    ae<N> / Port-channel<N>."""
    assert recon._canonical_lag_name("bond1") == recon._canonical_lag_name(
        "ae1"
    )
    assert recon._canonical_lag_name("bond2") == recon._canonical_lag_name(
        "Port-channel2"
    )


def test_canonical_lag_name_returns_none_for_non_lag_names() -> None:
    """Names that don't match a LAG shape return ``None`` so the caller
    falls back to raw equality.  Critical regression guard: we MUST NOT
    canonicalise loopback / VLAN / physical port names."""
    for name in (
        "Loopback0",
        "Loopback123",
        "Vlan100",
        "Vlan4094",
        "GigabitEthernet1/0/1",
        "TenGigabitEthernet0/1/2",
        "xe-0/0/0",
        "et-1/0/48",
        "ge-0/0/0.0",
        "Ethernet1",
        "Ethernet1/1",
        "1/25",
        "fortilink",
        "lacp trunk",
    ):
        assert recon._canonical_lag_name(name) is None, (
            f"non-LAG name {name!r} must not canonicalise"
        )


def test_canonical_lag_name_handles_none_and_empty() -> None:
    assert recon._canonical_lag_name(None) is None
    assert recon._canonical_lag_name("") is None


# ---------------------------------------------------------------------------
# actual_disposition — applies canonicalisation to lags[].name
# ---------------------------------------------------------------------------


def test_lags_name_rename_treated_as_preserved() -> None:
    """A Phase 1 record where the only drift on a LAG record is a
    documented rename (``Port-channel1`` → ``ae1``) must reconcile to
    ``preserved`` once canonicalisation is applied."""
    fd = {
        "lags": {
            "preserved": False,
            "source_count": 1,
            "target_count": 1,
            "drift": {
                "lags[0] {'name': 'Port-channel1'}": {
                    "name": {
                        "source": "Port-channel1",
                        "target": "ae1",
                    },
                },
            },
        },
    }
    actual, detail = recon.actual_disposition(fd, "lags[].name")
    assert actual == "preserved", (
        f"vendor-correct LAG rename should be preserved, got {actual}"
    )
    assert detail is None


def test_lags_name_real_drift_still_drifted() -> None:
    """If the LAG number itself changed (e.g. ``Port-channel1`` →
    ``ae5``), that's a real drift — the canonicalisation rule must not
    mask it."""
    fd = {
        "lags": {
            "preserved": False,
            "drift": {
                "lags[0] {'name': 'Port-channel1'}": {
                    "name": {
                        "source": "Port-channel1",
                        "target": "ae5",  # different number!
                    },
                },
            },
        },
    }
    actual, _ = recon.actual_disposition(fd, "lags[].name")
    assert actual == "drifted"


def test_lag_member_of_rename_treated_as_preserved() -> None:
    """``interfaces[].lag_member_of`` carries a LAG-name reference —
    the same canonicalisation must apply, otherwise the per-record
    drift dict spuriously fires CODEC_BUG.
    """
    fd = {
        "interfaces": {
            "preserved": False,
            "source_count": 4,
            "target_count": 4,
            "drift": {
                "interfaces[2] {'name': 'et-0/0/48'}": {
                    "lag_member_of": {
                        "source": "ae1",
                        "target": "Port-channel1",
                    },
                },
                "interfaces[3] {'name': 'et-0/0/49'}": {
                    "lag_member_of": {
                        "source": "ae1",
                        "target": "Port-channel1",
                    },
                },
            },
        },
    }
    actual, _ = recon.actual_disposition(
        fd, "interfaces[].lag_member_of",
    )
    assert actual == "preserved"


def test_lag_member_of_dropped_still_drifted() -> None:
    """If ``lag_member_of`` is dropped entirely (target = None / ""),
    that's a parser bug — canonicalisation must NOT flatten it to
    preserved.  None doesn't match any LAG shape, so the comparison
    falls back to raw equality and surfaces the drop."""
    fd = {
        "interfaces": {
            "preserved": False,
            "drift": {
                "interfaces[2] {'name': 'et-0/0/48'}": {
                    "lag_member_of": {
                        "source": "ae1",
                        "target": None,
                    },
                },
            },
        },
    }
    actual, _ = recon.actual_disposition(
        fd, "interfaces[].lag_member_of",
    )
    assert actual == "drifted"


def test_lag_member_of_mixed_some_renamed_some_dropped() -> None:
    """Real-world scenario: out of three records, two are renamed
    cleanly (preserved) and one is genuinely dropped.  The aggregate
    must still surface as drifted because ONE record really lost its
    LAG association."""
    fd = {
        "interfaces": {
            "preserved": False,
            "drift": {
                "interfaces[2] {'name': 'et-0/0/48'}": {
                    "lag_member_of": {
                        "source": "ae1",
                        "target": "Port-channel1",
                    },
                },
                "interfaces[3] {'name': 'et-0/0/49'}": {
                    "lag_member_of": {
                        "source": "ae1",
                        "target": "Port-channel1",
                    },
                },
                "interfaces[4] {'name': 'et-1/0/48'}": {
                    "lag_member_of": {
                        "source": "ae1",
                        "target": None,  # genuinely dropped
                    },
                },
            },
        },
    }
    actual, _ = recon.actual_disposition(
        fd, "interfaces[].lag_member_of",
    )
    assert actual == "drifted"


def test_loopback_name_drift_not_swallowed_by_lag_canonicaliser() -> None:
    """Critical regression guard: if a loopback / SVI / physical-port
    sub-field drifts, the LAG canonicaliser must NOT mask it."""
    fd = {
        "interfaces": {
            "preserved": False,
            "drift": {
                "interfaces[15] {'name': 'Loopback0'}": {
                    "name": {
                        "source": "Loopback0",
                        "target": "lo0",  # NOT a LAG rename
                    },
                },
            },
        },
    }
    actual, _ = recon.actual_disposition(fd, "interfaces[].name")
    assert actual == "drifted"


def test_reconcile_cell_lag_rename_yields_aligned_when_yaml_says_good() -> None:
    """End-to-end: a cell where the only drift is a vendor-correct LAG
    rename and the YAML expects ``good`` reconciles to ALIGNED, not
    CODEC_BUG."""
    cell = {
        "fixture": "tests/fixtures/synthetic/juniper_junos/kitchen_sink.set",
        "fixture_kind": "synthetic",
        "source_codec": "juniper_junos",
        "target_codec": "cisco_iosxe_cli",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "lags": {
                "preserved": False,
                "source_count": 2,
                "target_count": 2,
                "drift": {
                    "lags[0] {'name': 'ae0'}": {
                        "name": {
                            "source": "ae0",
                            "target": "Port-channel0",
                        },
                    },
                    "lags[1] {'name': 'ae1'}": {
                        "name": {
                            "source": "ae1",
                            "target": "Port-channel1",
                        },
                    },
                },
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "lags[].name": {"disposition": "good"},
        },
    }
    result = recon.reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    assert fv["lags[].name"]["variance"] == recon.VAR_ALIGNED
    assert result["summary"][recon.VAR_CODEC_BUG] == 0
    assert result["summary"][recon.VAR_ALIGNED] == 1
