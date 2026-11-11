"""A VLAN interface of a grammar that has one is its VLAN on AOS-S, and
an interface that only begins ``vlan`` is not.

AOS-S writes a VLAN interface's addresses and VRRP groups in the VLAN's
own stanza, and the renderer looked for the interface by one name,
``Vlan<id>``.  An AOS-CX ``interface vlan 31`` or an OS10 ``interface
vlan31`` lost its IPv6 addresses, and the OS10 one its VRRP groups (its
IPv4 address is on its VLAN's record, where those parsers put it); a VLAN
interface that is shut down was written as an address that is up, from
every grammar, since the parsers put its address on its VLAN; and an
interface whose name begins ``vlan`` and that is no VLAN of the output (a
FortiOS loopback called ``vlan-guest``) was skipped, with its addresses
-- in jobs that said nothing of any of it.

The sources are typed by hand, one per grammar that has a VLAN
interface, and sent onto AOS-S through the plan path.  The output is
read as text, by a reader of this module's own, and with the AOS-S
parser; and each check is handed the defect it is for.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.codecs.aruba_aoss import codec as aoss_codec
from netcanon.migration.codecs.aruba_aoss import render as aoss_render
from netcanon.migration.codecs.aruba_aoss import vlan_interfaces
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

AOSS = "aruba_aoss"
_V6 = "2001:db8:31::1"
_V4 = "10.32.0.1"

#: Per source codec: the name its parser gives VLAN 31's interface, and
#: a config whose VLAN 31 has an interface holding the IPv6 address
#: ``2001:db8:31::1/64`` and nothing else.
_IPV6_ONLY: dict[str, tuple[str, str]] = {
    "cisco_iosxe_cli": ("Vlan31", (
        "hostname r1\nvlan 31\n!\ninterface Vlan31\n ipv6 address 2001:db8:31::1/64\n!\nend\n"
    )),
    "cisco_nxos": ("Vlan31", (
        "hostname r1\nfeature interface-vlan\nvlan 31\n"
        "interface Vlan31\n  ipv6 address 2001:db8:31::1/64\n  no shutdown\n"
    )),
    "arista_eos": ("Vlan31", (
        "hostname r1\n!\nvlan 31\n!\ninterface Vlan31\n   ipv6 address 2001:db8:31::1/64\n!\n"
    )),
    "aruba_aoscx": ("vlan 31", (
        "hostname r1\nvlan 31\ninterface vlan 31\n    ipv6 address 2001:db8:31::1/64\n"
    )),
    "dell_os10": ("vlan31", (
        "hostname r1\ninterface vlan31\n ipv6 address 2001:db8:31::1/64\n no shutdown\n!\n"
    )),
    "aruba_aoss": ("Vlan31", (
        'hostname "r1"\nvlan 31\n   ipv6 address 2001:db8:31::1/64\n   exit\n'
    )),
}

#: Per source codec: the name its parser gives VLAN 32's interface, and
#: a config whose VLAN 32 has an interface that is shut down and holds
#: the address ``10.32.0.1/24``, and an access port ``GigabitEthernet9``
#: or the like in VLAN 32 where the grammar states one.
_SHUT_DOWN: dict[str, tuple[str, str]] = {
    "cisco_iosxe_cli": ("Vlan32", (
        "hostname r1\nvlan 32\n!\n"
        "interface Vlan32\n ip address 10.32.0.1 255.255.255.0\n shutdown\n!\nend\n"
    )),
    "cisco_nxos": ("Vlan32", (
        "hostname r1\nfeature interface-vlan\nvlan 32\n"
        "interface Vlan32\n  ip address 10.32.0.1/24\n  shutdown\n"
    )),
    "arista_eos": ("Vlan32", (
        "hostname r1\n!\nvlan 32\n!\ninterface Vlan32\n   shutdown\n   ip address 10.32.0.1/24\n!\n"
    )),
    "aruba_aoscx": ("vlan 32", (
        "hostname r1\nvlan 32\ninterface vlan 32\n    shutdown\n    ip address 10.32.0.1/24\n"
    )),
    "dell_os10": ("vlan32", (
        "hostname r1\ninterface vlan32\n ip address 10.32.0.1/24\n shutdown\n!\n"
    )),
}


def _job(source: str, text: str, port_rename_map: dict[str, str] | None = None) -> MigrationJob:
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(AOSS), text, port_rename_map=port_rename_map or {},
    )
    assert job.rendered, job.error
    return job


def _stanzas(text: str) -> dict[str, list[str]]:
    """Each stanza of an AOS-S *text* by its header line, with its lines
    stripped: from a line in column 0 to the next.  A header met twice
    has the lines of both."""
    stanzas: dict[str, list[str]] = {}
    body: list[str] | None = None
    for line in text.splitlines():
        if line[:1].strip():
            body = stanzas.setdefault(line.strip(), [])
        elif body is not None and line.strip():
            body.append(line.strip())
    return stanzas


def _reviews(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith("; review:")]


def _read_back(text: str) -> CanonicalIntent:
    return get_codec(AOSS).parse(text)


def _ipv6_problems(job: MigrationJob) -> list[str]:
    """What is wrong with VLAN 31 in the output of *job*: its stanza has
    to hold the IPv6 address, and the AOS-S parser has to read it back
    onto ``Vlan31``; no stanza of an interface of VLAN 31's own."""
    out = job.rendered or ""
    problems: list[str] = []
    body = _stanzas(out).get("vlan 31")
    if body != [f"ipv6 address {_V6}/64", "exit"]:
        problems.append(f"vlan 31 is {body}")
    own = [h for h in _stanzas(out) if h.lower().startswith("interface vlan")]
    if own:
        problems.append(f"the output has {own}")
    back = [i.name for i in _read_back(out).interfaces if any(a.ip == _V6 for a in i.ipv6_addresses)]
    if back != ["Vlan31"]:
        problems.append(f"{_V6} is read onto {back}")
    return problems


