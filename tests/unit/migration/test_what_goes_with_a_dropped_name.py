"""What goes with a dropped name is said.

The port translator drops a name the target has no form for, and a
name an operator's entry maps to ``null``.  With the name it removes
what cannot stand without it (``_strip_dropped_ports``): a static
route out of it, a DHCP pool on it, a VRRP track entry of it, a VXLAN
source that is it, its place in a LAG.  The job listed the name; what
went with it was in no line of the job and, being removed, in no line
of the output.  Where both devices are declared the plan said it,
from a reading of its own; with none declared -- what every plan
endpoint runs by default -- nothing did: the Cisco Live EVPN leaf's
``Loopback2`` is its VTEP source, and onto Junos the VTEP was left
with no source in a job that said why ``Loopback2`` went and nothing
of the overlay.

The translator now records what it removes, where it removes it
(``PortRenameResult.taken``), and the job says it in the plan's words.
Three things are read here.

* **The record is what was done**, on every committed capture onto
  every public codec: the routes, pools, VNIs, LAGs and interfaces of
  the tree are held by IDENTITY before the translator runs, and what
  is gone from the tree afterwards, or emptied, is compared with the
  record.  The oracle asks nothing of the predicates that decide what
  goes.
* **The job says it**, once, for an operator's drop and for the
  translator's, from configs written here.
* **Where devices are declared the plan says it**, and the job says
  it once, not twice.

Each check is also handed the defect it is for.
"""

