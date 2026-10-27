"""Keeps ``TRUNK_ALLOWED_SPECIFICITY_BOUND`` honest against the corpus.

``canonical.transforms.switchport_declared_vlan_ids`` decides whether a
``trunk_allowed_vlans`` list is a *specific declaration* (every member is a
real VLAN) or the *"allow everything" idiom* (it names no VLAN at all) by a
single number: the length of the expanded list.

A bare constant in prose or code rots silently — which is exactly the failure
this project forbids.  So the number is not asserted; the **gap it sits in**
is measured, on every CI run, from the committed captures themselves.

What the corpus looked like when the bound was chosen (2026-09-23)::

    real, undeclared on a trunk        <=   12 VIDs per list
    real, fully declared                    85 VIDs per list  (a Junos ae)
    "allow everything" idiom          4093 / 4094 VIDs per list

Two populations, separated by a ~48x gap with nothing in between.  The bound
is 128 — above every genuine list, ~4x below the narrowest phantom case the
regression guards pin (``500-999``).

If a future capture lands a *legitimate* trunk list wider than the bound, its
VLANs would be dropped at parse time and nothing else in the suite would
notice: the loss happens before any render or cross-mesh comparison, so the
cell still scores ALIGNED.  That is precisely how the original defect stayed
invisible.  This module is the tripwire for a recurrence.

See ``tests/unit/migration/codecs/cisco_iosxe_cli/
test_trunk_allowed_phantom_vlan_guard.py`` for the behavioural assertions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.transforms import (
    TRUNK_ALLOWED_SPECIFICITY_BOUND,
    switchport_declared_vlan_ids,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME

pytestmark = pytest.mark.unit

_CORPUS = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "real"

#: Widest list we are willing to call "allow everything".  A real capture
#: between this and the bound would mean the two populations have merged and
#: length alone can no longer separate them.
_PHANTOM_FLOOR = 500

#: Lists in the band that were looked at and decided, each with why.
#: :func:`test_a_decided_list_loses_nothing` holds each to its reason
#: on every run, from the capture's own text.
_DECIDED = {
    ("arista_eos", "dtn_dcs_7050sx3_48yc8_eos4321.txt", "Ethernet49/1"): (
        "`switchport trunk allowed vlan 1-255` on a switch whose VLANs "
        "are each a `vlan` stanza (2-14 and 254): the list names more "
        "VLANs than the switch has.  Its VLANs are records, the trunk is "
        "in each, and the port keeps the list whole; only the ids no "
        "stanza declares are not made into VLANs"
    ),
}

#: A `vlan` stanza's header, as the decided captures print it: ids,
#: ranges and commas.  Typed here, so that the parser is not asked
#: which VLANs its own text declares.
_VLAN_STANZA = re.compile(r"^vlan ([0-9][0-9,\-]*)$", re.MULTILINE)


def _parsed_corpus():
    """Every committed real capture, parsed by its own codec."""
    for dirname, codec_name in sorted(DIR_TO_CODEC_NAME.items()):
        directory = _CORPUS / dirname
        if not directory.is_dir():
            continue
        codec = get_codec(codec_name)
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() in {".md", ""}:
                continue
            try:
                intent = codec.parse(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            except Exception:
                # A codec that cannot parse its own fixture is another
                # test's failure, not this module's.
                continue
            yield codec_name, path.name, intent


def _trunk_list_widths():
    """(codec, fixture, iface, width) for every non-empty trunk-allowed list."""
    for codec_name, fixture, intent in _parsed_corpus():
        for iface in intent.interfaces:
            if iface.trunk_allowed_vlans:
                yield (
                    codec_name,
                    fixture,
                    iface.name,
                    len(iface.trunk_allowed_vlans),
                )


def test_the_corpus_actually_exercises_trunk_allowed_lists() -> None:
    """Guard the guard.  If parsing regresses to producing no trunk lists at
    all, every assertion below would pass vacuously."""
    widths = list(_trunk_list_widths())
    assert len(widths) >= 20, (
        f"only {len(widths)} trunk-allowed lists found in the corpus — the "
        f"measurements below are no longer meaningful"
    )
    assert any(w > _PHANTOM_FLOOR for _, _, _, w in widths), (
        "no wide 'allow everything' list left in the corpus — the bound is "
        "no longer separating two populations"
    )


def test_no_real_trunk_list_falls_in_the_gap() -> None:
    """The load-bearing assertion.

    Nothing in the corpus may sit between the bound and the phantom floor.
    A capture landing there means length no longer separates a specific
    declaration from an allow-everything range, and the rule needs rethinking
    rather than the constant nudging.  A list that was looked at and found
    to lose nothing is in :data:`_DECIDED`, with why, and is held to it below.
    """
    straddlers = [
        (c, f, i, w)
        for c, f, i, w in _trunk_list_widths()
        if TRUNK_ALLOWED_SPECIFICITY_BOUND < w <= _PHANTOM_FLOOR
        and (c, f, i) not in _DECIDED
    ]
    assert not straddlers, (
        "trunk-allowed list(s) landed in the ambiguous band between "
        f"TRUNK_ALLOWED_SPECIFICITY_BOUND ({TRUNK_ALLOWED_SPECIFICITY_BOUND}) "
        f"and the phantom floor ({_PHANTOM_FLOOR}):\n"
        + "\n".join(f"  {c}/{f} {i}: {w} VIDs" for c, f, i, w in straddlers)
        + "\nDecide which population it belongs to before moving the bound — "
        "if it is a real declaration its VLANs are being dropped at parse "
        "time, silently."
    )


def _ids(text: str) -> set[int]:
    """``2-14,254`` as the ids it names."""
    ids: set[int] = set()
    for part in text.split(","):
        low, _, high = part.partition("-")
        ids.update(range(int(low), int(high or low) + 1))
    return ids


def _what_a_decided_list_lost(text: str, intent, iface_name: str) -> list[str]:
    """What the parse of *text* lost of the trunk *iface_name*: its list
    as the text states it, and each VLAN the text declares that the list
    names, as a record with the port in it.  Read from the text by the
    readers typed here, never by the parser."""
    stanza = re.search(
        rf"^interface {re.escape(iface_name)}\n((?:[ \t]+.*\n)*)", text, re.MULTILINE,
    )
    assert stanza, iface_name
    stated = re.search(r"switchport trunk allowed vlan ([0-9,\-]+)$", stanza[1], re.MULTILINE)
    assert stated, iface_name
    listed = _ids(stated[1])
    declared = set().union(*(_ids(m) for m in _VLAN_STANZA.findall(text)))
    assert declared & listed, "nothing the decision rests on"
    lost = []
    iface = next((i for i in intent.interfaces if i.name == iface_name), None)
    if iface is None or set(iface.trunk_allowed_vlans) != listed:
        lost.append(f"{iface_name}: the list is not the one the text states")
    vlans = {v.id: v for v in intent.vlans}
    for vid in sorted(declared & listed):
        vlan = vlans.get(vid)
        if vlan is None:
            lost.append(f"VLAN {vid}: no record")
        elif iface_name not in (*vlan.tagged_ports, *vlan.untagged_ports):
            lost.append(f"VLAN {vid}: {iface_name} is not in it")
    return lost


def _decided():
    """Each decided list, with its capture's text and parse."""
    codec_dir = {codec: dirname for dirname, codec in DIR_TO_CODEC_NAME.items()}
    for (codec_name, fixture, iface_name) in sorted(_DECIDED):
        text = (_CORPUS / codec_dir[codec_name] / fixture).read_text(encoding="utf-8")
        yield codec_name, fixture, iface_name, text, get_codec(codec_name).parse(text)


