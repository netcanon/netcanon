"""A name nobody mapped stands; a sub-interface goes where its port goes.

Every job runs the port translator on every name no entry of a rename
map decided: the source codec classifies the name, the target codec
formats what it was told.  Two things went wrong there, in jobs that
said ``completed``.

* **One codec on both sides.**  That round trip is not the identity on
  several codecs' own names: on the committed inputs, those of AOS-S,
  IOS-XE (CLI), OS10, FortiOS, Junos and VyOS
  (``test_which_codecs_lose_their_own_names``).  A
  Junos config translated to Junos came back
  with ``fxp0`` as ``em0`` and with ``ge-0/0/1.54`` as ``ge-0/0/1`` --
  the tagged unit on its port, its tag gone; FortiOS ``dmz`` came back
  as ``dmz1``, IOS ``Ethernet0/0`` as ``FastEthernet0/0``, and a
  Catalyst management port and every OS10 breakout lane were dropped.
* **A sub-interface across vendors.**  No classifier keeps a unit.
  Junos and VyOS read ``<port>.<unit>`` as the port, so two interfaces
  were rendered under one name; IOS, EOS, NX-OS and IOS-XR do not know
  the name, so it stayed in the other vendor's config as it was.

Now a name nobody mapped stands between two configs of one codec, and
a sub-interface goes where its port goes, with its unit.

What is read here is the RENDERED OUTPUT of jobs run the way ``POST
/plan`` runs them when no devices are declared
(``run_plan_with_overrides`` with an empty port map; where a test
asks what STATUS such a job has, ``run_plan_with_checked_names``,
which is that run and then a look at what it did to the names),
parsed again with the target codec and compared with something the
translator had no hand in:

* between two configs of one codec, the output of the bare pipeline
  (``run_plan``: parse and render, no translator), as text and parsed;
* across vendors, the source config: each sub-interface is found in
  the output BY ITS ADDRESS, and has to be on an interface of its own
  that is named after what its port became.

The guards that were there compared one output of the translator with
another, and a loss common to both cancels out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical import port_names as translator
from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.port_names import (
    UNIT_PARENT_KINDS,
    collect_port_names,
    split_unit,
    translate_port_names,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import (
    run_plan,
    run_plan_with_checked_names,
    run_plan_with_overrides,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
#: The native capture extensions (the filter the real-capture test and
#: the mesh tool use).
_SUFFIXES = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}


def _inputs() -> list[tuple[str, Path]]:
    """Every committed capture and every kitchen sink, with its codec."""
    found: list[tuple[str, Path]] = []
    for directory in sorted((FIXTURES / "real").iterdir()):
        codec = DIR_TO_CODEC_NAME.get(directory.name)
        if codec is None or not directory.is_dir():
            continue
        found.extend(
            (codec, path) for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in _SUFFIXES
        )
    for directory in sorted((FIXTURES / "synthetic").iterdir()):
        if directory.is_dir() and directory.name in list_public_codecs():
            found.extend(
                (directory.name, path) for path in sorted(directory.iterdir())
                if path.is_file() and path.suffix.lower() in _SUFFIXES
            )
    return found


INPUTS = _inputs()


# ---------------------------------------------------------------------------
# 1. One codec on both sides: an empty port map changes nothing
# ---------------------------------------------------------------------------


class TestOneCodecOnBothSides:
    def test_every_public_codec_has_an_input(self) -> None:
        """So the test below cannot pass by reading nothing."""
        assert {codec for codec, _ in INPUTS} == set(list_public_codecs())

    @pytest.mark.parametrize(
        ("codec_name", "path"), INPUTS,
        ids=[f"{path.parent.name}/{path.name}" for _, path in INPUTS],
    )
    def test_an_empty_port_map_changes_nothing(self, codec_name: str, path: Path) -> None:
        """A name is a name of its own platform by construction.  With
        no entry of a map and no device declared nothing can justify
        another -- and the output has to be the bare pipeline's, read
        from the text and not from the job's lists."""
        codec = get_codec(codec_name)
        text = path.read_text(encoding="utf-8")
        bare = run_plan(codec, codec, text)
        job = run_plan_with_overrides(codec, codec, text, port_rename_map={})
        assert job.port_renames == {}, "a job from a codec to itself renamed a port"
        assert job.port_drops == [], "a job from a codec to itself dropped a port"
        assert job.status == bare.status
        if bare.rendered is None:
            return
        assert job.rendered is not None
        # Parsed again first: a difference is then said field by field.
        assert codec.parse(job.rendered).model_dump() == codec.parse(bare.rendered).model_dump()
        assert job.rendered == bare.rendered

    def test_no_name_is_put_to_the_classifier(self, monkeypatch) -> None:
        """Not even to be told it is unknown: a codec's own name needs
        no reading, and a classifier that cannot read one must not be
        able to fail the job."""
        junos = get_codec("juniper_junos")

        def explode(_name: str):
            raise RuntimeError("no")

        bare = run_plan(junos, junos, _UNITS["juniper_junos"][1])
        monkeypatch.setattr(junos, "classify_port_name", explode)
        job = run_plan_with_overrides(junos, junos, _UNITS["juniper_junos"][1], port_rename_map={})
        assert job.status == MigrationJobStatus.completed
        assert job.rendered == bare.rendered and job.warnings == bare.warnings

    def test_which_codecs_lose_their_own_names(self) -> None:
        """What the rule above is for, measured: over every name of
        the committed inputs that its own classifier knows, the
        codecs whose own formatter then writes another name, or
        none.  Not all of them -- the documents name these, and this
        keeps the list true.  (A codec that leaves it is no reason
        to ask its classifier again: the list is of the inputs
        committed here, and the rule is for any config.)"""
        differs: set[str] = set()
        for codec_name, path in INPUTS:
            codec = get_codec(codec_name)
            for name in collect_port_names(codec.parse(path.read_text(encoding="utf-8"))):
                identity = codec.classify_port_name(name)
                if identity is None or identity.kind == "unknown":
                    continue
                if codec.format_port_identity(identity) != name:
                    differs.add(codec_name)
        assert differs == {
            "aruba_aoss", "cisco_iosxe_cli", "dell_os10", "fortigate_cli",
            "juniper_junos", "vyos",
        }


# ---------------------------------------------------------------------------
# 2. A sub-interface, from each grammar that names one, onto every codec
# ---------------------------------------------------------------------------

#: One config per codec whose GRAMMAR names a sub-interface
#: ``<port>.<unit>``: the port, two units of it with a tag and an
#: address each, and a second port.  Unit 54 carries tag 300 where the
#: grammar lets a unit's number differ from its tag, so an output that
#: takes the tag from the name is told from one that carries it.
_UNITS: dict[str, tuple[str, str]] = {
    "juniper_junos": ("ge-0/0/1", "\n".join([
        "set system host-name r1",
        "set interfaces ge-0/0/1 description PARENT",
        "set interfaces ge-0/0/1 vlan-tagging",
        "set interfaces ge-0/0/1 unit 54 vlan-id 300",
        "set interfaces ge-0/0/1 unit 54 family inet address 10.54.0.1/24",
        "set interfaces ge-0/0/1 unit 55 vlan-id 55",
        "set interfaces ge-0/0/1 unit 55 family inet address 10.55.0.1/24",
        "set interfaces ge-0/0/2 unit 0 family inet address 10.2.0.1/24",
        "",
    ])),
    "cisco_iosxe_cli": ("GigabitEthernet0/0/1", "\n".join([
        "!", "version 17.9", "hostname r1", "!",
        "interface GigabitEthernet0/0/1", " description PARENT", " no ip address", "!",
        "interface GigabitEthernet0/0/1.54", " encapsulation dot1Q 300",
        " ip address 10.54.0.1 255.255.255.0", "!",
        "interface GigabitEthernet0/0/1.55", " encapsulation dot1Q 55",
        " ip address 10.55.0.1 255.255.255.0", "!",
        "interface GigabitEthernet0/0/2", " ip address 10.2.0.1 255.255.255.0", "!", "end", "",
    ])),
    "arista_eos": ("Ethernet1", "\n".join([
        "! device: r1 (DCS-7050SX-64, EOS-4.27.0F)", "!", "hostname r1", "!",
        "interface Ethernet1", "   description PARENT", "   no switchport", "!",
        "interface Ethernet1.54", "   encapsulation dot1q vlan 300", "   ip address 10.54.0.1/24", "!",
        "interface Ethernet1.55", "   encapsulation dot1q vlan 55", "   ip address 10.55.0.1/24", "!",
        "interface Ethernet2", "   no switchport", "   ip address 10.2.0.1/24", "!", "end", "",
    ])),
    "cisco_nxos": ("Ethernet1/1", "\n".join([
        "!Command: show running-config", "version 9.3(11) Bios:version", "hostname r1", "",
        "interface Ethernet1/1", "  description PARENT", "  no switchport", "",
        "interface Ethernet1/1.54", "  encapsulation dot1q 300", "  ip address 10.54.0.1/24", "",
        "interface Ethernet1/1.55", "  encapsulation dot1q 55", "  ip address 10.55.0.1/24", "",
        "interface Ethernet1/2", "  no switchport", "  ip address 10.2.0.1/24", "",
    ])),
    "cisco_iosxr": ("GigabitEthernet0/0/0/1", "\n".join([
        "!! IOS XR Configuration 7.3.2", "!", "hostname r1", "!",
        "interface GigabitEthernet0/0/0/1", " description PARENT", "!",
        "interface GigabitEthernet0/0/0/1.54", " ipv4 address 10.54.0.1 255.255.255.0",
        " encapsulation dot1q 300", "!",
        "interface GigabitEthernet0/0/0/1.55", " ipv4 address 10.55.0.1 255.255.255.0",
        " encapsulation dot1q 55", "!",
        "interface GigabitEthernet0/0/0/2", " ipv4 address 10.2.0.1 255.255.255.0", "!", "end", "",
    ])),
    # A vif's number IS its tag.
    "vyos": ("eth1", "\n".join([
        "interfaces {", "    ethernet eth1 {", '        description "PARENT"',
        "        vif 54 {", "            address 10.54.0.1/24", "        }",
        "        vif 55 {", "            address 10.55.0.1/24", "        }", "    }",
        "    ethernet eth2 {", "        address 10.2.0.1/24", "    }", "}",
        "system {", "    host-name r1", "}",
        '// vyos-config-version: "system@27:interfaces@29"', "",
    ])),
}
#: The two units of each config above, by the address each carries.
_UNIT_ADDRESSES = (("54", "10.54.0.1"), ("55", "10.55.0.1"))

