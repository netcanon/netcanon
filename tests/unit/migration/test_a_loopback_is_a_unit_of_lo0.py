"""Junos has one loopback, ``lo0``, and a unit of it in each routing instance.

Juniper: "Junos OS follows the IP convention of using lo0 as the
loopback interface's identifier name", "Only unit 0 is permitted as
the master loopback interface" (Junos 13.2, *Configuring the Loopback
Interface*), and "You can configure more than just unit 0 for lo0, but
you must place each additional unit in a separate routing instance"
(*Loopback Interfaces*, Interfaces Fundamentals).

The translator named loopbacks one at a time, and both directions were
wrong, in jobs that said ``completed``:

* **onto Junos** ``Loopback1`` was ``lo1``, an interface Junos does not
  have, and a loopback of a routing instance was ``lo<N>`` too -- the
  EVPN leaf's VTEP source came out as ``vtep-source-interface lo2``.
  Where a loopback goes is a matter of the config's OTHER loopbacks
  and of its routing instance, which no name formatted alone can know:
  the translator now gives the target every loopback at once
  (``CodecBase.place_loopbacks``).  The global table's one loopback is
  ``lo0``, a routing instance's one loopback numbered N is unit N, and
  any other is dropped and listed, so that the job is ``partial``.
* **from Junos** a unit of ``lo0`` was read as ``lo0`` itself, so the
  loopbacks of every routing instance came out on one ``Loopback0``
  (two source names on one, which the job did list).  ``lo0.<N>`` is
  now loopback N.

What is read here is the RENDERED OUTPUT, as text by a reader of this
module's own and with the target's parser, never the translator's own
account.  Which names are loopbacks of the source is read from the
source tree by a pattern typed here, not by asking the classifier.
Each check is handed the defect it is for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.port_names import LoopbackToPlace
from netcanon.migration.codecs.juniper_junos import port_names as junos_names
from netcanon.migration.codecs.juniper_junos.codec import JunosCodec
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan, run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
_SUFFIXES = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}

#: A loopback's name on the platforms whose captures have one, typed
#: here: ``Loopback7``, ``loopback 7``, ``lo0.7``, VyOS and RouterOS
#: ``lo``.  Not the classifiers' reading: the oracle looks for itself.
_A_LOOPBACK = re.compile(r"^(?:loopback ?\d+|lo\d*(?:\.\d+)?)$", re.IGNORECASE)


def _inputs() -> list[tuple[str, Path]]:
    """Every committed capture and kitchen sink, with its codec."""
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


def _with_loopbacks(inputs: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """The inputs whose tree has a loopback by :data:`_A_LOOPBACK`."""
    kept = []
    for codec, path in inputs:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = get_codec(codec).parse(text)
        except Exception:
            continue
        if any(_A_LOOPBACK.match(i.name) for i in tree.interfaces):
            kept.append((codec, path))
    return kept


_LOOPBACK_INPUTS = _with_loopbacks(_inputs())


def _job(source: str, target: str, text: str, port_map: dict | None = None) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map=port_map or {},
    )


# ---------------------------------------------------------------------------
# Reading a Junos output as text
# ---------------------------------------------------------------------------

_SET_INTERFACE = re.compile(r"^set interfaces (?P<device>\S+)(?P<rest>.*)$")
_UNIT_ADDRESS = re.compile(
    r"^ unit (?P<unit>\d+) family inet6? address (?P<address>[0-9A-Fa-f.:]+)/"
)
_BINDING = re.compile(r"^set routing-instances (?P<instance>\S+) interface (?P<name>\S+)$")


def _loopback_devices(text: str) -> set[str]:
    """The devices of every ``set interfaces lo...`` line."""
    devices = set()
    for line in text.splitlines():
        m = _SET_INTERFACE.match(line)
        if m and m.group("device").lower().startswith("lo"):
            devices.add(m.group("device"))
    return devices


def _lo0_units(text: str) -> dict[str, int]:
    """Each address the text puts on a unit of ``lo0``, with the unit."""
    units: dict[str, int] = {}
    for line in text.splitlines():
        m = _SET_INTERFACE.match(line)
        if not m or m.group("device") != "lo0":
            continue
        a = _UNIT_ADDRESS.match(m.group("rest"))
        if a:
            units[a.group("address")] = int(a.group("unit"))
    return units


def _bindings(text: str) -> dict[str, list[str]]:
    """Each name a routing instance binds, with the instances that do."""
    bound: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = _BINDING.match(line)
        if m:
            bound.setdefault(m.group("name"), []).append(m.group("instance"))
    return bound


def _defects_onto_junos(source: str, text: str, job: MigrationJob) -> list[str]:
    """What is wrong with a job onto Junos, read from its output.

    * no ``set interfaces`` line names a loopback device other than
      ``lo0``;
    * each unit of ``lo0`` but 0 is bound to exactly one routing
      instance, and the routing instance of its source loopback;
      unit 0 is bound to none;
    * each address of a source loopback is on ``lo0`` in the output,
      or its loopback is listed (dropped, or left to an entry) and the
      job is not ``completed``.
    """
    defects: list[str] = []
    out = job.rendered or ""
    for device in sorted(_loopback_devices(out) - {"lo0"}):
        defects.append(f"the output configures {device!r}, which Junos does not have")
    units = _lo0_units(out)
    bindings = _bindings(out)
    tree = get_codec(source).parse(text)
    for iface in tree.interfaces:
        if not _A_LOOPBACK.match(iface.name):
            continue
        for address in [a.ip for a in iface.ipv4_addresses]:
            unit = units.get(address)
            if unit is None:
                listed = iface.name in (job.unresolved_ports + job.untranslated_ports + job.port_drops)
                if not listed:
                    defects.append(f"{iface.name!r} ({address}) is not on lo0 and not listed")
                elif job.status == MigrationJobStatus.completed:
                    defects.append(f"{iface.name!r} is not in the output of a completed job")
                continue
            instances = bindings.get(f"lo0.{unit}", [])
            if unit == 0:
                if instances:
                    defects.append(f"lo0.0 is bound to {instances}")
                if iface.vrf:
                    defects.append(f"{iface.name!r} of {iface.vrf!r} is on lo0.0")
            elif instances != [iface.vrf]:
                defects.append(
                    f"{iface.name!r} of {iface.vrf or 'the global table'!r} is on "
                    f"lo0.{unit}, bound to {instances}"
                )
    seen: dict[str, str] = {}
    for name, instances in bindings.items():
        if not name.startswith("lo0."):
            continue
        for instance in instances:
            if instance in seen:
                defects.append(f"{instance!r} binds {seen[instance]} and {name}")
            seen[instance] = name
    return defects


# ---------------------------------------------------------------------------
# Onto Junos, from sources typed here
# ---------------------------------------------------------------------------


def _ios(*loopbacks: tuple[int, str, str]) -> str:
    """An IOS-XE CLI config of loopbacks ``(number, vrf, address)``."""
    lines = ["hostname r1", "!"]
    for vrf in sorted({v for _, v, _ in loopbacks if v}):
        lines += [f"vrf definition {vrf}", " address-family ipv4",
                  " exit-address-family", "!"]
    for number, vrf, address in loopbacks:
        lines.append(f"interface Loopback{number}")
        if vrf:
            lines.append(f" vrf forwarding {vrf}")
        lines += [f" ip address {address} 255.255.255.255", "!"]
    return "\n".join([*lines, "end", ""])


def _eos(*loopbacks: tuple[int, str, str]) -> str:
    """An EOS config of loopbacks ``(number, vrf, address)``."""
    lines = ["hostname r1", "!"]
    for vrf in sorted({v for _, v, _ in loopbacks if v}):
        lines += [f"vrf instance {vrf}", "!"]
    for number, vrf, address in loopbacks:
        lines.append(f"interface Loopback{number}")
        if vrf:
            lines.append(f"   vrf {vrf}")
        lines += [f"   ip address {address}/32", "!"]
    return "\n".join([*lines, ""])


_GRAMMARS = {"cisco_iosxe_cli": _ios, "arista_eos": _eos}

#: ``(case, loopbacks, where each address is, what is dropped)``.
#: Where an address is: its unit of lo0, written out by hand.
_CASES = [
    ("one-global-numbered-1", [(1, "", "10.0.0.1")], {"10.0.0.1": 0}, []),
    ("zero-and-a-routing-instance",
     [(0, "", "10.0.0.1"), (101, "T", "10.0.1.1")],
     {"10.0.0.1": 0, "10.0.1.1": 101}, []),
    ("two-routing-instances",
     [(0, "", "10.0.0.1"), (101, "T", "10.0.1.1"), (201, "U", "10.0.2.1")],
     {"10.0.0.1": 0, "10.0.1.1": 101, "10.0.2.1": 201}, []),
    ("two-global-one-numbered-0",
     [(0, "", "10.0.0.1"), (1, "", "10.0.0.2")],
     {"10.0.0.1": 0}, ["Loopback1"]),
    ("two-global-none-numbered-0",
     [(1, "", "10.0.0.1"), (2, "", "10.0.0.2")],
     {}, ["Loopback1", "Loopback2"]),
    ("two-in-one-routing-instance",
     [(0, "", "10.0.0.1"), (101, "T", "10.0.1.1"), (102, "T", "10.0.1.2")],
     {"10.0.0.1": 0}, ["Loopback101", "Loopback102"]),
    ("numbered-0-in-a-routing-instance",
     [(1, "", "10.0.0.1"), (0, "T", "10.0.1.1")],
     {"10.0.0.1": 0}, ["Loopback0"]),
    ("the-internal-unit",
     [(0, "", "10.0.0.1"), (16384, "T", "10.0.1.1")],
     {"10.0.0.1": 0}, ["Loopback16384"]),
]


class TestOntoJunos:
    """Each case in two grammars, read as text and with the Junos
    parser."""

    @pytest.mark.parametrize("source", sorted(_GRAMMARS))
    @pytest.mark.parametrize(
        ("case", "loopbacks", "units", "dropped"), _CASES, ids=[c[0] for c in _CASES],
    )
    def test_each_loopback_is_a_unit_of_lo0_or_is_listed(
        self, source: str, case: str, loopbacks: list, units: dict, dropped: list,
    ) -> None:
        text = _GRAMMARS[source](*loopbacks)
        job = _job(source, "juniper_junos", text)
        assert _defects_onto_junos(source, text, job) == []
        assert _lo0_units(job.rendered) == units
        assert sorted(job.unresolved_ports) == sorted(dropped)
        assert job.status == (
            MigrationJobStatus.partial if dropped else MigrationJobStatus.completed
        )
        for name in dropped:
            assert any(
                w.startswith(f"juniper_junos: {source} loopback {name!r} ")
                for w in job.warnings
            ), name
        # The parser reads each placed unit back in its routing instance.
        back = get_codec("juniper_junos").parse(job.rendered)
        vrf_of = {address: vrf for _, vrf, address in loopbacks}
        for iface in back.interfaces:
            for address in [a.ip for a in iface.ipv4_addresses]:
                assert iface.name == ("lo0" if units[address] == 0 else f"lo0.{units[address]}")
                assert iface.vrf == vrf_of[address]

    def test_an_entry_decides_and_takes_its_unit(self) -> None:
        """An entry decides its loopback, and the unit it gives is not
        given again: the other loopback of the global table is then
        refused, not put on ``lo0`` beside it."""
        text = _ios((0, "", "10.0.0.1"), (1, "", "10.0.0.2"))
        job = _job("cisco_iosxe_cli", "juniper_junos", text, {"Loopback1": "lo0"})
        assert _lo0_units(job.rendered) == {"10.0.0.2": 0}
        assert job.unresolved_ports == ["Loopback0"]
        assert job.status == MigrationJobStatus.partial
        settled = _job(
            "cisco_iosxe_cli", "juniper_junos", text, {"Loopback1": None},
        )
        assert settled.status == MigrationJobStatus.completed
        assert _lo0_units(settled.rendered) == {"10.0.0.1": 0}

    def test_an_entry_that_takes_a_routing_instances_unit(self) -> None:
        text = _ios((0, "", "10.0.0.1"), (101, "T", "10.0.1.1"), (5, "", "10.0.0.5"))
        job = _job(
            "cisco_iosxe_cli", "juniper_junos", text, {"Loopback5": "lo0.101"},
        )
        assert "Loopback101" in job.unresolved_ports
        assert "10.0.1.1" not in _lo0_units(job.rendered)


class TestOntoJunosOverTheCaptures:
    """Every committed input with a loopback, onto Junos."""

    @pytest.mark.parametrize(
        ("source", "path"),
        [(c, p) for c, p in _LOOPBACK_INPUTS if c != "juniper_junos"],
        ids=[p.name for c, p in _LOOPBACK_INPUTS if c != "juniper_junos"],
    )
    def test_no_loopback_but_lo0_and_none_lost_unsaid(self, source: str, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        job = _job(source, "juniper_junos", text)
        if job.status == MigrationJobStatus.failed:
            pytest.skip(f"the job failed: {job.error}")
        assert _defects_onto_junos(source, text, job) == []

    def test_the_captures_hold_the_cases(self) -> None:
        """The inputs above are not all of one shape: some place a
        loopback in a routing instance, and some have a second
        loopback in the global table."""
        in_an_instance = second = 0
        for source, path in _LOOPBACK_INPUTS:
            if source == "juniper_junos":
                continue
            tree = get_codec(source).parse(path.read_text(encoding="utf-8", errors="replace"))
            loops = [i for i in tree.interfaces if _A_LOOPBACK.match(i.name)]
            in_an_instance += any(i.vrf for i in loops)
            second += sum(1 for i in loops if not i.vrf) > 1
        assert in_an_instance >= 2 and second >= 2


# ---------------------------------------------------------------------------
# From Junos: a unit of lo0 is a loopback of its own
# ---------------------------------------------------------------------------

_JUNOS_UNITS = "\n".join([
    "set system host-name r1",
    "set interfaces lo0 unit 0 family inet address 10.0.0.1/32",
    "set interfaces lo0 unit 2 family inet address 10.0.0.2/32",
    "set interfaces lo0 unit 10 family inet address 10.0.0.10/32",
    "set routing-instances A instance-type vrf",
    "set routing-instances A interface lo0.2",
    "set routing-instances B instance-type vrf",
    "set routing-instances B interface lo0.10",
    "",
])
_JUNOS_ADDRESSES = {"10.0.0.1": "lo0", "10.0.0.2": "lo0.2", "10.0.0.10": "lo0.10"}


def _fusions(target: str, job: MigrationJob, addresses: dict[str, str]) -> list[str]:
    """Interfaces of the output, read by the target's parser, that
    carry the addresses of two source loopbacks; and an address that
    is in no interface of the output while its loopback is not
    listed."""
    if job.status == MigrationJobStatus.failed:
        return [f"failed: {job.error}"]
    back = get_codec(target).parse(job.rendered)
    holders: dict[str, list[str]] = {}
    for iface in back.interfaces:
        for a in iface.ipv4_addresses:
            if a.ip in addresses:
                holders.setdefault(iface.name, []).append(addresses[a.ip])
    defects = [
        f"{name!r} carries {sorted(set(sources))}"
        for name, sources in holders.items() if len(set(sources)) > 1
    ]
    found = {s for sources in holders.values() for s in sources}
    listed = set(job.unresolved_ports + job.untranslated_ports + job.port_drops)
    for source in sorted(set(addresses.values()) - found - listed):
        defects.append(f"{source!r} is in no interface of the output and not listed")
    return defects


class TestFromJunos:

    @pytest.mark.parametrize("target", [c for c in list_public_codecs() if c != "juniper_junos"])
    def test_each_unit_is_a_loopback_of_its_own(self, target: str) -> None:
        job = _job("juniper_junos", target, _JUNOS_UNITS)
        assert _fusions(target, job, _JUNOS_ADDRESSES) == []
        assert not any(n.startswith("lo0") for ns in job.fused_ports.values() for n in ns)

    def test_the_number_is_the_unit(self) -> None:
        """Onto IOS-XE, by hand: unit N is ``LoopbackN``."""
        job = _job("juniper_junos", "cisco_iosxe_cli", _JUNOS_UNITS)
        assert {k: v for k, v in job.port_renames.items() if k.startswith("lo0")} == {
            "lo0": "Loopback0", "lo0.2": "Loopback2", "lo0.10": "Loopback10",
        }

    @pytest.mark.parametrize("target", [c for c in list_public_codecs() if c != "juniper_junos"])
    def test_over_the_junos_captures(self, target: str) -> None:
        for source, path in _LOOPBACK_INPUTS:
            if source != "juniper_junos":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = get_codec(source).parse(text)
            addresses = {
                a.ip: i.name for i in tree.interfaces if _A_LOOPBACK.match(i.name)
                for a in i.ipv4_addresses
            }
            job = _job(source, target, text)
            assert _fusions(target, job, addresses) == [], path.name

    @pytest.mark.parametrize("target", ["arista_eos", "cisco_iosxe_cli", "vyos"])
    def test_a_unit_of_too_many_digits_fails_no_job(self, target: str) -> None:
        """A pasted config can write more digits than ``int`` converts:
        read as text, such a unit is no unit of lo0 and the name is
        one the classifier does not know.  Where the bare pipeline --
        parse and render, no translator -- gets through, so does the
        job (the IOS-XE renderer fails on such a name whoever hands
        it over: it sorts interfaces by the numbers in their names;
        see ``TestAUnitOfTooManyDigits`` in
        ``test_units_follow_their_port.py``)."""
        unit = "7" * 4301
        text = _JUNOS_UNITS.replace("lo0 unit 2 ", f"lo0 unit {unit} ").replace(
            "interface lo0.2", f"interface lo0.{unit}",
        )
        source = get_codec("juniper_junos")
        if run_plan(source, get_codec(target), text).status == MigrationJobStatus.failed:
            return
        job = _job("juniper_junos", target, text)
        assert job.status != MigrationJobStatus.failed, job.error
        assert f"lo0.{unit}" in job.untranslated_ports


# ---------------------------------------------------------------------------
# The hook, and each check handed the defect it is for
# ---------------------------------------------------------------------------


class TestThePlacement:
    """``place_loopbacks`` alone, on the cases the docstring names."""

    def test_the_cases(self) -> None:
        place = junos_names.place_loopbacks

        def lb(name: str, number: int | None, instance: str = "") -> LoopbackToPlace:
            return LoopbackToPlace(name, number, instance)

        assert place([lb("L7", 7)], frozenset()) == ({"L7": "lo0"}, {})
        placed, refused = place([lb("L0", 0), lb("L1", 1)], frozenset())
        assert placed == {"L0": "lo0"} and set(refused) == {"L1"}
        placed, refused = place([lb("L1", 1), lb("L2", 2)], frozenset())
        assert placed == {} and set(refused) == {"L1", "L2"}
        placed, refused = place([lb("A", 5, "X"), lb("B", 5, "Y")], frozenset())
        assert placed == {} and set(refused) == {"A", "B"}
        placed, refused = place([lb("A", None, "X"), lb("B", 16383, "Y")], frozenset())
        assert placed == {"B": "lo0.16383"} and set(refused) == {"A"}
        placed, refused = place([lb("L0", 0)], frozenset({"lo0.0"}))
        assert placed == {} and set(refused) == {"L0"}
        placed, refused = place([lb("A", 9, "X")], frozenset({"lo0.009"}))
        assert placed == {} and set(refused) == {"A"}

    def test_a_target_that_places_none_formats_each(self) -> None:
        """The default: every target but Junos formats one name at a
        time, as before."""
        for name in list_public_codecs():
            if name != "juniper_junos":
                assert get_codec(name).place_loopbacks([], frozenset()) is None


class TestEachCheckSeesItsDefect:

    def test_the_old_placement_is_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loopbacks named one at a time, as ``lo<N>``: the reader of
        text finds the device Junos does not have, on the captures."""
        monkeypatch.setattr(JunosCodec, "place_loopbacks", lambda self, loopbacks, taken: None)
        monkeypatch.setattr(
            junos_names, "format_port_identity",
            lambda identity: f"lo{identity.index or 0}" if identity.kind == "loopback"
            else _FORMAT(identity),
        )
        found = 0
        for source, path in _LOOPBACK_INPUTS:
            if source == "juniper_junos":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            job = _job(source, "juniper_junos", text)
            found += bool(_defects_onto_junos(source, text, job))
        assert found >= 2

    def test_a_loopback_in_the_wrong_instance_is_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every loopback on unit 0: a routing instance's address on
        the global table's loopback."""
        monkeypatch.setattr(
            JunosCodec, "place_loopbacks",
            lambda self, loopbacks, taken: ({lb.name: "lo0" for lb in loopbacks}, {}),
        )
        text = _ios((0, "", "10.0.0.1"), (101, "T", "10.0.1.1"))
        job = _job("cisco_iosxe_cli", "juniper_junos", text)
        assert _defects_onto_junos("cisco_iosxe_cli", text, job) != []

    def test_a_refusal_the_job_does_not_list_is_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A loopback dropped and not listed (the job says nothing)."""
        text = _ios((0, "", "10.0.0.1"), (1, "", "10.0.0.2"))
        job = _job("cisco_iosxe_cli", "juniper_junos", text)
        hidden = job.model_copy(update={
            "unresolved_ports": [], "status": MigrationJobStatus.completed,
        })
        assert _defects_onto_junos("cisco_iosxe_cli", text, hidden) != []

    def test_the_old_reading_of_a_unit_is_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A unit of lo0 read as lo0 itself: the units fuse."""
        classify = junos_names.classify_port_name

        def old(name: str):
            identity = classify(name)
            if identity.kind == "loopback":
                return identity.model_copy(update={"index": 0})
            return identity

        monkeypatch.setattr(junos_names, "classify_port_name", old)
        job = _job("juniper_junos", "cisco_iosxe_cli", _JUNOS_UNITS)
        assert _fusions("cisco_iosxe_cli", job, _JUNOS_ADDRESSES) != []


_FORMAT = junos_names.format_port_identity