def _shut_down_problems(job: MigrationJob, name: str) -> list[str]:
    """What is wrong with VLAN 32 in the output of *job*: its stanza is
    written, with no address; the address is in no line and read onto
    nothing; one review line and one warning say why, naming *name*."""
    out = job.rendered or ""
    problems: list[str] = []
    if "vlan 32" not in _stanzas(out):
        problems.append("there is no vlan 32")
    if _V4 in out.replace(f"; review: interface {name}", ""):
        problems.append(f"{_V4} is in the output")
    back = [i.name for i in _read_back(out).interfaces if any(a.ip == _V4 for a in i.ipv4_addresses)]
    back += [f"vlan {v.id}" for v in _read_back(out).vlans if any(a.ip == _V4 for a in v.ipv4_addresses)]
    if back:
        problems.append(f"{_V4} is read onto {back}")
    why = f"interface {name} is disabled, and an AOS-S VLAN cannot be; not written"
    if _reviews(out) != [f"; review: {why}"]:
        problems.append(f"the review lines are {_reviews(out)}")
    if [w for w in job.warnings if w == why] != [why]:
        problems.append("the job does not say it once")
    return problems


class TestAVlanInterfaceIsItsVlan:
    @pytest.mark.parametrize("source", sorted(_IPV6_ONLY))
    def test_its_ipv6_address_is_in_its_vlans_stanza(self, source: str) -> None:
        name, text = _IPV6_ONLY[source]
        assert [i.name for i in get_codec(source).parse(text).interfaces] == [name]
        assert _ipv6_problems(_job(source, text)) == []

    def test_its_vrrp_group_is_in_its_vlans_stanza(self) -> None:
        """An OS10 ``vlan31`` that holds a VRRP group and no address:
        the group was dropped with the interface."""
        text = (
            "hostname r1\ninterface vlan31\n no shutdown\n vrrp-group 7\n"
            "  virtual-address 192.0.2.254\n!\n"
        )
        out = _job("dell_os10", text).rendered
        body = _stanzas(out)["vlan 31"]
        assert body[body.index("vrrp vrid 7") + 1] == "virtual-ip-address 192.0.2.254"
        (vlan_31,) = _read_back(out).interfaces
        assert (vlan_31.name, [g.virtual_ips for g in vlan_31.vrrp_groups]) == (
            "Vlan31", [["192.0.2.254"]],
        )

    def test_the_upper_case_is_one_of_its_grammar(self) -> None:
        """``VLAN31`` is a name an IOS-XE operator can type; the parser
        keeps it, and it is VLAN 31's interface."""
        name, text = _IPV6_ONLY["cisco_iosxe_cli"]
        tree = get_codec("cisco_iosxe_cli").parse(text)
        tree.interfaces[0].name = "VLAN31"
        out = aoss_render.render_intent(tree)
        assert _stanzas(out)["vlan 31"] == [f"ipv6 address {_V6}/64", "exit"]

    @pytest.mark.parametrize("source", ["aruba_aoscx", "dell_os10"])
    def test_the_check_sees_it_lost(self, source: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handed the renderer as it was (no interface read for the VLAN
        it stands for), the check above fails."""
        monkeypatch.setattr(
            aoss_render, "prepare_vlan_interfaces", lambda tree: vlan_interfaces.Prepared(tree),
        )
        _name, text = _IPV6_ONLY[source]
        assert _ipv6_problems(_job(source, text)) != []


class TestOneThatIsShutDown:
    @pytest.mark.parametrize("source", sorted(_SHUT_DOWN))
    def test_is_left_out_under_a_review_line(self, source: str) -> None:
        name, text = _SHUT_DOWN[source]
        (iface,) = [i for i in get_codec(source).parse(text).interfaces if i.name == name]
        assert not iface.enabled
        assert _shut_down_problems(_job(source, text), name) == []

    def test_its_vlans_ports_are_still_written(self) -> None:
        _name, text = _SHUT_DOWN["cisco_iosxe_cli"]
        text = text.replace(
            "interface Vlan32", "interface GigabitEthernet1/0/4\n switchport access vlan 32\n!\ninterface Vlan32",
        )
        job = _job("cisco_iosxe_cli", text, {"GigabitEthernet1/0/4": "4"})
        assert _stanzas(job.rendered)["vlan 32"] == ["untagged 4", "exit"]
        assert _shut_down_problems(job, "Vlan32") == []

    def test_nothing_on_it_is_written(self) -> None:
        """Its VRRP group is not written; a route out of it and a pool
        it served each have a review line of their own."""
        _name, text = _SHUT_DOWN["cisco_iosxe_cli"]
        text = text.replace(" shutdown\n", " vrrp 3 ip 10.32.0.254\n shutdown\n").replace(
            "end\n",
            "ip dhcp pool users\n network 10.32.0.0 255.255.255.0\n default-router 10.32.0.1\n!\n"
            "ip route 192.0.2.0 255.255.255.0 Vlan32\nend\n",
        )
        out = _job("cisco_iosxe_cli", text).rendered
        body = _stanzas(out)["vlan 32"]
        assert body == ["exit"]
        assert "10.32.0.254" not in out
        assert not [line for line in out.splitlines() if line.startswith("ip route")]
        assert any(r.startswith("; review: static route 192.0.2.0/24 goes out Vlan32") for r in _reviews(out))
        assert any("the source serves this pool on Vlan32" in r for r in _reviews(out))

    def test_one_that_holds_nothing_says_nothing(self) -> None:
        """Nothing of it is lost: its VLAN is written, and no line says
        more."""
        text = "hostname r1\nvlan 33\n!\ninterface Vlan33\n shutdown\n!\nend\n"
        job = _job("cisco_iosxe_cli", text)
        assert _stanzas(job.rendered)["vlan 33"] == ["exit"]
        assert _reviews(job.rendered) == []
        assert not [w for w in job.warnings if "Vlan33" in w]

    @pytest.mark.parametrize("defect", ["written_live", "unsaid"])
    @pytest.mark.parametrize("source", sorted(_SHUT_DOWN))
    def test_the_check_sees_each_defect(
        self, source: str, defect: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handed the renderer as it was, or a job that says nothing,
        the check above fails."""
        if defect == "written_live":
            monkeypatch.setattr(
                aoss_render, "prepare_vlan_interfaces", lambda tree: vlan_interfaces.Prepared(tree),
            )
        else:
            monkeypatch.setattr(aoss_codec, "vlan_interface_warnings", lambda tree: [])
        name, text = _SHUT_DOWN[source]
        assert _shut_down_problems(_job(source, text), name) != []


def _svi(name: str, *addresses: str, kind: str = "ianaift:l3ipvlan", **kw) -> CanonicalInterface:
    return CanonicalInterface(
        name=name, interface_type=kind,
        ipv4_addresses=[CanonicalIPv4Address(ip=a, prefix_length=24) for a in addresses],
        **kw,
    )


class TestTreesNoParserMakesHere:
    def test_one_with_no_vlan_record_is_given_one(self) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[_svi("vlan 40", "10.40.0.1")])
        out = aoss_render.render_intent(tree)
        assert _stanzas(out)["vlan 40"] == ["ip address 10.40.0.1/24", "exit"]

    def test_one_with_no_vlan_record_that_holds_nothing_is_not(self) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[_svi("vlan41")])
        out = aoss_render.render_intent(tree)
        assert [h for h in _stanzas(out) if "41" in h] == []

    def test_the_netconf_type_is_one(self) -> None:
        """The IOS-XE NETCONF parser types ``Vlan<id>`` ``l2vlan``."""
        tree = CanonicalIntent(
            hostname="r1", vlans=[CanonicalVlan(id=32, ipv4_addresses=[
                CanonicalIPv4Address(ip=_V4, prefix_length=24),
            ])],
            interfaces=[_svi("Vlan32", _V4, kind="ianaift:l2vlan", enabled=False)],
        )
        out = aoss_render.render_intent(tree)
        assert _stanzas(out)["vlan 32"] == ["exit"]
        assert _reviews(out) == [
            "; review: interface Vlan32 is disabled, and an AOS-S VLAN cannot be; not written",
        ]

    def test_two_of_one_vlan(self) -> None:
        """The one already named ``Vlan30`` keeps the name, wherever it
        is in the tree; the other is left out, its name not being
        free."""
        tree = CanonicalIntent(
            hostname="r1", vlans=[CanonicalVlan(id=30)],
            interfaces=[_svi("vlan 30", "10.30.0.1"), _svi("Vlan30", "10.31.0.1")],
        )
        prepared = vlan_interfaces.prepare(tree)
        assert prepared.review == {"vlan 30": (
            "; review: interface vlan 30 stands for VLAN 30, as Vlan30 does, and an "
            "AOS-S VLAN stanza is one interface's; not written"
        )}
        out = aoss_render.render_intent(tree)
        assert _stanzas(out)["vlan 30"] == ["ip address 10.31.0.1/24", "exit"]
        assert "10.30.0.1" not in out.replace("; review: interface vlan 30", "")

    def test_a_name_another_interface_has(self) -> None:
        """``vlan 30`` cannot be renamed ``Vlan30`` where a FortiOS-like
        loopback is called ``vlan30``: it is left out, and the loopback
        is written under its name."""
        tree = CanonicalIntent(
            hostname="r1", vlans=[CanonicalVlan(id=30)],
            interfaces=[
                _svi("vlan 30", "10.30.0.1"),
                _svi("vlan30", "10.31.0.1", kind="ianaift:softwareLoopback"),
            ],
        )
        prepared = vlan_interfaces.prepare(tree)
        assert list(prepared.review) == ["vlan 30"]
        assert "as vlan30 does" in prepared.review["vlan 30"]

    def test_a_record_of_its_own_address_keeps_it(self) -> None:
        """Only the shut-down interface's addresses come off its VLAN's
        record: one the record holds of its own is still written."""
        tree = CanonicalIntent(
            hostname="r1", vlans=[CanonicalVlan(id=32, ipv4_addresses=[
                CanonicalIPv4Address(ip=_V4, prefix_length=24),
                CanonicalIPv4Address(ip="10.99.0.1", prefix_length=24),
            ])],
            interfaces=[_svi("Vlan32", _V4, enabled=False)],
        )
        out = aoss_render.render_intent(tree)
        assert _stanzas(out)["vlan 32"] == ["ip address 10.99.0.1/24", "exit"]

    def test_the_tree_given_is_not_changed(self) -> None:
        tree = CanonicalIntent(
            hostname="r1", vlans=[CanonicalVlan(id=32, ipv4_addresses=[
                CanonicalIPv4Address(ip=_V4, prefix_length=24),
            ])],
            interfaces=[_svi("vlan 32", _V4, enabled=False), _svi("vlan 40", "10.40.0.1")],
        )
        before = tree.model_dump()
        prepared = vlan_interfaces.prepare(tree)
        assert tree.model_dump() == before
        assert prepared.tree is not tree