_PAIRS = [(source, target) for source in _UNITS for target in list_public_codecs()]
_PAIR_IDS = [f"{source}->{target}" for source, target in _PAIRS]

#: Pairs on which the PORT has no name on the target, so the translator
#: drops it and its units go with it.  The validation report has
#: nothing to say of an interface that is not there, so the status of
#: such a job is not the report's to give: it comes from what the run
#: did to the names (``run_plan_with_checked_names``).  Such a job
#: said ``completed`` while a status looked at the report alone.
_PORT_HAS_NO_NAME = {("cisco_nxos", "aruba_aoss")}


def _holders(tree, ip: str) -> list:
    return [
        iface for iface in tree.interfaces
        if any(address.ip == ip for address in iface.ipv4_addresses)
    ]


def _tag_of(source_name: str, unit: str) -> int:
    return 300 if unit == "54" and source_name != "vyos" else int(unit)


def _routeros_line_says(text: str, name: str, tag: int) -> bool:
    """An ``add`` line of ``/interface vlan`` names *name* and states
    *tag*."""
    names = {f"name={name}", f'name="{name}"'}
    section = ""
    for line in text.splitlines():
        words = line.split()
        if line.startswith("/"):
            section = line.strip()
        elif (
            section == "/interface vlan" and words[:1] == ["add"]
            and names & set(words) and f"vlan-id={tag}" in words
        ):
            return True
    return False


#: Targets whose sub-interface is NAMED by its tag: VyOS, where
#: ``eth1.300`` is ``vif 300`` and carries VLAN 300.  Onto these a
#: unit goes with its tag after its port, not its number.  Typed
#: here, not read from the codec.
_NAMED_BY_TAG = {"vyos"}


def _fortios_block_says(text: str, name: str, tag: int) -> bool:
    """The ``edit`` block of *name* in ``config system interface``
    states ``set vlanid <tag>``."""
    section = block = False
    for line in text.splitlines():
        words = line.split()
        if words == ["config", "system", "interface"]:
            section = True
        elif section and words[:1] == ["edit"]:
            block = line.strip() in (f'edit "{name}"', f"edit {name}")
        elif section and words == ["next"]:
            block = False
        elif block and words == ["set", "vlanid", str(tag)]:
            return True
    return False


def _opnsense_device_says(text: str, name: str, tag: int) -> bool:
    """A ``<vlan>`` of ``<vlans>`` in *text* is the device *name*
    (``<vlanif>``) with ``<tag>`` *tag*."""
    from xml.etree import ElementTree as ET

    return any(
        (vlan.findtext("vlanif") or "").strip() == name
        and (vlan.findtext("tag") or "").strip() == str(tag)
        for vlan in ET.fromstring(text).iterfind("vlans/vlan")
    )


#: Targets whose parser reads a sub-interface's tag otherwise than as
#: ``dot1q_vlan``, with a reader of the text that states it.  RouterOS
#: writes a sub-interface as a VLAN interface on its port (``/interface
#: vlan add interface=ether1 name=ether1.54 vlan-id=300``) and FortiOS
#: as one too (``edit "port1.54"`` / ``set vlanid 300`` / ``set
#: interface "port1"``); each writes a VLAN interface on a port and on
#: a bridge or a switch interface alike, so its parser reads it as a
#: VLAN interface and a VLAN of the tag under the interface's name.
#: OPNsense writes it as a VLAN device on its port (``<vlan>`` with
#: ``<if>``, ``<tag>`` and ``<vlanif>``), which its parser reads the
#: same way.  The tag is taken where the parser reads it so AND the
#: text states it.
_TAG_AS_A_VLAN_OF_ITS_NAME = {
    "mikrotik_routeros": _routeros_line_says,
    "fortigate_cli": _fortios_block_says,
    "opnsense": _opnsense_device_says,
}


def _tags(target_name: str, out, iface, rendered: str) -> set[int]:
    """The tags the output carries on *iface*, read the target's way."""
    tags = {iface.dot1q_vlan} - {None}
    says = _TAG_AS_A_VLAN_OF_ITS_NAME.get(target_name)
    if says is not None and iface.interface_type == "ianaift:l3ipvlan":
        tags |= {
            vlan.id for vlan in out.vlans
            if vlan.name == iface.name and says(rendered, iface.name, vlan.id)
        }
    return tags


