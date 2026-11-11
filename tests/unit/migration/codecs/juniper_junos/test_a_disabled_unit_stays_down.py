"""A Junos unit that is disabled is down on every target.

A unit is disabled by a line of its own (``set interfaces irb unit 10
disable``) or with its device (``set interfaces lo0 disable``, or an
``interface-range`` that disables its members).  The parser lost both:

* An ``irb`` unit bound to a VLAN (``set vlans v10 l3-interface
  irb.10``) is folded onto the VLAN's record, which has no state of its
  own, so a disabled unit's address was the VLAN's, up.  The fold now
  keeps a disabled unit as the interface it is.
* A device's ``disable`` stayed on the device's record, and each unit
  above 0 is a record of its own: ``lo0.1`` came out as a live
  ``Loopback1``, ``irb.10`` as a live ``Vlan10``.  A unit of a disabled
  device is now disabled with it.  Unit 0 is the device's own record,
  and a ``unit 0 disable`` is no line of the device's.

Every case went to every target in a job that said ``completed``.  The
outputs are read back with each target's own parser (every interface
that holds the address is disabled) and, for the targets that write an
interface as a stanza, as text: the stanza that holds the address says
``shutdown``, and not ``no shutdown``.  AOS-S has no form for a VLAN
that is disabled, and none is known for a loopback that is down: it
refuses either with a review line.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.codecs.aruba_aoss import render as aoss_render
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

_ADDR = "198.51.100.1"

_IRB = (
    "set system host-name r1\n"
    "set vlans v10 vlan-id 10\n"
    "set vlans v10 l3-interface irb.10\n"
    "set interfaces ge-0/0/3 unit 0 family ethernet-switching vlan members v10\n"
    f"set interfaces irb unit 10 family inet address {_ADDR}/24\n"
)
_LO0 = f"set system host-name r1\nset interfaces lo0 unit 1 family inet address {_ADDR}/32\n"

#: Each way to disable a unit, and the unit's name in the tree.
_SOURCES = {
    "irb unit": (_IRB + "set interfaces irb unit 10 disable\n", "irb.10"),
    "irb device": (_IRB + "set interfaces irb disable\n", "irb.10"),
    "lo0 device": ("set interfaces lo0 disable\n" + _LO0, "lo0.1"),
}

#: The pairs whose output holds the address on no interface, each with
#: its reason: AOS-S refuses a disabled VLAN interface and a disabled
#: loopback; IOS XR and VyOS write no address for a Junos ``irb`` unit,
#: up or down.
#: Compared for equality with what is measured.
_HOLDS_NO_ADDRESS = {
    ("irb unit", "aruba_aoss"),
    ("irb device", "aruba_aoss"),
    ("lo0 device", "aruba_aoss"),
    ("irb unit", "cisco_iosxr"),
    ("irb device", "cisco_iosxr"),
    ("irb unit", "vyos"),
    ("irb device", "vyos"),
}

#: The targets that write an interface as a stanza: a header line in
#: column 0, the lines under it indented.
_STANZA_TARGETS = (
    "arista_eos", "aruba_aoscx", "cisco_iosxe_cli", "cisco_iosxr", "cisco_nxos", "dell_os10",
)


def _tree(text: str) -> list[tuple[str, bool, list[str]]]:
    tree = get_codec("juniper_junos").parse(text)
    return [(i.name, i.enabled, [a.ip for a in i.ipv4_addresses]) for i in tree.interfaces]


def _job(text: str, target: str):
    return run_plan_with_checked_names(
        get_codec("juniper_junos"), get_codec(target), text, port_rename_map={},
    )


def _stanzas_holding(out: str, needle: str) -> list[list[str]]:
    """Each stanza of *out* (its header and the lines under it, as they
    stand) that has a line holding *needle*, read by hand: a stanza
    begins at a line in column 0 and runs over the indented lines after
    it."""
    stanzas: list[list[str]] = []
    for line in out.splitlines():
        if line and not line[0].isspace():
            stanzas.append([line])
        elif stanzas:
            stanzas[-1].append(line)
    return [s for s in stanzas if any(needle in line for line in s)]


class TestTheTree:
    def test_a_disabled_irb_unit_is_not_folded_onto_its_vlan(self) -> None:
        tree = get_codec("juniper_junos").parse(_SOURCES["irb unit"][0])
        assert [(i.name, i.enabled) for i in tree.interfaces if i.name.startswith("irb")] == [
            ("irb.10", False),
        ]
        assert [(v.id, v.ipv4_addresses) for v in tree.vlans] == [(10, [])]

    def test_an_irb_unit_that_is_up_is_folded_as_before(self) -> None:
        tree = get_codec("juniper_junos").parse(_IRB)
        assert [i.name for i in tree.interfaces if i.name.startswith("irb")] == []
        assert [(v.id, [a.ip for a in v.ipv4_addresses]) for v in tree.vlans] == [(10, [_ADDR])]

    @pytest.mark.parametrize(("text", "unit"), [
        (_SOURCES["irb device"][0], "irb.10"),
        (_SOURCES["lo0 device"][0], "lo0.1"),
        (
            "set interfaces ge-0/0/2 disable\n"
            "set interfaces ge-0/0/2 vlan-tagging\n"
            "set interfaces ge-0/0/2 unit 5 vlan-id 5\n"
            f"set interfaces ge-0/0/2 unit 5 family inet address {_ADDR}/24\n",
            "ge-0/0/2.5",
        ),
        (
            "set interfaces interface-range R member ge-0/0/2\n"
            "set interfaces interface-range R disable\n"
            "set interfaces ge-0/0/2 vlan-tagging\n"
            "set interfaces ge-0/0/2 unit 5 vlan-id 5\n"
            f"set interfaces ge-0/0/2 unit 5 family inet address {_ADDR}/24\n",
            "ge-0/0/2.5",
        ),
    ], ids=["irb", "lo0", "port", "range"])
    def test_a_unit_of_a_disabled_device_is_disabled(self, text: str, unit: str) -> None:
        assert [(n, up) for n, up, _a in _tree(text) if n == unit] == [(unit, False)]

    @pytest.mark.parametrize("tagged", [True, False], ids=["tagged unit 0", "untagged unit 0"])
    def test_a_unit_0_disable_disables_no_other_unit(self, tagged: bool) -> None:
        text = (
            ("set interfaces ge-0/0/2 vlan-tagging\n" if tagged else "")
            + "set interfaces ge-0/0/2 unit 0 disable\n"
            + ("set interfaces ge-0/0/2 unit 0 vlan-id 4\n" if tagged else "")
            + "set interfaces ge-0/0/2 unit 0 family inet address 192.0.2.1/24\n"
            "set interfaces ge-0/0/2 unit 5 vlan-id 5\n"
            f"set interfaces ge-0/0/2 unit 5 family inet address {_ADDR}/24\n"
        )
        assert [(n, up) for n, up, _a in _tree(text) if n == "ge-0/0/2.5"] == [("ge-0/0/2.5", True)]

    def test_a_deactivated_disable_disables_nothing(self) -> None:
        text = "deactivate interfaces lo0 disable\n" + _SOURCES["lo0 device"][0]
        assert [(n, up) for n, up, _a in _tree(text) if n == "lo0.1"] == [("lo0.1", True)]

    @pytest.mark.parametrize("key", ["irb unit", "lo0 device"])
    def test_the_block_form_is_the_set_form(self, key: str) -> None:
        block = {
            "irb unit": (
                "system {\n    host-name r1;\n}\n"
                "interfaces {\n    ge-0/0/3 {\n        unit 0 {\n            family ethernet-switching {\n"
                "                vlan {\n                    members v10;\n                }\n"
                "            }\n        }\n    }\n"
                "    irb {\n        unit 10 {\n            disable;\n            family inet {\n"
                f"                address {_ADDR}/24;\n            }}\n        }}\n    }}\n}}\n"
                "vlans {\n    v10 {\n        vlan-id 10;\n        l3-interface irb.10;\n    }\n}\n"
            ),
            "lo0 device": (
                "system {\n    host-name r1;\n}\n"
                "interfaces {\n    lo0 {\n        disable;\n        unit 1 {\n"
                f"            family inet {{\n                address {_ADDR}/32;\n            }}\n"
                "        }\n    }\n}\n"
            ),
        }[key]
        assert _tree(block) == _tree(_SOURCES[key][0])


@pytest.mark.parametrize("key", sorted(_SOURCES))
class TestEveryTarget:
    def test_the_address_is_on_no_interface_that_is_up(self, key: str) -> None:
        text, _unit = _SOURCES[key]
        up: dict[str, list[str]] = {}
        nowhere: set[tuple[str, str]] = set()
        for target in sorted(list_public_codecs()):
            codec = get_codec(target)
            back = codec.parse(_job(text, target).rendered or "")
            holding = [i for i in back.interfaces if any(a.ip == _ADDR for a in i.ipv4_addresses)]
            if not holding:
                nowhere.add((key, target))
            if [i for i in holding if i.enabled]:
                up[target] = [i.name for i in holding if i.enabled]
        assert up == {}
        assert nowhere == {pair for pair in _HOLDS_NO_ADDRESS if pair[0] == key}

    def test_the_stanza_that_holds_it_says_shutdown(self, key: str) -> None:
        text, _unit = _SOURCES[key]
        wrong: dict[str, list[list[str]]] = {}
        for target in _STANZA_TARGETS:
            for stanza in _stanzas_holding(_job(text, target).rendered or "", _ADDR):
                body = [line.strip() for line in stanza[1:]]
                if "shutdown" not in body or "no shutdown" in body:
                    wrong.setdefault(target, []).append(stanza)
        assert wrong == {}

    def test_a_target_that_holds_no_address_says_so(self, key: str) -> None:
        """Where the address is on no interface, the job is ``partial``
        or a review line says why."""
        text, _unit = _SOURCES[key]
        silent = []
        for pair in sorted(_HOLDS_NO_ADDRESS):
            if pair[0] != key:
                continue
            job = _job(text, pair[1])
            if job.status.value != "partial" and "; review:" not in (job.rendered or ""):
                silent.append(pair[1])
        assert silent == []


class TestAossRefusesIt:
    _WHY = "interface irb.10 is disabled, and an AOS-S VLAN cannot be; not written"

    def test_the_job_says_it_and_writes_no_address(self) -> None:
        job = _job(_SOURCES["irb unit"][0], "aruba_aoss")
        out = job.rendered or ""
        assert f"; review: {self._WHY}" in out.splitlines()
        assert _ADDR not in out
        assert [w for w in job.warnings if w == self._WHY] == [self._WHY]

    @staticmethod
    def _tree(enabled: bool) -> CanonicalIntent:
        """An ``irb.10`` holding the address its VLAN's record holds as
        well, as a parser that mirrors it there makes."""
        addr = CanonicalIPv4Address(ip=_ADDR, prefix_length=24)
        return CanonicalIntent(
            hostname="r1",
            vlans=[CanonicalVlan(id=10, ipv4_addresses=[addr])],
            interfaces=[CanonicalInterface(
                name="irb.10", enabled=enabled, interface_type="ianaift:l3ipvlan",
                ipv4_addresses=[addr.model_copy()],
            )],
        )

    def test_its_address_comes_off_its_vlans_record(self) -> None:
        out = aoss_render.render_intent(self._tree(enabled=False))
        assert _ADDR not in out
        assert f"; review: {self._WHY}" in out.splitlines()

    def test_one_that_is_up_is_written_in_its_vlan(self) -> None:
        out = aoss_render.render_intent(self._tree(enabled=True))
        assert f"   ip address {_ADDR}/24" in out.splitlines()
        assert "; review:" not in out

    def test_a_disabled_loopback_is_refused_too(self) -> None:
        """``lo0`` and its unit 1 are loopbacks 0 and 1, both down."""
        job = _job(_SOURCES["lo0 device"][0], "aruba_aoss")
        out = job.rendered or ""
        why = [
            f"interface loopback{n} is disabled, and no AOS-S form is known "
            f"for a loopback that is down; not written"
            for n in (0, 1)
        ]
        assert [line for line in out.splitlines() if "; review:" in line] == [
            f"; review: {w}" for w in why
        ]
        assert _ADDR not in out
        assert not [line for line in out.splitlines() if line.startswith("interface loopback")]
        assert [w for w in job.warnings if "loopback" in w] == why