#: Interfaces whose name begins ``vlan`` and that are no VLAN interface
#: of a grammar: a name an operator chose, typed by its parser as what
#: it is.  Each, the name, and its address.
_NO_VLAN: dict[str, tuple[str, str, str, str]] = {
    "a FortiOS loopback": ("fortigate_cli", "vlan-guest", "10.99.0.1", (
        "config system interface\n"
        '    edit "vlan-guest"\n        set type loopback\n'
        "        set ip 10.99.0.1 255.255.255.255\n    next\nend\n"
    )),
    "a FortiOS loopback in capitals": ("fortigate_cli", "VLAN30", "10.98.0.1", (
        "config system interface\n"
        '    edit "VLAN30"\n        set type loopback\n'
        "        set ip 10.98.0.1 255.255.255.255\n    next\nend\n"
    )),
    "a RouterOS bridge": ("mikrotik_routeros", "vlanbr", "10.77.0.1", (
        "/interface bridge\nadd name=vlanbr\n"
        "/ip address\nadd address=10.77.0.1/24 interface=vlanbr\n"
    )),
}


def _no_vlan_problems(job: MigrationJob, name: str, ip: str) -> list[str]:
    """What is wrong with interface *name*, address *ip*, in the output
    of *job*: it has to be written under its name with its address, as
    another name of no AOS-S form is, read back onto it by the AOS-S
    parser, and be in no VLAN's stanza."""
    out = job.rendered or ""
    problems: list[str] = []
    stanzas = _stanzas(out)
    body = stanzas.get(f"interface {name}")
    if body is None or not any(line.startswith(f"ip address {ip}/") for line in body):
        problems.append(f"interface {name} is {body}")
    in_vlans = [h for h, lines in stanzas.items() if h.startswith("vlan ") and any(ip in x for x in lines)]
    if in_vlans:
        problems.append(f"{ip} is in {in_vlans}")
    back = [i.name for i in _read_back(out).interfaces if any(a.ip == ip for a in i.ipv4_addresses)]
    if back != [name]:
        problems.append(f"{ip} is read onto {back}")
    return problems