class TestASubInterfaceOnEveryPair:
    """Every pair that can be made of the source grammars above and
    the public targets -- not every pair of codecs: AOS-S, AOS-CX,
    OS10, FortiOS, RouterOS, OPNsense and the NETCONF codec are
    targets here and not sources."""

    @pytest.mark.parametrize(("source_name", "target_name"), _PAIRS, ids=_PAIR_IDS)
    def test_it_is_an_interface_of_its_own(self, source_name: str, target_name: str) -> None:
        """Read from the output, by address: each unit is on one
        interface, no interface holds two, and its name is what its
        port became with the unit after it -- or, onto a target whose
        sub-interface is named by its tag, the tag.  A unit that is not in the
        output at all has to be in ``port_drops``, with its port."""
        source, target = get_codec(source_name), get_codec(target_name)
        port, text = _UNITS[source_name]
        job = run_plan_with_overrides(source, target, text, port_rename_map={})
        assert job.rendered, job.error
        out = target.parse(job.rendered)
        where = job.port_renames.get(port, port)
        for unit, ip in _UNIT_ADDRESSES:
            name = f"{port}.{unit}"
            holders = _holders(out, ip)
            if not holders:
                assert name in job.port_drops and port in job.port_drops, (
                    f"{name} is not in the output and the job does not say "
                    f"it was dropped with its port"
                )
                continue
            (iface,) = holders
            others = {address.ip for address in iface.ipv4_addresses} - {ip}
            assert not others, f"{name} shares {iface.name!r} with {sorted(others)}"
            after = (
                str(_tag_of(source_name, unit))
                if target_name in _NAMED_BY_TAG and source_name != target_name
                else unit
            )
            assert job.port_renames.get(name, name) == f"{where}.{after}"
            assert iface.name == f"{where}.{after}", f"{name} is on {iface.name!r}"

    @pytest.mark.parametrize(
        ("source_name", "target_name"),
        [pair for pair in _PAIRS if pair not in _PORT_HAS_NO_NAME],
        ids=[
            name for pair, name in zip(_PAIRS, _PAIR_IDS, strict=True)
            if pair not in _PORT_HAS_NO_NAME
        ],
    )
    def test_a_lost_tag_is_not_completed(self, source_name: str, target_name: str) -> None:
        """Where the output cannot be read back as carrying the tag on
        the unit's own interface, the job must not say ``completed``
        -- by the validation report alone, which is what lists a tag
        the target cannot carry.  (Where the unit is not in the output
        at all the report lists nothing: the next test.)"""
        source, target = get_codec(source_name), get_codec(target_name)
        _, text = _UNITS[source_name]
        job = run_plan_with_overrides(source, target, text, port_rename_map={})
        out = target.parse(job.rendered)
        for unit, ip in _UNIT_ADDRESSES:
            tag = _tag_of(source_name, unit)
            holders = _holders(out, ip)
            if len(holders) != 1 or tag not in _tags(target_name, out, holders[0], job.rendered):
                assert job.status != MigrationJobStatus.completed, (
                    f"{ip}: tag {tag} is not in the output "
                    f"({[(h.name, h.dot1q_vlan) for h in holders]}) and the job is completed"
                )

    @pytest.mark.parametrize("source_name", sorted(_UNITS))
    def test_routeros_is_read_for_a_tag_it_wrote(
        self, source_name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handed the RouterOS renderer that wrote no line for a
        sub-interface -- the defect RouterOS's reading is for -- the
        reading finds no tag, and the job says ``completed``: the check
        above fails."""
        import copy

        from netcanon.migration.codecs.mikrotik_routeros import codec as ros_codec

        real = ros_codec.render_intent

        def render(tree):
            tree = copy.deepcopy(tree)
            for iface in tree.interfaces:
                iface.dot1q_vlan = None
            return real(tree)

        monkeypatch.setattr(ros_codec, "render_intent", render)
        target = get_codec("mikrotik_routeros")
        _, text = _UNITS[source_name]
        job = run_plan_with_overrides(get_codec(source_name), target, text, port_rename_map={})
        out = target.parse(job.rendered)
        unit, ip = _UNIT_ADDRESSES[0]
        (holder,) = _holders(out, ip)
        assert _tag_of(source_name, unit) not in _tags("mikrotik_routeros", out, holder, job.rendered)
        assert job.status == MigrationJobStatus.completed

    @pytest.mark.parametrize("source_name", sorted(_UNITS))
    def test_fortios_is_read_for_a_tag_it_wrote(
        self, source_name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handed the FortiOS renderer that wrote the number in a
        unit's name for its tag -- the defect FortiOS's reading is
        for -- the reading finds no tag where the two differ, and the
        job says ``completed``: the check above fails."""
        import copy

        from netcanon.migration.codecs.fortigate_cli import codec as fgt_codec

        real = fgt_codec.render_intent

        def render(tree):
            tree = copy.deepcopy(tree)
            for iface in tree.interfaces:
                iface.dot1q_vlan = None
            return real(tree)

        monkeypatch.setattr(fgt_codec, "render_intent", render)
        target = get_codec("fortigate_cli")
        _, text = _UNITS[source_name]
        job = run_plan_with_overrides(get_codec(source_name), target, text, port_rename_map={})
        out = target.parse(job.rendered)
        lost = [
            ip for unit, ip in _UNIT_ADDRESSES
            if _tag_of(source_name, unit) != int(unit)
            and _tag_of(source_name, unit)
            not in _tags("fortigate_cli", out, _holders(out, ip)[0], job.rendered)
        ]
        expected = [
            ip for unit, ip in _UNIT_ADDRESSES if _tag_of(source_name, unit) != int(unit)
        ]
        assert lost == expected
        if expected:
            assert job.status == MigrationJobStatus.completed

    @pytest.mark.parametrize("source_name", sorted(_UNITS))
    def test_opnsense_is_read_for_the_device_it_wrote(
        self, source_name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handed the OPNsense renderer that wrote a sub-interface's
        zone and no VLAN device -- the defect OPNsense's reading is
        for -- the reading finds no tag on any unit, and the job says
        ``completed``: the check above fails."""
        import copy

        from netcanon.migration.codecs.opnsense import codec as opn_codec

        real = opn_codec.render_intent

        def render(tree, *args, **kwargs):
            tree = copy.deepcopy(tree)
            for iface in tree.interfaces:
                iface.dot1q_vlan = None
            return real(tree, *args, **kwargs)

        monkeypatch.setattr(opn_codec, "render_intent", render)
        target = get_codec("opnsense")
        _, text = _UNITS[source_name]
        job = run_plan_with_overrides(get_codec(source_name), target, text, port_rename_map={})
        out = target.parse(job.rendered)
        lost = [
            ip for unit, ip in _UNIT_ADDRESSES
            if _tag_of(source_name, unit)
            not in _tags("opnsense", out, _holders(out, ip)[0], job.rendered)
        ]
        assert lost == [ip for _, ip in _UNIT_ADDRESSES]
        assert job.status == MigrationJobStatus.completed

    @pytest.mark.parametrize(
        ("source_name", "target_name"), sorted(_PORT_HAS_NO_NAME),
    )
    def test_dropped_with_a_port_is_partial(
        self, source_name: str, target_name: str,
    ) -> None:
        """The job says which interfaces went: in ``port_drops``, in a
        warning each, and in its status.  It said ``completed`` while
        a status looked at the validation report alone -- as did
        every job whose ports the translator drops, with or without
        units.  Run the way ``POST /plan`` runs it the job is
        ``partial`` and lists the port and its units as dropped with
        nothing deciding them; an entry that drops the port decides
        its units with it.  (A unit that MOVED and took no tag with
        it is another matter, and is said in a warning: see
        ``TestAUnitWithNoTag``.)"""
        source, target = get_codec(source_name), get_codec(target_name)
        port, text = _UNITS[source_name]
        job = run_plan_with_checked_names(source, target, text, port_rename_map={})
        units = [f"{port}.{unit}" for unit, _ in _UNIT_ADDRESSES]
        assert {port, *units} <= set(job.port_drops)
        for name in units:
            assert (
                f"port_rename: {name!r} is a unit of {port!r}, which is not "
                f"in the output; dropped with it"
            ) in job.warnings
        assert not any(ip in job.rendered for _, ip in _UNIT_ADDRESSES)
        assert job.status == MigrationJobStatus.partial
        assert {port, *units} <= set(job.unresolved_ports)
        assert job.error.startswith("Port names are not settled: ")
        # The run itself is the one that was made before: the status
        # of the pipeline's older entry is the report's, as it was.
        before = run_plan_with_overrides(source, target, text, port_rename_map={})
        assert before.status == MigrationJobStatus.completed
        assert before.rendered == job.rendered
        # Dropping each port is deciding its units.
        ports = [name for name in job.unresolved_ports if split_unit(name) is None]
        decided = run_plan_with_checked_names(
            source, target, text, port_rename_map=dict.fromkeys(ports),
        )
        assert set(units) <= set(decided.port_drops)
        assert decided.unresolved_ports == []
        assert decided.status == MigrationJobStatus.completed


# ---------------------------------------------------------------------------
# 3. The operator's entry for the port
# ---------------------------------------------------------------------------

#: A sub-interface pasted without the stanza of its port: the config
#: names the port nowhere but in the unit.
_IOS_UNIT_ALONE = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "interface GigabitEthernet0/0/1.54", " encapsulation dot1Q 54",
    " ip address 10.54.0.1 255.255.255.0", "!",
    "interface GigabitEthernet0/0/2", " ip address 10.2.0.1 255.255.255.0", "!", "end", "",
])


class TestTheOperatorsEntryForThePort:
    """Between two configs of one codec a unit stands with every other
    name -- until an entry moves or drops its port.  It used to stay
    on the port's OLD name, or bring a dropped port back."""

    def test_a_unit_follows_a_port_that_moved(self) -> None:
        junos = get_codec("juniper_junos")
        job = run_plan_with_overrides(
            junos, junos, _UNITS["juniper_junos"][1], port_rename_map={"ge-0/0/1": "ge-0/0/7"},
        )
        assert job.port_renames == {
            "ge-0/0/1": "ge-0/0/7", "ge-0/0/1.54": "ge-0/0/7.54", "ge-0/0/1.55": "ge-0/0/7.55",
        }
        assert "set interfaces ge-0/0/7 unit 54 vlan-id 300" in job.rendered
        assert "set interfaces ge-0/0/7 unit 54 family inet address 10.54.0.1/24" in job.rendered
        assert "ge-0/0/1" not in job.rendered

    @pytest.mark.parametrize("target_name", ["juniper_junos", "arista_eos"])
    def test_a_unit_goes_with_a_dropped_port(self, target_name: str) -> None:
        junos = get_codec("juniper_junos")
        job = run_plan_with_overrides(
            junos, get_codec(target_name), _UNITS["juniper_junos"][1],
            port_rename_map={"ge-0/0/1": None},
        )
        assert job.port_drops == ["ge-0/0/1", "ge-0/0/1.54", "ge-0/0/1.55"]
        assert "10.54.0.1" not in job.rendered and "10.55.0.1" not in job.rendered
        assert "ge-0/0/1" not in job.rendered and "10.2.0.1" in job.rendered
        assert (
            "port_rename: 'ge-0/0/1.54' is a unit of 'ge-0/0/1', which is not "
            "in the output; dropped with it"
        ) in job.warnings

    def test_an_entry_for_the_unit_itself_wins(self) -> None:
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        job = run_plan_with_overrides(
            junos, eos, _UNITS["juniper_junos"][1],
            port_rename_map={"ge-0/0/1": None, "ge-0/0/1.54": "Ethernet9.54"},
        )
        assert job.port_renames["ge-0/0/1.54"] == "Ethernet9.54"
        assert "interface Ethernet9.54" in job.rendered
        assert job.port_drops == ["ge-0/0/1", "ge-0/0/1.55"]

    def test_it_follows_an_entry_across_vendors(self) -> None:
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        job = run_plan_with_overrides(
            junos, eos, _UNITS["juniper_junos"][1], port_rename_map={"ge-0/0/1": "Ethernet7"},
        )
        assert job.port_renames["ge-0/0/1.54"] == "Ethernet7.54"
        assert job.port_renames["ge-0/0/1.55"] == "Ethernet7.55"

    def test_a_port_named_only_through_its_unit(self) -> None:
        """An entry for it moves the unit, is not reported as naming
        a port the config does not have, and no rename of the port
        itself is claimed: it has no line to rename."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_overrides(
            ios, ios, _IOS_UNIT_ALONE,
            port_rename_map={"GigabitEthernet0/0/1": "GigabitEthernet0/0/7"},
        )
        assert job.port_renames == {"GigabitEthernet0/0/1.54": "GigabitEthernet0/0/7.54"}
        assert "interface GigabitEthernet0/0/7.54" in job.rendered
        assert not [w for w in job.warnings if "does not exist in the parsed config" in w]
        job = run_plan_with_overrides(
            ios, ios, _IOS_UNIT_ALONE, port_rename_map={"GigabitEthernet0/0/1": None},
        )
        assert job.port_drops == ["GigabitEthernet0/0/1.54"]
        assert not [w for w in job.warnings if "does not exist in the parsed config" in w]
        job = run_plan_with_overrides(ios, get_codec("juniper_junos"), _IOS_UNIT_ALONE, port_rename_map={})
        assert job.port_renames == {
            "GigabitEthernet0/0/1.54": "ge-0/0/1.54", "GigabitEthernet0/0/2": "ge-0/0/2",
        }
        assert "set interfaces ge-0/0/1 unit 54 vlan-id 54" in job.rendered

    def test_an_entry_for_no_port_is_still_said(self) -> None:
        """Only a port a unit was sent after is spared the line."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_overrides(
            ios, ios, _IOS_UNIT_ALONE, port_rename_map={"GigabitEthernet0/0/9": "GigabitEthernet0/0/7"},
        )
        assert job.port_renames == {}
        assert (
            "port_rename: source port 'GigabitEthernet0/0/9' does not exist in "
            "the parsed config; entry ignored"
        ) in job.warnings


# ---------------------------------------------------------------------------
# 4. What is, and what is not, a unit of a port
# ---------------------------------------------------------------------------

#: A FortiOS VLAN interface an operator NAMED like a unit of its port.
_FORTIOS_NAMED_LIKE_A_UNIT = """config system interface
    edit "port1"
        set ip 10.1.1.1 255.255.255.0
        set type physical
    next
    edit "port2"
        set ip 10.2.2.1 255.255.255.0
        set type physical
    next
    edit "port1.55"
        set ip 10.55.0.1 255.255.255.0
        set interface "port1"
        set vlanid 55
    next
end
"""

#: A RouterOS VLAN interface named after its parent, which the RouterOS
#: classifier reads as a VLAN interface and not as a port.
_ROUTEROS_NAMED_AFTER_A_PORT = """/interface ethernet
set [ find default-name=ether1 ] comment="a"
set [ find default-name=ether2 ] comment="b"
/interface vlan
add interface=ether1 name=ether1.55 vlan-id=55
/ip address
add address=10.1.0.1/24 interface=ether1
add address=10.55.0.1/24 interface=ether1.55
add address=10.2.0.1/24 interface=ether2
"""

#: Junos names that end in a unit and are not a sub-interface of a
#: port: a reference to unit 0 (which is the interface itself on every
#: other platform), a unit of a loopback -- and one that is, on a LAG.
_JUNOS_OTHER_UNITS = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24 vrrp-group 1 virtual-address 10.1.0.254",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24 vrrp-group 1 track interface ge-0/0/2.0",
    "set interfaces ge-0/0/2 unit 0 family inet address 10.2.0.1/24",
    "set interfaces ge-0/0/3 ether-options 802.3ad ae0",
    "set interfaces ae0 unit 100 vlan-id 100",
    "set interfaces ae0 unit 100 family inet address 10.100.0.1/24",
    "set interfaces lo0 unit 0 family inet address 192.0.2.1/32",
    "set interfaces lo0 unit 2 family inet address 192.0.2.2/32",
    "",
])