from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.canonical import port_names
from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.port_names import (
    TakenWithDrops,
    translate_port_names,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.device_models import inventory_from_profile
from netcanon.migration.target_profiles import load_profiles_dir
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import (
    run_plan_with_checked_names,
    run_plan_with_models,
)
from tests.unit.migration.test_run_plan_checked_names import CAPTURES

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PROFILES = load_profiles_dir(LIBRARY_DIR / "target_profiles")
LEAF = FIXTURES / "real" / "cisco_iosxe" / "ciscolive_brkops1104_evpn_leaf_iosxe1715.txt"


# ---------------------------------------------------------------------------
# The oracle: what is gone from the tree, by identity
# ---------------------------------------------------------------------------


class _Before:
    """The records of a tree, held by identity before the translator
    runs, with what each held then.  The translator mutates the tree
    in place: a record it removes is no longer in its list, and one it
    keeps is the same object."""

    def __init__(self, tree: CanonicalIntent) -> None:
        self.routes = list(tree.static_routes)
        self.pools = list(tree.dhcp_servers)
        self.vnis = [(vx, vx.source_interface) for vx in tree.vxlan_vnis]
        self.tracks = [
            (iface, iface.name, sum(len(g.track_interfaces) for g in iface.vrrp_groups))
            for iface in tree.interfaces
        ]
        # A LAG's places for a port: the entries of its member list,
        # and the interfaces that say they are in it, held by
        # identity.  Not names: two members can be renamed onto one
        # name (two FPCs onto one EOS port) with no member gone.
        self.lags = []
        for lag in tree.lags:
            claims = [
                iface for iface in tree.interfaces
                if iface.lag_member_of and iface.lag_member_of == lag.name
            ]
            places = len([member for member in lag.members if member]) + len(claims)
            self.lags.append((lag, lag.name, places, claims))


def _places(lag, claims: list, interfaces: set[int]) -> int:
    """How many places *lag* has for a port after the translator: an
    entry of its member list, or an interface that said it is in it
    and is still in the tree, still saying so."""
    still = [iface for iface in claims if id(iface) in interfaces and iface.lag_member_of]
    return len([member for member in lag.members if member]) + len(still)


def _gone(before: _Before, tree: CanonicalIntent) -> dict[str, Counter]:
    """What the tree no longer holds that it held, in the record's
    terms: source names, a route by its destination, a pool by its
    network (or its interface)."""
    routes = {id(r) for r in tree.static_routes}
    pools = {id(p) for p in tree.dhcp_servers}
    interfaces = {id(i) for i in tree.interfaces}
    lags = {id(lag) for lag in tree.lags}
    emptied, shrunk = Counter(), Counter()
    for lag, name, count, claims in before.lags:
        if id(lag) not in lags or not count:
            continue
        now = _places(lag, claims, interfaces)
        if now == 0:
            emptied[name] += 1
        elif now < count:
            shrunk[name] += 1
    return {
        "lost_routes": Counter(r.destination for r in before.routes if id(r) not in routes),
        "lost_dhcp_pools": Counter(
            p.network or p.interface for p in before.pools if id(p) not in pools
        ),
        "lost_vtep_sources": Counter(dict.fromkeys(
            name for vx, name in before.vnis if name and not vx.source_interface
        ).keys()),
        "lost_tracking": Counter(
            name for iface, name, count in before.tracks
            if id(iface) in interfaces
            and sum(len(g.track_interfaces) for g in iface.vrrp_groups) < count
        ),
        "emptied_lags": emptied,
        "shrunk_lags": shrunk,
    }


def _recorded(taken: TakenWithDrops) -> dict[str, Counter]:
    return {field: Counter(getattr(taken, field)) for field in TakenWithDrops.model_fields}


def _translate(source_name: str, target_name: str, tree: CanonicalIntent, rename_map=None):
    """The translator on *tree*, with what it held before."""
    before = _Before(tree)
    result = translate_port_names(
        tree, get_codec(source_name), get_codec(target_name), rename_map or {},
    )
    return before, result


# ---------------------------------------------------------------------------
# Configs written here
# ---------------------------------------------------------------------------

_IOS_ROUTE = """hostname sw
interface GigabitEthernet1/0/1
 description user
!
interface GigabitEthernet1/0/30
 description uplink
!
ip route 10.50.0.0 255.255.0.0 GigabitEthernet1/0/30 10.0.100.254
ip route 10.60.0.0 255.255.0.0 10.0.100.254
"""

_IOS_LAG = """hostname sw
interface Port-channel1
 description bundle
!
interface GigabitEthernet1/0/1
 channel-group 1 mode active
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
!
"""

_EOS_TRACK = """hostname sw
interface Ethernet1
   no switchport
   ip address 10.0.0.2/24
   vrrp 1 ipv4 10.0.0.1
   vrrp 1 track Ethernet2 decrement 20
!
interface Ethernet2
   no switchport
   ip address 10.0.1.2/24
!
"""

_FGT_POOL = """config system interface
    edit "internal1"
        set ip 10.1.0.1 255.255.255.0
    next
    edit "wan1"
        set ip 192.0.2.2 255.255.255.0
    next
end
config system dhcp server
    edit 1
        set default-gateway 10.1.0.1
        set netmask 255.255.255.0
        set interface "internal1"
        config ip-range
            edit 1
                set start-ip 10.1.0.10
                set end-ip 10.1.0.100
            next
        end
    next
end
"""

_SAID = "port_rename: "


def _checked(source_name: str, target_name: str, text: str, port_map=None):
    return run_plan_with_checked_names(
        get_codec(source_name), get_codec(target_name), text,
        port_rename_map=port_map or {},
    )


def _what_went(job) -> list[str]:
    """The lines that say what went with a dropped name."""
    return [line for line in job.warnings if line.startswith(_SAID) and (
        "removed with it" in line or "LAG(s)" in line
        or "VRRP track entry" in line or "VXLAN source interface" in line
    )]


# ---------------------------------------------------------------------------
# The record is what was done
# ---------------------------------------------------------------------------


class TestTheRecord:
    def test_an_operators_drop(self) -> None:
        tree = get_codec("cisco_iosxe_cli").parse(_IOS_ROUTE)
        before, result = _translate(
            "cisco_iosxe_cli", "arista_eos", tree, {"GigabitEthernet1/0/30": None},
        )
        assert result.taken.lost_routes == ["10.50.0.0/16"]
        assert _recorded(result.taken) == _gone(before, tree)
        # The route by its gateway alone stays.
        assert [r.destination for r in tree.static_routes] == ["10.60.0.0/16"]

    def test_a_lag_that_loses_one_and_one_that_loses_all(self) -> None:
        ios = get_codec("cisco_iosxe_cli")
        tree = ios.parse(_IOS_LAG)
        before, result = _translate(
            "cisco_iosxe_cli", "arista_eos", tree, {"GigabitEthernet1/0/1": None},
        )
        assert (result.taken.shrunk_lags, result.taken.emptied_lags) == (["Port-channel1"], [])
        assert _recorded(result.taken) == _gone(before, tree)
        tree = ios.parse(_IOS_LAG)
        before, result = _translate("cisco_iosxe_cli", "arista_eos", tree, {
            "GigabitEthernet1/0/1": None, "GigabitEthernet1/0/2": None,
        })
        assert (result.taken.shrunk_lags, result.taken.emptied_lags) == ([], ["Port-channel1"])
        assert _recorded(result.taken) == _gone(before, tree)

    def test_a_lag_that_is_itself_dropped_is_not_emptied(self) -> None:
        """It is gone, and the job lists it."""
        tree = get_codec("cisco_iosxe_cli").parse(_IOS_LAG)
        before, result = _translate("cisco_iosxe_cli", "arista_eos", tree, {
            "Port-channel1": None, "GigabitEthernet1/0/1": None,
            "GigabitEthernet1/0/2": None,
        })
        assert (result.taken.shrunk_lags, result.taken.emptied_lags) == ([], [])
        assert _recorded(result.taken) == _gone(before, tree)

    def test_a_track_entry(self) -> None:
        tree = get_codec("arista_eos").parse(_EOS_TRACK)
        assert tree.interfaces[0].vrrp_groups[0].track_interfaces == ["Ethernet2"]
        before, result = _translate("arista_eos", "cisco_iosxe_cli", tree, {"Ethernet2": None})
        assert result.taken.lost_tracking == ["Ethernet1"]
        assert _recorded(result.taken) == _gone(before, tree)

    def test_a_pool(self) -> None:
        tree = get_codec("fortigate_cli").parse(_FGT_POOL)
        before, result = _translate("fortigate_cli", "cisco_iosxe_cli", tree, {"internal1": None})
        assert result.taken.lost_dhcp_pools == ["10.1.0.0/24"]
        assert _recorded(result.taken) == _gone(before, tree)

    def test_the_translators_own_drop(self) -> None:
        """No entry: Junos has no form for a second loopback of the
        global table, and the leaf's VTEP source is one."""
        tree = get_codec("cisco_iosxe_cli").parse(LEAF.read_text(encoding="utf-8"))
        before, result = _translate("cisco_iosxe_cli", "juniper_junos", tree)
        assert "Loopback2" in result.dropped
        assert result.taken.lost_vtep_sources == ["Loopback2"]
        assert _recorded(result.taken) == _gone(before, tree)

    def test_two_routes_to_one_destination_are_two(self) -> None:
        ios = get_codec("cisco_iosxe_cli")
        tree = ios.parse(_IOS_ROUTE + "ip route 10.50.0.0 255.255.0.0 GigabitEthernet1/0/30 10.0.100.253\n")
        before, result = _translate(
            "cisco_iosxe_cli", "arista_eos", tree, {"GigabitEthernet1/0/30": None},
        )
        assert result.taken.lost_routes == ["10.50.0.0/16", "10.50.0.0/16"]
        assert _recorded(result.taken) == _gone(before, tree)

    def test_a_merge_moves_a_lag_another_drop_emptied(self) -> None:
        taken = TakenWithDrops(shrunk_lags=["Po1"], lost_routes=["10.0.0.0/8"])
        taken.add(TakenWithDrops(emptied_lags=["Po1"], lost_routes=["10.0.0.0/8"]))
        assert (taken.shrunk_lags, taken.emptied_lags) == ([], ["Po1"])
        assert taken.lost_routes == ["10.0.0.0/8", "10.0.0.0/8"]

    def test_every_source_codec_is_pinned(self) -> None:
        assert set(_RECORDS) == set(CAPTURES)

    @pytest.mark.parametrize("codec_name", sorted(CAPTURES))
    def test_every_committed_capture(self, codec_name: str) -> None:
        """Onto every public codec, with no entry: the record against
        what is gone from the tree.  How many jobs record something is
        pinned, so that a sweep which compares only empty records
        cannot pass for one that compared something."""
        source = get_codec(codec_name)
        compared = 0
        for path in CAPTURES[codec_name]:
            parsed = source.parse(path.read_text(encoding="utf-8", errors="replace"))
            for target_name in list_public_codecs():
                tree = copy.deepcopy(parsed)
                before, result = _translate(codec_name, target_name, tree)
                where = f"{path.parent.name}/{path.name} -> {target_name}"
                assert _recorded(result.taken) == _gone(before, tree), where
                compared += any(getattr(result.taken, f) for f in TakenWithDrops.model_fields)
        assert compared == _RECORDS[codec_name]


#: Jobs of the sweep above whose record holds something, by source
#: codec: every committed capture onto every public codec, with no
#: entry, so every drop is the translator's.  Measured, and pinned:
#: a number that moves is a drop that took something, or stopped.
_RECORDS = {
    # 3, from 2: the 7050SX3-48YC8 capture's VTEP source is
    # `Loopback1`, which Junos has no name for, as the two EVPN
    # captures' already was.
    "arista_eos": 3,
    "aruba_aoscx": 6,
    "aruba_aoss": 0,
    "cisco_iosxe_cli": 9,
    "cisco_iosxr": 0,
    "cisco_nxos": 4,
    "dell_os10": 3,
    "fortigate_cli": 4,
    "juniper_junos": 0,
    "mikrotik_routeros": 0,
    "opnsense": 0,
    "vyos": 0,
}


class TestTheOracleFails:
    """Each check handed the defect it is for."""

    def test_a_record_left_empty(self) -> None:
        tree = get_codec("cisco_iosxe_cli").parse(LEAF.read_text(encoding="utf-8"))
        before, _ = _translate("cisco_iosxe_cli", "juniper_junos", tree)
        assert _recorded(TakenWithDrops()) != _gone(before, tree)

    def test_a_strip_that_records_nothing(self, monkeypatch) -> None:
        monkeypatch.setattr(port_names, "_what_goes", lambda *_: TakenWithDrops())
        tree = get_codec("cisco_iosxe_cli").parse(_IOS_ROUTE)
        before, result = _translate(
            "cisco_iosxe_cli", "arista_eos", tree, {"GigabitEthernet1/0/30": None},
        )
        assert _recorded(result.taken) != _gone(before, tree)
        job = _checked(
            "cisco_iosxe_cli", "arista_eos", _IOS_ROUTE, {"GigabitEthernet1/0/30": None},
        )
        assert _what_went(job) == []

    def test_a_record_of_what_stayed(self, monkeypatch) -> None:
        """A record of a route the strip did not remove."""
        real = port_names._what_goes

        def more(intent, dropped, named):
            taken = real(intent, dropped, named)
            taken.lost_routes.append("10.60.0.0/16")
            return taken

        monkeypatch.setattr(port_names, "_what_goes", more)
        tree = get_codec("cisco_iosxe_cli").parse(_IOS_ROUTE)
        before, result = _translate(
            "cisco_iosxe_cli", "arista_eos", tree, {"GigabitEthernet1/0/30": None},
        )
        assert _recorded(result.taken) != _gone(before, tree)


# ---------------------------------------------------------------------------
# The job says it
# ---------------------------------------------------------------------------


class TestTheJobSaysIt:
    def test_a_route(self) -> None:
        job = _checked(
            "cisco_iosxe_cli", "arista_eos", _IOS_ROUTE, {"GigabitEthernet1/0/30": None},
        )
        assert "10.50.0.0" not in job.rendered
        assert _what_went(job) == [
            "port_rename: 1 static route(s) that named a dropped interface "
            "were removed with it: 10.50.0.0/16",
        ]

    def test_a_pool(self) -> None:
        job = _checked("fortigate_cli", "cisco_iosxe_cli", _FGT_POOL, {"internal1": None})
        assert "10.1.0.10" not in job.rendered
        assert _what_went(job) == [
            "port_rename: 1 DHCP pool(s) bound to a dropped interface "
            "were removed with it: 10.1.0.0/24",
        ]

    def test_a_lag(self) -> None:
        job = _checked(
            "cisco_iosxe_cli", "arista_eos", _IOS_LAG, {
                "GigabitEthernet1/0/1": None, "GigabitEthernet1/0/2": None,
            },
        )
        assert _what_went(job) == [
            "port_rename: every member port of 1 LAG(s) was dropped, so the "
            "LAG has no port on the target (Port-channel1); review it and "
            "the VLANs that reference it",
        ]

    def test_a_track_entry(self) -> None:
        job = _checked("arista_eos", "cisco_iosxe_cli", _EOS_TRACK, {"Ethernet2": None})
        assert "track" not in job.rendered
        assert _what_went(job) == [
            "port_rename: 1 interface(s) lost a VRRP track entry with what it "
            "named (a dropped interface, or a track object number read as "
            "one), so failover no longer follows it: Ethernet1",
        ]

    def test_the_vtep_source_the_translator_dropped(self) -> None:
        """The case the known limitation named."""
        job = _checked("cisco_iosxe_cli", "juniper_junos", LEAF.read_text(encoding="utf-8"))
        assert job.status == MigrationJobStatus.partial
        assert "Loopback2" in job.unresolved_ports
        assert "vtep-source-interface" not in job.rendered
        assert _what_went(job) == [
            "port_rename: the VXLAN source interface was dropped (Loopback2), "
            "so the VTEP is left without the source it was bound to — give it one",
        ]

    def test_no_drop_says_nothing(self) -> None:
        job = _checked("cisco_iosxe_cli", "arista_eos", _IOS_ROUTE)
        assert job.port_drops == [] and _what_went(job) == []

    def test_a_status_is_not_changed_by_it(self) -> None:
        """An operator's drop is the operator's to decide: what went
        with it is said, and the job is not held for it."""
        job = _checked(
            "cisco_iosxe_cli", "arista_eos", _IOS_ROUTE, {"GigabitEthernet1/0/30": None},
        )
        assert job.status == MigrationJobStatus.completed

    def test_no_quoted_name(self) -> None:
        """The migrate page reads a quoted name out of a warning as a
        row of its rename table."""
        job = _checked("cisco_iosxe_cli", "juniper_junos", LEAF.read_text(encoding="utf-8"))
        for line in _what_went(job):
            assert "'" not in line


class TestWithDevices:
    def test_the_plan_says_it_and_the_job_says_it_once(self) -> None:
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_models(
            ios, ios, _IOS_ROUTE,
            inventory_from_profile(PROFILES["cisco_iosxe/C9300-48P"], None),
            inventory_from_profile(PROFILES["cisco_iosxe/C9300-24P"], None),
        )
        assert job.port_drops == ["GigabitEthernet1/0/30"]
        assert job.port_mapping_plan.lost_routes == ["10.50.0.0/16"]
        (line,) = [w for w in job.warnings if "static route(s)" in w]
        assert line.startswith("port mapping: ")
        assert _what_went(job) == []