def test_a_decided_list_loses_nothing() -> None:
    """Each list of :data:`_DECIDED` is still in the band (or its entry is
    stale) and its parse lost nothing the text states."""
    for codec_name, fixture, iface_name, text, intent in _decided():
        iface = next(i for i in intent.interfaces if i.name == iface_name)
        width = len(iface.trunk_allowed_vlans)
        assert TRUNK_ALLOWED_SPECIFICITY_BOUND < width <= _PHANTOM_FLOOR, (
            f"{codec_name}/{fixture} {iface_name}: {width} VIDs, out of the band; "
            "take its entry out of _DECIDED"
        )
        assert _what_a_decided_list_lost(text, intent, iface_name) == [], fixture


def test_the_check_of_a_decided_list_sees_a_loss() -> None:
    """The check handed the defects it is for: a VLAN record gone, the
    port out of one, and the list cut."""
    for _, fixture, iface_name, text, intent in _decided():
        iface = next(i for i in intent.interfaces if i.name == iface_name)
        declared = set().union(*(_ids(m) for m in _VLAN_STANZA.findall(text)))
        first, *_, last = sorted(declared & set(iface.trunk_allowed_vlans))
        gone = intent.model_copy(deep=True)
        gone.vlans = [v for v in gone.vlans if v.id != last]
        assert f"VLAN {last}: no record" in _what_a_decided_list_lost(text, gone, iface_name)
        out = intent.model_copy(deep=True)
        for vlan in out.vlans:
            if vlan.id == first:
                vlan.tagged_ports = [p for p in vlan.tagged_ports if p != iface_name]
                vlan.untagged_ports = [p for p in vlan.untagged_ports if p != iface_name]
        assert f"VLAN {first}: {iface_name} is not in it" in _what_a_decided_list_lost(
            text, out, iface_name,
        )
        cut = intent.model_copy(deep=True)
        for iface in cut.interfaces:
            if iface.name == iface_name:
                iface.trunk_allowed_vlans = iface.trunk_allowed_vlans[:-1]
        assert _what_a_decided_list_lost(text, cut, iface_name), fixture


