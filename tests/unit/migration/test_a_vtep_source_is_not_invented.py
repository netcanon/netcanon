"""A VTEP source that no record states is not invented.

The tree holds no VTEP source when the source config states none (a VyOS
``vxlan`` interface with neither ``source-interface`` nor
``source-address``), when the operator's map dropped the interface it
named, and when the overlay is L3 VNIs only, which have no record to hold
one.  Up to 0.7.7 the EOS, IOS-XE CLI and NX-OS renderers wrote
``Loopback0`` / ``loopback0`` in its place -- an interface nothing names,
which the target may not have -- in jobs that said ``completed``; where
the map had dropped the source, beside a warning that said the VTEP was
left without one.  Junos, VyOS and AOS-CX wrote nothing.  Now no target
writes a source nothing states, and the three write a review line where
the source line would go.

Read here: every public codec's output, as TEXT, by a reader of this
module's own, for a source line that is not a comment; the review line,
in the VTEP's own stanza, typed by hand for each of the three grammars;
and the three parsers on their own output, for the VNIs.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalRoutingInstance,
    CanonicalVlan,
    CanonicalVxlan,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

#: A line that states a VTEP source, in any public grammar (EOS ``vxlan
#: source-interface``, IOS-XE and NX-OS ``source-interface``, Junos
#: ``vtep-source-interface``, VyOS ``source-interface`` /
#: ``source-address``, AOS-CX ``source ip``).  The trees here hold nothing
#: else a source line could be written for.
_A_SOURCE = re.compile(
    r"source-interface|source-address|source[ \t]+ip\b", re.IGNORECASE,
)
#: A comment line, in any public grammar.
_COMMENT = re.compile(r"^[ \t]*(?:!|#|/\*)")

#: The header of the VTEP's stanza, and the review line in it.
REVIEW = {
    "arista_eos": (
        "interface Vxlan1",
        "   ! vxlan source-interface -- review: no source interface of "
        "this VTEP is known, so none is written; give it one",
    ),
    "cisco_iosxe_cli": (
        "interface nve1",
        " ! source-interface -- review: no source interface of this VTEP "
        "is known, so none is written; give it one",
    ),
    "cisco_nxos": (
        "interface nve1",
        "  ! source-interface -- review: no source interface of this VTEP "
        "is known, so none is written; give it one",
    ),
}


def _stanza(text: str, header: str) -> list[str]:
    """The lines of the stanza *header* opens, read by indentation."""
    lines = text.splitlines()
    if header not in lines:
        return []
    body = []
    for line in lines[lines.index(header) + 1:]:
        if not line[:1].isspace():
            break
        body.append(line)
    return body


def check_output(rendered: str, target: str) -> None:
    """*rendered* states no VTEP source; the three write the review line
    in the VTEP's own stanza."""
    named = [
        line for line in rendered.splitlines()
        if _A_SOURCE.search(line) and not _COMMENT.match(line)
    ]
    assert not named, f"{target}: a VTEP source nothing states: {named}"
    if target in REVIEW:
        header, review = REVIEW[target]
        assert review in _stanza(rendered, header), (
            f"{target}: no review line in the {header!r} stanza"
        )


_L2 = CanonicalIntent(
    vlans=[CanonicalVlan(id=10, name="V10"), CanonicalVlan(id=20, name="V20")],
    vxlan_vnis=[
        CanonicalVxlan(vlan_id=10, vni=10010),
        CanonicalVxlan(vlan_id=20, vni=10020),
    ],
)
_L3_ONLY = CanonicalIntent(
    routing_instances=[
        CanonicalRoutingInstance(name="TEN", instance_type="vrf", l3_vni=50001),
    ],
)


@pytest.mark.parametrize("target", PUBLIC)
def test_a_tree_with_no_source(target):
    check_output(get_codec(target).render(_L2.model_copy(deep=True)), target)


@pytest.mark.parametrize("target", PUBLIC)
def test_an_overlay_of_l3_vnis_only(target):
    check_output(get_codec(target).render(_L3_ONLY.model_copy(deep=True)), target)


@pytest.mark.parametrize("target", sorted(REVIEW))
def test_the_parser_reads_its_own_output_whole(target):
    """The review line ends no stanza: the VNIs read back, with no source."""
    codec = get_codec(target)
    back = codec.parse(codec.render(_L2.model_copy(deep=True)))
    assert sorted((v.vlan_id, v.vni, v.source_interface) for v in back.vxlan_vnis) == [
        (10, 10010, ""), (20, 10020, ""),
    ]


@pytest.mark.parametrize("target", sorted(REVIEW))
def test_a_source_that_is_stated_is_written(target):
    tree = _L2.model_copy(deep=True)
    for record in tree.vxlan_vnis:
        record.source_interface = "Loopback1"
    out = get_codec(target).render(tree)
    header, review = REVIEW[target]
    body = _stanza(out, header)
    assert review not in body
    assert [line for line in body if "source-interface Loopback1" in line]


#: A VyOS overlay that states no source.
_VYOS = (
    "set interfaces vxlan vxlan10 vni '10010'\n"
    "set interfaces vxlan vxlan10 remote '192.0.2.9'\n"
    "set interfaces bridge br10 member interface vxlan10\n"
    "set interfaces bridge br10 address '198.51.100.1/24'\n"
)


@pytest.mark.parametrize("target", PUBLIC)
def test_a_source_config_that_states_none(target):
    job = run_plan_with_checked_names(
        get_codec("vyos"), get_codec(target), _VYOS, port_rename_map={},
    )
    check_output(job.rendered or "", target)


#: An EOS overlay whose source the operator's map drops.
_EOS = (
    "hostname a\n"
    "vlan 10\n"
    "interface Loopback1\n"
    "   ip address 192.0.2.1/32\n"
    "interface Vxlan1\n"
    "   vxlan source-interface Loopback1\n"
    "   vxlan udp-port 4789\n"
    "   vxlan vlan 10 vni 10010\n"
)


@pytest.mark.parametrize("target", PUBLIC)
def test_a_source_the_map_drops(target):
    job = run_plan_with_checked_names(
        get_codec("arista_eos"), get_codec(target), _EOS,
        port_rename_map={"Loopback1": None},
    )
    check_output(job.rendered or "", target)
    if target in REVIEW:
        assert any(
            "VXLAN source interface was dropped (Loopback1)" in w
            for w in job.warnings
        )


@pytest.mark.parametrize("target", sorted(REVIEW))
def test_the_check_fails_on_an_invented_source(target):
    """Handed the output as it was written up to 0.7.7, the check fails."""
    header, review = REVIEW[target]
    out = get_codec(target).render(_L2.model_copy(deep=True))
    indent = review[: len(review) - len(review.lstrip())]
    word = "vxlan source-interface" if target == "arista_eos" else "source-interface"
    old = out.replace(review, f"{indent}{word} Loopback0")
    assert old != out
    with pytest.raises(AssertionError):
        check_output(old, target)
    # And with no line at all where the source would go.
    with pytest.raises(AssertionError):
        check_output(out.replace(review + "\n", ""), target)


def test_review_names_public_codecs():
    assert set(PUBLIC) >= set(REVIEW)
