"""An AOS-CX VTEP that is down is left out and said, with every VNI under it.

AOS-CX reads ``interface vxlan`` as down until it says ``no shutdown``,
as it reads a port, a LAG and ``interface mgmt`` (the parser's
``_default_enabled``: every such stanza of the committed inputs prints
its state, and HPE's ``aoscx-ansible-dcn-workflows`` templates write
``no shutdown`` under every ``interface vxlan``).  A VTEP that is down
carries none of its VNIs.  Up to 0.7.7 the parser read no state of the
VTEP: the VNIs of a shut VTEP were written onto every target that writes
an overlay, and onto AOS-CX under ``no shutdown``, in jobs that said
``completed``.

Read here: each form of the stanza, with what it means typed by hand;
the row, which is a left-out row; and every public codec's output read
as TEXT, by a reader of this module's own, for the VNI of a VTEP that
is down and of one that is up.
"""

from __future__ import annotations

import functools
import re

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_HEAD = (
    "hostname sw1\n"
    "vlan 11\n"
    "vlan 12\n"
    "interface vlan 11\n"
    "    ip address 192.0.2.1/24\n"
)

#: The row for ``interface vxlan 1`` left out.
_ROW = (
    "shutdown: interface vxlan 1 (a VXLAN interface the source holds shut, "
    "so it carries none of its VNIs; not translated)"
)


def _vtep(number: str, *lines: str) -> str:
    return f"interface vxlan {number}\n" + "".join(f"    {line}\n" for line in lines)


_UP = _vtep("1", "source ip 198.51.100.1", "no shutdown", "vni 10011", "    vlan 11")
_SHUT = _vtep("1", "source ip 198.51.100.1", "shutdown", "vni 10011", "    vlan 11")

#: Each form: the stanzas, the (VLAN, VNI) bindings read, and the rows.
FORMS = {
    "no shutdown": (_UP, [(11, 10011)], []),
    "shutdown": (_SHUT, [], [_ROW]),
    "no state line": (
        _vtep("1", "source ip 198.51.100.1", "vni 10011", "    vlan 11"), [], [_ROW],
    ),
    "the last state line, up": (
        _vtep("1", "shutdown", "no shutdown", "vni 10011", "    vlan 11"), [(11, 10011)], [],
    ),
    "the last state line, down": (
        _vtep("1", "no shutdown", "vni 10011", "    vlan 11", "shutdown"), [], [_ROW],
    ),
    # A line under a ``vni`` is not the VTEP's own.
    "no shutdown under a vni": (
        _vtep("1", "vni 10011", "    vlan 11", "    no shutdown"), [], [_ROW],
    ),
    "a VTEP down and a VTEP up": (
        _vtep("1", "shutdown", "vni 10011", "    vlan 11")
        + _vtep("2", "no shutdown", "vni 10012", "    vlan 12"),
        [(12, 10012)],
        [_ROW],
    ),
}


@pytest.mark.parametrize("form", sorted(FORMS))
def test_each_form(form):
    body, bindings, rows = FORMS[form]
    tree = get_codec("aruba_aoscx").parse(_HEAD + body)
    assert [(v.vlan_id, v.vni) for v in tree.vxlan_vnis] == bindings
    assert [r for r in tree.dropped_tier3_sections if r.startswith("shutdown: ")] == rows
    assert all(is_left_out_row(r) for r in rows)


def test_a_vtep_that_is_up_keeps_its_source():
    tree = get_codec("aruba_aoscx").parse(_HEAD + _UP)
    assert [v.source_interface for v in tree.vxlan_vnis] == ["198.51.100.1"]


#: The public targets that write an AOS-CX VTEP's VNIs at all (read from
#: their output below, typed here).
WRITES_VNIS = {
    "arista_eos", "aruba_aoscx", "cisco_iosxe_cli", "cisco_nxos", "juniper_junos", "vyos",
}

#: The VNI, as a number of its own in a line of any grammar.
_VNI = re.compile(r"(?<![\d.])10011(?![\d.])")


@functools.cache
def _job(body: str, target: str) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec("aruba_aoscx"), get_codec(target), _HEAD + body, port_rename_map={},
    )


def check_output(rendered: str, carried: bool, target: str) -> None:
    """The output writes the VNI exactly where it is *carried*."""
    assert bool(_VNI.search(rendered)) == carried, (target, carried)


@pytest.mark.parametrize("target", PUBLIC)
def test_the_vni_of_a_vtep_that_is_down_is_in_no_output(target):
    job = _job(_SHUT, target)
    check_output(job.rendered or "", False, target)
    assert _ROW in job.dropped_tier3_sections


@pytest.mark.parametrize("target", PUBLIC)
def test_the_vni_of_a_vtep_that_is_up_is_where_an_overlay_is_written(target):
    check_output(_job(_UP, target).rendered or "", target in WRITES_VNIS, target)


def test_aoscx_writes_no_vtep_for_one_that_is_down():
    assert "interface vxlan" not in (_job(_SHUT, "aruba_aoscx").rendered or "")


def test_writes_vnis_names_public_codecs():
    assert set(PUBLIC) >= WRITES_VNIS


def test_the_check_fails_on_the_output_of_a_vtep_read_as_up():
    """Up to 0.7.7 a shut VTEP was read as the same tree as one that is
    up, so its output was the output of ``_UP``: the check is handed
    that, and fails."""
    for target in sorted(WRITES_VNIS):
        with pytest.raises(AssertionError):
            check_output(_job(_UP, target).rendered or "", False, target)


def test_the_reader_reads_the_vni_as_a_number_of_its_own():
    assert _VNI.search("    vni 10011\n")
    assert _VNI.search("   vxlan vlan 11 vni 10011\n")
    assert _VNI.search("set vlans v11 vxlan vni 10011\n")
    assert not _VNI.search("    vni 100110\n")
    assert not _VNI.search("    ip address 10.0.10011.1/24\n")