def test_every_genuine_list_is_under_the_bound() -> None:
    """Every trunk list the corpus treats as real must be comfortably inside
    the bound, with the headroom the docstring claims."""
    real = [
        (c, f, i, w)
        for c, f, i, w in _trunk_list_widths()
        if w <= TRUNK_ALLOWED_SPECIFICITY_BOUND
    ]
    assert real, "no trunk list is being treated as a specific declaration"
    widest = max(real, key=lambda r: r[3])
    assert widest[3] <= TRUNK_ALLOWED_SPECIFICITY_BOUND, widest
    assert widest[3] * 1.3 <= TRUNK_ALLOWED_SPECIFICITY_BOUND, (
        f"widest genuine trunk list ({widest[0]}/{widest[1]} {widest[2]}: "
        f"{widest[3]} VIDs) has less than 30% headroom under the bound "
        f"({TRUNK_ALLOWED_SPECIFICITY_BOUND}) — the next capture like it may "
        f"cross, and crossing is a silent VLAN loss"
    )


def test_wide_lists_contribute_no_declared_vids() -> None:
    """The anti-inflation property, measured rather than asserted on a
    synthetic: for every capture carrying an allow-everything list, the
    declared-VID set stays far below the size of that list."""
    checked = 0
    for codec_name, fixture, intent in _parsed_corpus():
        widest = max(
            (len(i.trunk_allowed_vlans) for i in intent.interfaces),
            default=0,
        )
        if widest <= _PHANTOM_FLOOR:
            continue
        checked += 1
        declared = switchport_declared_vlan_ids(intent)
        assert len(declared) < widest, (
            f"{codec_name}/{fixture}: a {widest}-VID allow-everything list "
            f"inflated the declared set to {len(declared)} VIDs"
        )
    assert checked, "no capture with a wide trunk list — nothing measured"