#: An EOS lane of a broken-out cage with a sub-interface.
_EOS_UNIT_OF_A_LANE = "\n".join([
    "! device: r1 (DCS-7050CX3-32S, EOS-4.27.0F)", "!", "hostname r1", "!",
    "interface Ethernet49/1", "   no switchport", "!",
    "interface Ethernet49/1.100", "   encapsulation dot1q vlan 100", "   ip address 10.100.0.1/24", "!",
    "interface Ethernet2", "   no switchport", "   ip address 10.2.0.1/24", "!", "end", "",
])


class TestWhatIsAUnit:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("ge-0/0/1.54", ("ge-0/0/1", "54")),
            ("xe-0/0/6:2.10", ("xe-0/0/6:2", "10")),
            ("a.1.2", ("a.1", "2")),
            ("ether1.backup", None),
            ("ether1", None),
            ("ether1.", None),
            (".54", None),
            ("ether1.-5", None),
            # Digits of another script are digits to ``str.isdigit``.
            ("ether1.\u0665", None),
            # Given as written, however long and whatever its zeros.
            ("ge-0/0/1.00", ("ge-0/0/1", "00")),
            ("ge-0/0/1." + "7" * 4301, ("ge-0/0/1", "7" * 4301)),
        ],
    )
    def test_a_unit_suffix_is_a_number(self, name: str, expected) -> None:
        assert split_unit(name) == expected

    def test_the_kinds_of_port_that_have_them(self) -> None:
        assert sorted(UNIT_PARENT_KINDS) == ["breakout", "lag", "physical"]

    def test_a_vlan_interface_named_like_a_unit(self) -> None:
        """FortiOS names VLAN interfaces freely.  ``port1.55`` there is
        what an operator typed, bound to its port by a line of its own,
        and it is left as it was: across vendors under its name, and
        between two FortiOS configs when its port is renamed."""
        forti, eos = get_codec("fortigate_cli"), get_codec("arista_eos")
        job = run_plan_with_overrides(forti, eos, _FORTIOS_NAMED_LIKE_A_UNIT, port_rename_map={})
        assert job.port_renames == {"port1": "Ethernet1", "port2": "Ethernet2"}
        assert "interface port1.55" in job.rendered
        job = run_plan_with_overrides(
            forti, forti, _FORTIOS_NAMED_LIKE_A_UNIT, port_rename_map={"port1": "port9"},
        )
        assert job.port_renames == {"port1": "port9"}
        assert 'edit "port1.55"' in job.rendered and 'set interface "port9"' in job.rendered

    def test_a_name_read_as_another_thing(self) -> None:
        """RouterOS reads ``ether1.55`` as a VLAN interface: a thing of
        its own, with a form of its own on every target."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        assert mikrotik.classify_port_name("ether1.55").kind == "svi"
        job = run_plan_with_overrides(mikrotik, eos, _ROUTEROS_NAMED_AFTER_A_PORT, port_rename_map={})
        assert job.port_renames["ether1"] == "Ethernet1"
        assert job.port_renames["ether1.55"] == "Vlan55"
        job = run_plan_with_overrides(
            mikrotik, mikrotik, _ROUTEROS_NAMED_AFTER_A_PORT, port_rename_map={"ether1": "wan"},
        )
        assert job.port_renames == {"ether1": "wan"}
        assert "add address=10.55.0.1/24 interface=ether1.55" in job.rendered

    def test_the_classifier_alone_decides(self) -> None:
        """The RouterOS parser also TYPES that interface as a VLAN
        interface.  The OPNsense parser types none, and ``igb1.54`` is
        a VLAN interface there all the same: its classifier says so."""
        opnsense, eos = get_codec("opnsense"), get_codec("arista_eos")
        assert opnsense.classify_port_name("igb1.54").kind == "svi"
        tree = CanonicalIntent.model_validate({
            "interfaces": [{"name": "igb1"}, {"name": "igb1.54"}],
        })
        result = translate_port_names(tree, opnsense, eos, rename_map={})
        assert result.applied == {"igb1": "Ethernet1", "igb1.54": "Vlan54"}

    @pytest.mark.parametrize("vlan_type", ["ianaift:l3ipvlan", "ianaift:l2vlan"])
    def test_an_interface_typed_as_a_vlan(self, vlan_type: str) -> None:
        """Whatever its name looks like, and whichever of the two
        VLAN interface types its parser gave it."""
        forti, eos = get_codec("fortigate_cli"), get_codec("arista_eos")
        tree = CanonicalIntent.model_validate({
            "interfaces": [
                {"name": "port1"}, {"name": "port1.55", "interface_type": vlan_type},
            ],
        })
        result = translate_port_names(tree, forti, eos, rename_map={})
        assert result.applied == {"port1": "Ethernet1"}
        assert [iface.name for iface in tree.interfaces] == ["Ethernet1", "port1.55"]

    def test_a_reference_to_unit_0_is_the_port(self) -> None:
        """Junos writes ``ge-0/0/2.0`` where it means the interface.
        It has no interface of its own in the tree, and onto another
        vendor it is the port -- not a sub-interface numbered 0."""
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        tree = junos.parse(_JUNOS_OTHER_UNITS)
        assert "ge-0/0/2.0" not in {iface.name for iface in tree.interfaces}
        job = run_plan_with_overrides(junos, eos, _JUNOS_OTHER_UNITS, port_rename_map={})
        assert job.port_renames["ge-0/0/2.0"] == job.port_renames["ge-0/0/2"] == "Ethernet2"
        assert "vrrp 1 track Ethernet2" in job.rendered
        assert "Ethernet2.0" not in job.rendered

    def test_between_junos_configs_it_follows(self) -> None:
        junos = get_codec("juniper_junos")
        job = run_plan_with_overrides(
            junos, junos, _JUNOS_OTHER_UNITS,
            port_rename_map={"ge-0/0/2": "ge-0/0/9", "ae0": "ae5", "lo0": "lo1"},
        )
        assert job.port_renames == {
            "ge-0/0/2": "ge-0/0/9", "ge-0/0/2.0": "ge-0/0/9.0",
            "ae0": "ae5", "ae0.100": "ae5.100", "lo0": "lo1", "lo0.2": "lo1.2",
        }
        assert "track interface ge-0/0/9.0" in job.rendered

    def test_a_unit_of_a_lag_follows_the_lag(self) -> None:
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        job = run_plan_with_overrides(junos, eos, _JUNOS_OTHER_UNITS, port_rename_map={})
        lag = job.port_renames["ae0"]
        assert job.port_renames["ae0.100"] == f"{lag}.100"
        (iface,) = _holders(eos.parse(job.rendered), "10.100.0.1")
        assert (iface.name, iface.dot1q_vlan) == (f"{lag}.100", 100)

    def test_a_unit_of_a_lane_follows_the_lane(self) -> None:
        """Renamed where the target has a name for the lane, and
        dropped with it where it has none."""
        eos = get_codec("arista_eos")
        assert eos.classify_port_name("Ethernet49/1").kind == "breakout"
        job = run_plan_with_overrides(
            eos, get_codec("cisco_iosxe_cli"), _EOS_UNIT_OF_A_LANE, port_rename_map={},
        )
        lane = job.port_renames["Ethernet49/1"]
        assert job.port_renames["Ethernet49/1.100"] == f"{lane}.100"
        job = run_plan_with_overrides(
            eos, get_codec("juniper_junos"), _EOS_UNIT_OF_A_LANE, port_rename_map={},
        )
        assert job.port_drops == ["Ethernet49/1", "Ethernet49/1.100"]
        assert "10.100.0.1" not in job.rendered

    def test_a_loopback_unit_is_not_followed(self) -> None:
        """No other platform has a sub-interface of a loopback, so
        ``Loopback0.2`` would be a name of nothing.  A unit of lo0 is
        a loopback of its own, with the unit's number (see
        ``test_a_loopback_is_a_unit_of_lo0.py``), and not on the
        loopback itself."""
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        job = run_plan_with_overrides(junos, eos, _JUNOS_OTHER_UNITS, port_rename_map={})
        assert job.port_renames["lo0"] == "Loopback0"
        assert job.port_renames["lo0.2"] == "Loopback2"
        assert not [
            w for w in job.warnings
            if "multiple source ports map to 'Loopback" in w
        ]

    def test_a_unit_with_no_interface_record(self) -> None:
        """Across vendors only a name that IS an interface is taken
        for a sub-interface; one a VLAN merely lists is read by its
        classifier, as it was."""
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        tree = CanonicalIntent.model_validate({
            "interfaces": [{"name": "ge-0/0/1"}],
            "vlans": [{"id": 10, "tagged_ports": ["ge-0/0/1.54"]}],
        })
        result = translate_port_names(tree, junos, eos, rename_map={})
        assert result.applied == {"ge-0/0/1": "Ethernet1", "ge-0/0/1.54": "Ethernet1"}
        tree = CanonicalIntent.model_validate({
            "interfaces": [{"name": "ge-0/0/1"}, {"name": "ge-0/0/1.54"}],
            "vlans": [{"id": 10, "tagged_ports": ["ge-0/0/1.54"]}],
        })
        result = translate_port_names(tree, junos, eos, rename_map={})
        assert result.applied == {"ge-0/0/1": "Ethernet1", "ge-0/0/1.54": "Ethernet1.54"}
        assert tree.vlans[0].tagged_ports == ["Ethernet1.54"]


# ---------------------------------------------------------------------------
# 5. A unit and its port, spelt in two letter cases
# ---------------------------------------------------------------------------

#: A unit typed in another letter case than its port.  IOS names have
#: no letter case, so it is a unit of that port.
_IOS_UNIT_IN_ANOTHER_CASE = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "interface GigabitEthernet0/0/1", " description PARENT", " no ip address", "!",
    "interface gigabitethernet0/0/1.54", " encapsulation dot1Q 54",
    " ip address 10.54.0.1 255.255.255.0", "!",
    "interface GigabitEthernet0/0/2", " ip address 10.2.0.1 255.255.255.0", "!", "end", "",
])


class TestAUnitSpeltInAnotherCase:
    """The port of ``gigabitethernet0/0/1.54`` was looked up as the
    exact string before the dot.  An entry for ``GigabitEthernet0/0/1``
    then moved the port and left its unit on the OLD name, and one
    that dropped the port left the unit to bring it back -- with
    nothing said."""

    @pytest.mark.parametrize(
        ("target_name", "moved_to"),
        [("cisco_iosxe_cli", "GigabitEthernet0/0/7"), ("juniper_junos", "ge-0/0/7")],
    )
    def test_it_follows_a_port_that_moved(self, target_name: str, moved_to: str) -> None:
        ios, target = get_codec("cisco_iosxe_cli"), get_codec(target_name)
        assert not ios.port_names_case_sensitive
        job = run_plan_with_overrides(
            ios, target, _IOS_UNIT_IN_ANOTHER_CASE,
            port_rename_map={"GigabitEthernet0/0/1": moved_to},
        )
        assert job.port_renames["gigabitethernet0/0/1.54"] == f"{moved_to}.54"
        out = target.parse(job.rendered)
        (iface,) = _holders(out, "10.54.0.1")
        assert iface.name == f"{moved_to}.54"
        other = job.port_renames.get("GigabitEthernet0/0/2", "GigabitEthernet0/0/2")
        assert {i.name for i in out.interfaces} == {moved_to, f"{moved_to}.54", other}

    @pytest.mark.parametrize("target_name", ["cisco_iosxe_cli", "juniper_junos"])
    def test_it_goes_with_a_dropped_port(self, target_name: str) -> None:
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_overrides(
            ios, get_codec(target_name), _IOS_UNIT_IN_ANOTHER_CASE,
            port_rename_map={"GigabitEthernet0/0/1": None},
        )
        assert job.port_drops == ["GigabitEthernet0/0/1", "gigabitethernet0/0/1.54"]
        assert "10.54.0.1" not in job.rendered and "10.2.0.1" in job.rendered
        assert (
            "port_rename: 'gigabitethernet0/0/1.54' is a unit of "
            "'GigabitEthernet0/0/1', which is not in the output; dropped with it"
        ) in job.warnings

    def test_with_no_entry_it_stands_as_spelt(self) -> None:
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_overrides(ios, ios, _IOS_UNIT_IN_ANOTHER_CASE, port_rename_map={})
        assert job.port_renames == {} and "interface gigabitethernet0/0/1.54" in job.rendered

    def test_a_port_key_in_another_case_counts(self) -> None:
        """The config names the port nowhere but in the unit, and the
        entry spells it another way: it is still that port's entry, and
        is not reported as naming a port the config does not have."""
        ios, junos = get_codec("cisco_iosxe_cli"), get_codec("juniper_junos")
        job = run_plan_with_overrides(
            ios, junos, _IOS_UNIT_ALONE, port_rename_map={"gigabitethernet0/0/1": "ge-0/0/9"},
        )
        assert job.port_renames["GigabitEthernet0/0/1.54"] == "ge-0/0/9.54"
        assert not [w for w in job.warnings if "does not exist in the parsed config" in w]

    @pytest.mark.parametrize("target_name", ["cisco_iosxe_cli", "juniper_junos"])
    def test_it_goes_with_an_absent_port_too(self, target_name: str) -> None:
        """The config names the port nowhere but in the unit, the
        unit spells it another way than the entry does, and the
        entry DROPS the port.  A drop is an entry like any other:
        its key says which port is meant, the unit goes with it,
        and the entry is not reported as naming a port the config
        does not have."""
        ios = get_codec("cisco_iosxe_cli")
        text = _IOS_UNIT_ALONE.replace(
            "interface GigabitEthernet0/0/1.54", "interface gigabitethernet0/0/1.54",
        )
        assert "interface gigabitethernet0/0/1.54" in text
        job = run_plan_with_overrides(
            ios, get_codec(target_name), text, port_rename_map={"GigabitEthernet0/0/1": None},
        )
        assert job.port_drops == ["gigabitethernet0/0/1.54"]
        assert "10.54.0.1" not in job.rendered and "10.2.0.1" in job.rendered
        assert (
            "port_rename: 'gigabitethernet0/0/1.54' is a unit of "
            "'GigabitEthernet0/0/1', which is not in the output; dropped with it"
        ) in job.warnings
        assert not [w for w in job.warnings if "does not exist in the parsed config" in w]

    def test_a_spelling_in_use_is_not_laid_over(self) -> None:
        """Two spellings of the port in the config itself, and the
        unit under one of them.  The entry is for the other: nothing
        says the unit's own port is not the one it names, so it
        stands with it -- and the job says the two spellings do not
        end together."""
        ios = get_codec("cisco_iosxe_cli")
        tree = CanonicalIntent.model_validate({"interfaces": [
            {"name": "GigabitEthernet0/0/1"}, {"name": "gigabitethernet0/0/1"},
            {"name": "gigabitethernet0/0/1.54"},
        ]})
        result = translate_port_names(
            tree, ios, ios, rename_map={"GigabitEthernet0/0/1": "GigabitEthernet0/0/7"},
        )
        assert result.applied == {"GigabitEthernet0/0/1": "GigabitEthernet0/0/7"}
        assert [w for w in result.warnings if "do not end together" in w]

    def test_it_goes_where_the_configs_port_goes(self) -> None:
        """An entry under each spelling of the port.  The port is the
        one the config names, and goes where its entry says; the
        unit goes there with it, whichever spelling it uses.  The
        other entry is a second spelling of a name that has an
        entry, and is said to be ignored -- it used to take the
        unit, to another port than its own."""
        ios = get_codec("cisco_iosxe_cli")
        tree = CanonicalIntent.model_validate({"interfaces": [
            {"name": "GigabitEthernet0/0/1"}, {"name": "gigabitethernet0/0/1.54"},
        ]})
        result = translate_port_names(tree, ios, ios, rename_map={
            "GigabitEthernet0/0/1": "GigabitEthernet0/0/7",
            "gigabitethernet0/0/1": "GigabitEthernet0/0/8",
        })
        assert result.applied == {
            "GigabitEthernet0/0/1": "GigabitEthernet0/0/7",
            "gigabitethernet0/0/1.54": "GigabitEthernet0/0/7.54",
        }
        assert (
            "port_rename: source port 'gigabitethernet0/0/1' is another spelling "
            "of 'GigabitEthernet0/0/1', which has an entry of its own; entry ignored"
        ) in result.warnings

    def test_it_is_not_guessed_between_two_keys(self) -> None:
        """The port is in the map twice, in two cases, and nowhere in
        the config: neither entry is taken for the unit."""
        ios = get_codec("cisco_iosxe_cli")
        tree = CanonicalIntent.model_validate({"interfaces": [
            {"name": "gigabitethernet0/0/1.54"}, {"name": "GigabitEthernet0/0/2"},
        ]})
        result = translate_port_names(tree, ios, ios, rename_map={
            "GigabitEthernet0/0/1": "GigabitEthernet0/0/7",
            "GIGABITETHERNET0/0/1": "GigabitEthernet0/0/8",
        })
        assert result.applied == {}
        assert len([w for w in result.warnings if "does not exist in the parsed config" in w]) == 2

    def test_where_names_have_case_it_is_no_unit(self) -> None:
        """On FortiOS ``PORT1`` and ``port1`` are two interfaces, and
        ``PORT1.66`` is no unit of ``port1`` -- whether ``port1`` is
        a name of the config, or only a key of the map."""
        forti = get_codec("fortigate_cli")
        assert forti.port_names_case_sensitive
        tree = CanonicalIntent.model_validate({
            "interfaces": [{"name": "port1"}, {"name": "PORT1.66"}],
        })
        result = translate_port_names(tree, forti, forti, rename_map={"port1": "port9"})
        assert result.applied == {"port1": "port9"}
        assert [iface.name for iface in tree.interfaces] == ["port9", "PORT1.66"]
        tree = CanonicalIntent.model_validate({"interfaces": [{"name": "PORT1.66"}]})
        result = translate_port_names(tree, forti, forti, rename_map={"port1": "port9"})
        assert result.applied == {} and tree.interfaces[0].name == "PORT1.66"
        assert [w for w in result.warnings if "does not exist in the parsed config" in w]


# ---------------------------------------------------------------------------
# 6. Units that are not sent after their port, across vendors
# ---------------------------------------------------------------------------

#: A sub-interface numbered 0.  No running-config prints one; a hand does.
_IOS_UNIT_0 = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "interface GigabitEthernet0/0/1", " ip address 10.1.0.1 255.255.255.0", "!",
    "interface GigabitEthernet0/0/1.0", " encapsulation dot1Q 5",
    " ip address 10.54.0.1 255.255.255.0", "!",
    "interface GigabitEthernet0/0/2", " ip address 10.2.0.1 255.255.255.0", "!", "end", "",
])

#: A Catalyst whose management port is told from an ordinary one only
#: by its VRF, with a sub-interface -- beside a data port with one.
_IOS_MGMT_BY_VRF = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "vrf definition Mgmt-vrf", " address-family ipv4", " exit-address-family", "!",
    "interface GigabitEthernet0/0", " vrf forwarding Mgmt-vrf",
    " ip address 192.168.0.1 255.255.255.0", "!",
    "interface GigabitEthernet0/0.10", " encapsulation dot1Q 10",
    " ip address 10.10.0.1 255.255.255.0", "!",
    "interface GigabitEthernet1/0/1", " no switchport", " ip address 10.1.0.1 255.255.255.0", "!",
    "interface GigabitEthernet1/0/1.20", " encapsulation dot1Q 20",
    " ip address 10.20.0.1 255.255.255.0", "!", "end", "",
])

#: An EOS management port with a sub-interface, beside a data port with one.
_EOS_MGMT_BY_NAME = "\n".join([
    "! device: r1 (DCS-7050SX-64, EOS-4.27.0F)", "!", "hostname r1", "!",
    "interface Management1", "   ip address 192.168.0.1/24", "!",
    "interface Management1.5", "   encapsulation dot1q vlan 5", "   ip address 10.5.0.1/24", "!",
    "interface Ethernet2", "   no switchport", "   ip address 10.2.0.1/24", "!",
    "interface Ethernet2.7", "   encapsulation dot1q vlan 7", "   ip address 10.7.0.1/24", "!",
    "end", "",
])


class TestUnitsLeftToTheClassifier:
    @pytest.mark.parametrize("zeros", ["0", "00", "000"])
    def test_a_unit_numbered_0_across_vendors(self, zeros: str) -> None:
        """Unit 0 is the interface itself wherever there is one.  Sent
        after its port, ``Gi0/0/1.0`` was written as unit 0 of
        ``ge-0/0/1`` on Junos: the port's own address and the unit's
        on one interface, in a job that said nothing.  It is left to
        the classifier, which does not know it and says so.  However
        many zeros it is written with: ``.00`` is unit 0 as well,
        and Junos would write it ``unit 00`` of the same port."""
        ios, junos = get_codec("cisco_iosxe_cli"), get_codec("juniper_junos")
        name = f"GigabitEthernet0/0/1.{zeros}"
        text = _IOS_UNIT_0.replace("GigabitEthernet0/0/1.0", name)
        job = run_plan_with_overrides(ios, junos, text, port_rename_map={})
        assert name not in job.port_renames
        assert (
            f"cisco_iosxe_cli: could not classify port name {name!r}; left verbatim"
        ) in job.warnings
        out = junos.parse(job.rendered)
        (port,) = _holders(out, "10.1.0.1")
        (unit,) = _holders(out, "10.54.0.1")
        assert port.name == "ge-0/0/1" and unit.name != port.name

    def test_one_codec_on_both_sides_0_is_a_unit(self) -> None:
        """There it means on both sides what it meant on one."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_overrides(
            ios, ios, _IOS_UNIT_0,
            port_rename_map={"GigabitEthernet0/0/1": "GigabitEthernet0/0/7"},
        )
        assert job.port_renames["GigabitEthernet0/0/1.0"] == "GigabitEthernet0/0/7.0"

    @pytest.mark.parametrize("target_name", ["juniper_junos", "cisco_iosxe_cli", "aruba_aoss"])
    def test_a_management_port_by_its_name(self, target_name: str) -> None:
        """EOS ``Management1.5``.  A management port has another form
        on every platform, or none (``oobm`` is a block on AOS-S), and
        no unit of one is a sub-interface there.  The data port's unit
        beside it follows."""
        eos, target = get_codec("arista_eos"), get_codec(target_name)
        assert eos.classify_port_name("Management1").kind == "mgmt"
        job = run_plan_with_overrides(eos, target, _EOS_MGMT_BY_NAME, port_rename_map={})
        assert "Management1.5" not in job.port_renames
        assert "Management1.5" not in job.port_drops
        assert (
            "arista_eos: could not classify port name 'Management1.5'; left verbatim"
        ) in job.warnings
        assert job.port_renames["Ethernet2.7"] == job.port_renames["Ethernet2"] + ".7"

    @pytest.mark.parametrize("target_name", ["juniper_junos", "arista_eos", "aruba_aoss"])
    def test_a_management_port_by_its_vrf(self, target_name: str) -> None:
        """The Catalyst port in ``Mgmt-vrf``: its name reads as any
        other port's, and its parser marks it from context.  Its unit
        was sent after it all the same -- ``oobm.10`` on AOS-S,
        ``em0.10`` on Junos, ``Management1.10`` on EOS -- because the
        rule asked the name."""
        ios, target = get_codec("cisco_iosxe_cli"), get_codec(target_name)
        assert ios.classify_port_name("GigabitEthernet0/0").kind == "physical"
        kinds = {iface.name: iface.kind for iface in ios.parse(_IOS_MGMT_BY_VRF).interfaces}
        assert kinds["GigabitEthernet0/0"] == "mgmt" and kinds["GigabitEthernet1/0/1"] == ""
        job = run_plan_with_overrides(ios, target, _IOS_MGMT_BY_VRF, port_rename_map={})
        assert "GigabitEthernet0/0.10" not in job.port_renames
        assert (
            "cisco_iosxe_cli: could not classify port name "
            "'GigabitEthernet0/0.10'; left verbatim"
        ) in job.warnings
        assert job.port_renames["GigabitEthernet1/0/1.20"] == (
            job.port_renames["GigabitEthernet1/0/1"] + ".20"
        )

    def test_a_management_port_in_another_case(self) -> None:
        """What the parser read of the port is recorded under the
        name the config gives it.  A unit that spells the port
        another way is looked up by that name, not by its own
        spelling -- under which the port would be an ordinary one,
        and the unit sent after it to ``em0.10``."""
        ios, junos = get_codec("cisco_iosxe_cli"), get_codec("juniper_junos")
        text = _IOS_MGMT_BY_VRF.replace(
            "interface GigabitEthernet0/0.10", "interface gigabitethernet0/0.10",
        )
        job = run_plan_with_overrides(ios, junos, text, port_rename_map={})
        assert job.port_renames["GigabitEthernet0/0"] == "em0"
        assert "gigabitethernet0/0.10" not in job.port_renames
        assert (
            "cisco_iosxe_cli: could not classify port name "
            "'gigabitethernet0/0.10'; left verbatim"
        ) in job.warnings

    def test_one_codec_it_follows_an_entry_still(self) -> None:
        """What kind of port it is is asked across vendors only."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_overrides(
            ios, ios, _IOS_MGMT_BY_VRF,
            port_rename_map={"GigabitEthernet0/0": "GigabitEthernet0/1"},
        )
        assert job.port_renames == {
            "GigabitEthernet0/0": "GigabitEthernet0/1",
            "GigabitEthernet0/0.10": "GigabitEthernet0/1.10",
        }


#: More digits than Python turns into an integer (4,300).
_TOO_MANY_DIGITS = ("7" * 4301, "0" * 4301)


class TestAUnitOfTooManyDigits:
    """A pasted config can write any run of digits after a dot.  A
    rule that makes a number of the unit, to ask whether it is unit
    0, fails the job: Python refuses to convert more than 4,300
    digits.  The same config completes while such a name is left to
    the classifier, so the unit is read as text.  And across
    vendors a name that ends in more digits than a unit has is not
    sent after its port: there it would reach the FortiOS and VyOS
    renderers as ``<port>.<digits>``, which both make a VLAN id
    of."""

    @pytest.mark.parametrize("digits", _TOO_MANY_DIGITS, ids=["sevens", "zeros"])
    @pytest.mark.parametrize("target_name", list_public_codecs())
    def test_a_run_of_digits_fails_no_job(self, target_name: str, digits: str) -> None:
        """Onto every target.  Where the bare pipeline -- parse and
        render, no translator -- gets through, so does the job, and
        the name is neither renamed nor dropped.  (Its own renderer
        fails on such a name whoever hands it over: IOS-XE sorts
        interfaces by the numbers in their names.)"""
        ios, target = get_codec("cisco_iosxe_cli"), get_codec(target_name)
        name = f"GigabitEthernet0/0/1.{digits}"
        text = _IOS_UNIT_0.replace("GigabitEthernet0/0/1.0", name)
        bare = run_plan(ios, target, text)
        job = run_plan_with_overrides(ios, target, text, port_rename_map={})
        if bare.status != MigrationJobStatus.failed:
            assert job.status != MigrationJobStatus.failed, job.error
        assert name not in job.port_renames and name not in job.port_drops

    @pytest.mark.parametrize("target_name", ["arista_eos", "juniper_junos"])
    def test_it_is_a_name_nobody_could_read(self, target_name: str) -> None:
        """The job completes and says of the name what it says of
        any name its classifier does not know."""
        ios, target = get_codec("cisco_iosxe_cli"), get_codec(target_name)
        name = "GigabitEthernet0/0/1." + _TOO_MANY_DIGITS[0]
        text = _IOS_UNIT_0.replace("GigabitEthernet0/0/1.0", name)
        job = run_plan_with_overrides(ios, target, text, port_rename_map={})
        assert job.status == MigrationJobStatus.completed
        assert (
            f"cisco_iosxe_cli: could not classify port name {name!r}; left verbatim"
        ) in job.warnings
        assert name in job.rendered and "10.54.0.1" in job.rendered

    @pytest.mark.parametrize("target_name", ["arista_eos", "juniper_junos"])
    def test_it_is_never_made_a_number(self, monkeypatch, target_name: str) -> None:
        """The bound says what a unit is.  It is not what keeps the
        job alive: with the bound lifted, a unit of any length goes
        with its port like every other unit, and is still only ever
        read as text."""
        monkeypatch.setattr(translator, "UNIT_MAX_DIGITS", 10_000)
        ios, target = get_codec("cisco_iosxe_cli"), get_codec(target_name)
        digits = _TOO_MANY_DIGITS[0]
        name = f"GigabitEthernet0/0/1.{digits}"
        text = _IOS_UNIT_0.replace("GigabitEthernet0/0/1.0", name)
        job = run_plan_with_overrides(ios, target, text, port_rename_map={})
        assert job.status == MigrationJobStatus.completed, job.error
        assert job.port_renames[name] == (
            job.port_renames["GigabitEthernet0/0/1"] + "." + digits
        )

    def test_ten_digits_are_a_unit_eleven_not(self) -> None:
        ios, eos = get_codec("cisco_iosxe_cli"), get_codec("arista_eos")
        for digits, followed in (("4294967295", True), ("42949672950", False)):
            name = f"GigabitEthernet0/0/1.{digits}"
            text = _IOS_UNIT_0.replace("GigabitEthernet0/0/1.0", name)
            job = run_plan_with_overrides(ios, eos, text, port_rename_map={})
            assert job.port_renames.get(name) == (
                f"Ethernet1.{digits}" if followed else None
            )

    @pytest.mark.parametrize("digits", _TOO_MANY_DIGITS, ids=["sevens", "zeros"])
    def test_within_one_codec_it_follows_still(self, digits: str) -> None:
        """Between two configs of one codec the name is the same on
        both sides, whatever its length and whatever it is numbered:
        an entry for the port moves it, or drops it, with the port.
        Left behind it would bring the port's old name back."""
        junos = get_codec("juniper_junos")
        name = f"ge-0/0/1.{digits}"
        tree = CanonicalIntent.model_validate({"interfaces": [{"name": "ge-0/0/1"}, {"name": name}]})
        result = translate_port_names(tree, junos, junos, rename_map={"ge-0/0/1": "ge-0/0/7"})
        assert result.applied == {"ge-0/0/1": "ge-0/0/7", name: f"ge-0/0/7.{digits}"}
        tree = CanonicalIntent.model_validate({"interfaces": [{"name": "ge-0/0/1"}, {"name": name}]})
        result = translate_port_names(tree, junos, junos, rename_map={"ge-0/0/1": None})
        assert result.dropped == ["ge-0/0/1", name] and tree.interfaces == []