class TestANameThatOnlyBeginsVlan:
    @pytest.mark.parametrize("case", sorted(_NO_VLAN))
    def test_is_written_as_other_names_of_no_aoss_form(self, case: str) -> None:
        source, name, ip, text = _NO_VLAN[case]
        (iface,) = get_codec(source).parse(text).interfaces
        assert iface.interface_type not in vlan_interfaces._SVI_TYPES
        assert _no_vlan_problems(_job(source, text), name, ip) == []

    @pytest.mark.parametrize("case", sorted(_NO_VLAN))
    def test_the_check_sees_it_skipped(self, case: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handed a renderer that skips such a name, as it did, the
        check above fails."""
        source, name, ip, text = _NO_VLAN[case]
        real = aoss_render.prepare_vlan_interfaces

        def prepare(tree):
            prepared = real(tree)
            return vlan_interfaces.Prepared(
                prepared.tree, prepared.review, prepared.not_a_vlan,
                prepared.warnings, prepared.as_vlans | {name.lower()},
            )

        monkeypatch.setattr(aoss_render, "prepare_vlan_interfaces", prepare)
        assert _no_vlan_problems(_job(source, text), name, ip) != []

    @pytest.mark.parametrize("name", ["VLAN30", "vlan30"])
    def test_the_check_sees_its_shape_vouched_for(
        self, name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handed a renderer that reads a VLAN interface from the name
        alone, whatever its parser typed it, the check above fails for
        a FortiOS loopback named as a VLAN interface would be."""

        class _Every:
            def __contains__(self, _kind: object) -> bool:
                return True

        monkeypatch.setattr(vlan_interfaces, "_SVI_TYPES", _Every())
        _source, _name, _ip, text = _NO_VLAN["a FortiOS loopback in capitals"]
        job = _job("fortigate_cli", text.replace("VLAN30", name))
        assert _no_vlan_problems(job, name, "10.98.0.1") != []

    def test_a_lower_case_one_is_written_as_well(self) -> None:
        """A FortiOS loopback ``vlan30`` is no VLAN interface either."""
        _source, _name, ip, text = _NO_VLAN["a FortiOS loopback in capitals"]
        job = _job("fortigate_cli", text.replace("VLAN30", "vlan30"))
        assert _no_vlan_problems(job, "vlan30", ip) == []
