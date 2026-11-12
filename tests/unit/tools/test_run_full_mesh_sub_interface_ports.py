"""Pin that the cross-mesh audit records the source's interfaces with
sub-interfaces, and that the reconciler reads the target's matrix for an
address dropped from one.

AOS-CX gives a port or an L3 LAG that has sub-interfaces no address of its
own (HPE), so its renderer writes the address in a ``review:`` line instead,
and its matrix declares
``/interfaces/interface/address-beside-sub-interfaces`` unsupported.  The
per-pair expectation YAMLs say ``good`` for ``interfaces[].ipv4_addresses``
and cannot say "good except there", so the mesh records which interfaces of
the source those are (``sub_interface_ports``, by the rule the walker and the
renderer read) and the reconciler holds the drop to the matrix.  The cell is
made by ``process_cell`` itself here, so the record and its reader are held
together, not each to a hand-built cell.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


run_full_mesh = _load("run_full_mesh_carriers", "tools/run_full_mesh.py")
recon = _load("run_phase4_reconciliation_carriers", "tools/run_phase4_reconciliation.py")

# Any committed fixture: the source below reads none of it.
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "synthetic" / "aruba_aoscx" / "kitchen_sink.cfg"

_EXPECT_GOOD = {
    "per_field_expectation": {
        "interfaces[].ipv4_addresses": {"disposition": "good"},
    },
}


def _tree(with_unit: bool) -> CanonicalIntent:
    interfaces = [
        CanonicalInterface(
            name="1/1/1",
            ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24)],
        ),
    ]
    if with_unit:
        interfaces.append(
            CanonicalInterface(
                name="1/1/1.10",
                dot1q_vlan=10,
                ipv4_addresses=[CanonicalIPv4Address(ip="10.0.10.1", prefix_length=24)],
            ),
        )
    return CanonicalIntent(interfaces=interfaces)


class _Built(type(get_codec("aruba_aoscx"))):
    """AOS-CX that hands over a tree built here, whatever the text."""

    with_unit = True

    def parse(self, raw: str) -> CanonicalIntent:
        return _tree(self.with_unit)


def _cell(target: str, *, with_unit: bool = True) -> dict:
    source = _Built()
    source.with_unit = with_unit
    return run_full_mesh.process_cell(
        fixture_path=_FIXTURE,
        source_codec=source,
        source_codec_name="aruba_aoscx",
        target_codec=get_codec(target),
        target_codec_name=target,
        fixture_kind="synthetic",
    )


def test_the_fixture_is_there() -> None:
    assert _FIXTURE.exists(), f"fixture moved: {_FIXTURE}"


def test_the_cell_lists_the_port_with_a_sub_interface() -> None:
    cell = _cell("aruba_aoscx")
    assert cell["render_status"] == "ok", cell.get("error")
    assert cell["sub_interface_ports"] == ["1/1/1"]


def test_a_cell_with_no_sub_interface_lists_none() -> None:
    cell = _cell("aruba_aoscx", with_unit=False)
    assert cell["render_status"] == "ok", cell.get("error")
    assert "sub_interface_ports" not in cell


def test_onto_aoscx_the_dropped_address_is_expected() -> None:
    """The port's address is gone from the AOS-CX output (it is in a review
    line), the sub-interface's is not, and the drop is what the matrix
    declares."""
    cell = _cell("aruba_aoscx")
    assert cell["roundtrip_parse_status"] == "ok", cell.get("error")
    result = recon.reconcile_cell(cell, _EXPECT_GOOD)
    fv = result["field_variances"]["interfaces[].ipv4_addresses"]
    assert fv["actual"] == "drifted"
    assert fv["variance"] == recon.VAR_EXPECTED_UNSUPPORTED
    assert fv["drift_detail"]["reclassified_from"] == recon.VAR_CODEC_BUG
    (key,) = fv["drift_detail"]["per_record"]
    assert "'1/1/1'" in key


def test_without_the_list_the_same_cell_is_a_codec_bug() -> None:
    """The record is what decides: with it taken out, the drop is a bug."""
    cell = _cell("aruba_aoscx")
    del cell["sub_interface_ports"]
    result = recon.reconcile_cell(cell, _EXPECT_GOOD)
    fv = result["field_variances"]["interfaces[].ipv4_addresses"]
    assert fv["variance"] == recon.VAR_CODEC_BUG


def test_with_no_sub_interface_the_address_is_kept() -> None:
    result = recon.reconcile_cell(_cell("aruba_aoscx", with_unit=False), _EXPECT_GOOD)
    fv = result["field_variances"]["interfaces[].ipv4_addresses"]
    assert fv["variance"] == recon.VAR_ALIGNED