# ---------------------------------------------------------------------------
# 7. What the job says of a unit that went
# ---------------------------------------------------------------------------

#: AOS-CX states a sub-interface's tag and its parser reads none.
_AOSCX_UNIT = "\n".join([
    "!Version ArubaOS-CX FL.10.10.1010", "hostname r1", "!",
    "interface 1/1/1", "    no shutdown", "    routing", "    description PARENT",
    "interface 1/1/1.54", "    no shutdown", "    encapsulation dot1q 300",
    "    ip address 10.54.0.1/24",
    "interface 1/1/2", "    no shutdown", "    routing", "    ip address 10.2.0.1/24", "",
])

#: The same in OS10's grammar: stated, and not read.
_OS10_UNIT = "\n".join([
    "! Version 10.5.4.0", "!", "hostname r1", "!",
    "interface ethernet1/1/1", " description PARENT", " no shutdown", " no switchport", "!",
    "interface ethernet1/1/1.54", " no shutdown", " encapsulation dot1q 300",
    " ip address 10.54.0.1/24", "!",
    "interface ethernet1/1/2", " no shutdown", " no switchport", " ip address 10.2.0.1/24", "!", "",
])

#: Junos ports 0 and 1, each with a unit 54.
_JUNOS_TWO_PORTS_ONE_UNIT_EACH = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/0 unit 54 vlan-id 54",
    "set interfaces ge-0/0/0 unit 54 family inet address 10.54.0.1/24",
    "set interfaces ge-0/0/1 unit 54 vlan-id 54",
    "set interfaces ge-0/0/1 unit 54 family inet address 10.154.0.1/24",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24",
    "",
])

_NO_TAG = "with no 802.1Q tag"


class TestAUnitWithNoTag:
    """A unit's tag is not in its name: it travels in the tree.  One
    that went with its port and has none there is written as an
    interface with no VLAN, on a target that would have carried the
    tag -- and no validation line can say so, since there is no tag to
    list.  The stranded name used to be said ("could not classify");
    a unit that follows has to be said too."""

    @pytest.mark.parametrize(
        "target_name", ["arista_eos", "juniper_junos", "vyos", "fortigate_cli"],
    )
    def test_one_warning_says_it_went_untagged(self, target_name: str) -> None:
        aoscx, target = get_codec("aruba_aoscx"), get_codec(target_name)
        tags = {iface.name: iface.dot1q_vlan for iface in aoscx.parse(_AOSCX_UNIT).interfaces}
        assert "encapsulation dot1q 300" in _AOSCX_UNIT and tags["1/1/1.54"] is None, (
            "the AOS-CX parser reads a sub-interface's tag now: this is no "
            "longer a config with a unit that has none"
        )
        job = run_plan_with_overrides(aoscx, target, _AOSCX_UNIT, port_rename_map={})
        where = job.port_renames["1/1/1.54"]
        assert where == job.port_renames["1/1/1"] + ".54"
        (line,) = [w for w in job.warnings if _NO_TAG in w]
        assert line.startswith(
            f"port_rename: '1/1/1.54' went with its port to '{where}' {_NO_TAG}: "
            f"none was read for it from the source config"
        )

    def test_a_unit_whose_config_states_no_tag(self) -> None:
        """Two IOS units that state no ``encapsulation dot1Q``: the
        tree holds no tag for either.  The IOS parser reads a tag
        where one is stated, so "the parser reads none" is not true
        of them; the line gives no cause at all, the same line for
        every one: it says what is known, and what to do.  (The one
        committed IOS capture whose units' tags were not read had
        lost its indentation, and is refused now.)"""
        ios, eos = get_codec("cisco_iosxe_cli"), get_codec("arista_eos")
        text = (
            "hostname r1\n!\ninterface GigabitEthernet0/1\n no ip address\n!\n"
            "interface GigabitEthernet0/1.100\n ip address 192.0.2.1 255.255.255.0\n!\n"
            "interface GigabitEthernet0/1.200\n ip address 198.51.100.1 255.255.255.0\n!\nend\n"
        )
        assert {i.name: i.dot1q_vlan for i in ios.parse(text).interfaces}[
            "GigabitEthernet0/1.100"
        ] is None
        job = run_plan_with_overrides(ios, eos, text, port_rename_map={})
        lines = [w for w in job.warnings if _NO_TAG in w]
        assert [line.split("'")[1] for line in lines] == [
            "GigabitEthernet0/1.100", "GigabitEthernet0/1.200",
        ]
        for line in lines:
            assert "parser" not in line and "states" not in line
            assert line.endswith("look its VLAN id up in the source and set it on the target")

    def test_which_parsers_read_no_unit_tag(self) -> None:
        """The documents name the source platforms whose every
        sub-interface goes without a tag.  This keeps that list
        true: each grammar that names a unit ``<port>.<unit>``,
        with the tag stated, and what its parser makes of it."""
        samples = {
            **_UNITS,
            "aruba_aoscx": ("1/1/1", _AOSCX_UNIT),
            "dell_os10": ("ethernet1/1/1", _OS10_UNIT),
        }
        unread = set()
        for name, (port, text) in samples.items():
            tags = {i.name: i.dot1q_vlan for i in get_codec(name).parse(text).interfaces}
            if tags[f"{port}.54"] is None:
                unread.add(name)
        assert unread == {"aruba_aoscx", "dell_os10"}

    def test_the_line_quotes_the_unit_first(self) -> None:
        """The migrate page reads the first single-quoted token of a
        warning as the source name the warning is about, and draws it
        on that name's row."""
        aoscx, eos = get_codec("aruba_aoscx"), get_codec("arista_eos")
        job = run_plan_with_overrides(aoscx, eos, _AOSCX_UNIT, port_rename_map={})
        (line,) = [w for w in job.warnings if _NO_TAG in w]
        assert line.split("'")[1::2] == ["1/1/1.54", "Ethernet1.54"]

    def test_it_is_said_where_no_name_changes(self) -> None:
        """IOS-XE CLI onto the NETCONF codec: two codecs, one
        grammar.  The unit goes with its port to the name it has
        already, so no rename says it went anywhere -- and it is
        written with no tag all the same, which this line alone
        says."""
        ios, netconf = get_codec("cisco_iosxe_cli"), get_codec("cisco_iosxe")
        text = _UNITS["cisco_iosxe_cli"][1].replace(" encapsulation dot1Q 300\n", "")
        tags = {iface.name: iface.dot1q_vlan for iface in ios.parse(text).interfaces}
        assert tags["GigabitEthernet0/0/1.54"] is None and tags["GigabitEthernet0/0/1.55"] == 55
        job = run_plan_with_overrides(ios, netconf, text, port_rename_map={})
        assert job.rendered and job.port_renames == {}
        (line,) = [w for w in job.warnings if _NO_TAG in w]
        assert line.startswith(
            "port_rename: 'GigabitEthernet0/0/1.54' went with its port to "
            f"'GigabitEthernet0/0/1.54' {_NO_TAG}: "
        )

    def test_a_tagged_unit_is_not_remarked_on(self) -> None:
        ios, eos = get_codec("cisco_iosxe_cli"), get_codec("arista_eos")
        job = run_plan_with_overrides(ios, eos, _UNITS["cisco_iosxe_cli"][1], port_rename_map={})
        assert job.port_renames["GigabitEthernet0/0/1.54"] == "Ethernet1.54"
        assert not [w for w in job.warnings if _NO_TAG in w]

    def test_within_one_codec_it_is_not_said(self) -> None:
        """One grammar on both sides: a unit is written as the tree
        holds it, moved or not, and the line is not said."""
        aoscx = get_codec("aruba_aoscx")
        job = run_plan_with_overrides(
            aoscx, aoscx, _AOSCX_UNIT, port_rename_map={"1/1/1": "1/1/7"},
        )
        assert job.port_renames["1/1/1.54"] == "1/1/7.54"
        assert not [w for w in job.warnings if _NO_TAG in w]

    @pytest.mark.parametrize(
        ("codec_name", "text", "unit"),
        [("aruba_aoscx", _AOSCX_UNIT, "1/1/1.54"), ("dell_os10", _OS10_UNIT, "ethernet1/1/1.54")],
        ids=["aruba_aoscx", "dell_os10"],
    )
    def test_one_codec_loses_an_unread_tag_too(
        self, codec_name: str, text: str, unit: str,
    ) -> None:
        """That nothing is said there is no promise about the tag.
        One the source platform's parser does not read is lost on
        every path -- a job from that platform to itself included,
        as it is by parse and render alone -- and there nothing
        reports it: no warning, no validation line, no status.
        Known, and pinned as it is so that the documents which say
        so stay true; a parser that learns to read the tag has to
        come and take this away."""
        codec = get_codec(codec_name)
        assert "encapsulation dot1q 300" in text
        job = run_plan_with_overrides(codec, codec, text, port_rename_map={})
        assert job.rendered == run_plan(codec, codec, text).rendered
        (written,) = [i for i in codec.parse(job.rendered).interfaces if i.name == unit]
        assert written.dot1q_vlan is None and "encapsulation" not in job.rendered, (
            f"the {codec_name} codec carries a sub-interface's tag now: the "
            f"documents that say it is lost need to change with this test"
        )
        assert job.status == MigrationJobStatus.completed
        assert job.warnings == [] and job.dropped_tier3_sections == []
        listed = [*job.validation.unsupported_paths, *job.validation.lossy_paths]
        assert not [entry.path for entry in listed if "dot1q" in entry.path]

    def test_one_dropped_with_its_port_says_that(self) -> None:
        aoscx, eos = get_codec("aruba_aoscx"), get_codec("arista_eos")
        job = run_plan_with_overrides(aoscx, eos, _AOSCX_UNIT, port_rename_map={"1/1/1": None})
        assert job.port_drops == ["1/1/1", "1/1/1.54"]
        assert not [w for w in job.warnings if _NO_TAG in w]
        assert [w for w in job.warnings if "dropped with it" in w]

    def test_one_the_operator_named_is_theirs(self) -> None:
        aoscx, eos = get_codec("aruba_aoscx"), get_codec("arista_eos")
        job = run_plan_with_overrides(
            aoscx, eos, _AOSCX_UNIT, port_rename_map={"1/1/1.54": "Ethernet9.54"},
        )
        assert job.port_renames["1/1/1.54"] == "Ethernet9.54"
        assert not [w for w in job.warnings if _NO_TAG in w]


class TestWhatTheJobListsOfAUnit:
    def test_two_units_on_one_name_both_named(self) -> None:
        """Junos ports 0 and 1 are both ``port1`` on FortiOS (an older
        fusion, and reported).  Their units 54 are then both
        ``port1.54``, and the line for that name has to name the two
        units -- which it can only do if each unit that followed is
        remembered with where it went."""
        junos, forti = get_codec("juniper_junos"), get_codec("fortigate_cli")
        job = run_plan_with_overrides(junos, forti, _JUNOS_TWO_PORTS_ONE_UNIT_EACH, port_rename_map={})
        assert job.port_renames["ge-0/0/0.54"] == job.port_renames["ge-0/0/1.54"] == "port1.54"
        (line,) = [w for w in job.warnings if "map to 'port1.54'" in w]
        assert "(sources: ge-0/0/0.54, ge-0/0/1.54)" in line

    def test_ending_on_its_own_name_is_no_rename(self) -> None:
        """``port_renames`` holds names that CHANGED.  IOS-XE CLI to
        the NETCONF codec is two codecs and one grammar: the port keeps
        its name, its unit goes where the port goes -- to the name it
        has.  And between two Junos configs an entry that keeps a port
        where it is keeps its units where they are."""
        ios, netconf = get_codec("cisco_iosxe_cli"), get_codec("cisco_iosxe")
        job = run_plan_with_overrides(ios, netconf, _UNITS["cisco_iosxe_cli"][1], port_rename_map={})
        assert job.rendered and job.port_renames == {}
        junos = get_codec("juniper_junos")
        text = _UNITS["juniper_junos"][1]
        job = run_plan_with_overrides(junos, junos, text, port_rename_map={"ge-0/0/1": "ge-0/0/1"})
        assert job.port_renames == {} and job.port_drops == []
        assert job.rendered == run_plan(junos, junos, text).rendered
