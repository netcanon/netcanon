"""Positional port mapping — pairing two inventories into a rename map.

Runs on hand-built inventories so the POLICY is pinned independently of
any model data: what pairs with what, what is left unplaced, and what
the plan tells the translator to do with each.  The end-to-end case on
a real capture is in ``tests/unit/services/``.
"""

from __future__ import annotations

import pytest

from netcanon.migration.device_models import Inventory, PhysicalPort
from netcanon.migration.port_mapping import (
    MappingPlan,
    describe_plan,
    fused_targets,
    name_key,
    plan_port_mapping,
    settle_plan,
)

pytestmark = pytest.mark.unit


def _inventory(
    *groups: tuple[int, str, list[str]],
    description: str = "",
    evidence: str | None = "vendor-doc",
    caveats: list[str] | None = None,
    speed: dict[str, str] | None = None,
    poe: set[str] | None = None,
    origin: str = "family",
) -> Inventory:
    """``(member_rank, role, names)`` groups, in port-number order."""
    ports: list[PhysicalPort] = []
    for rank, role, names in groups:
        for ordinal, name in enumerate(names):
            ports.append(PhysicalPort(
                name=name, member_rank=rank, role=role, ordinal=ordinal,
                speed=(speed or {}).get(name, ""), poe=name in (poe or set()),
                evidence=evidence,
            ))
    return Inventory(
        vendor="x", origin=origin, description=description, ports=ports,
        port_count=len(ports),
        evidence=evidence if ports else None, caveats=caveats or [],
    )


def _bare(count: int, start: int = 1) -> list[str]:
    return [str(n) for n in range(start, start + count)]


STANDALONE_48 = _inventory(
    (0, "access", _bare(48)), (0, "uplink", _bare(4, 49)),
    description="standalone 48 + 4",
)
STANDALONE_24 = _inventory(
    (0, "access", _bare(24)), (0, "uplink", _bare(4, 25)),
    description="standalone 24 + 4",
)
STACKED_48_MODULE = _inventory(
    (0, "access", [f"1/{n}" for n in range(1, 49)]),
    (0, "uplink", ["1/A1", "1/A2", "1/A3", "1/A4"]),
    description="stacked 48 + module",
)
STACKED_24_MODULE = _inventory(
    (0, "access", [f"1/{n}" for n in range(1, 25)]),
    (0, "uplink", ["1/A1", "1/A2", "1/A3", "1/A4"]),
    description="stacked 24 + module",
)


class TestPairing:
    def test_access_pairs_with_access_and_uplink_with_uplink(self):
        """The whole point: source uplink ``49`` goes to the target's
        FIRST uplink, ``1/A1`` — not to ``1/49``, which the target does
        not have."""
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE)
        assert plan.rename_map["1"] == "1/1"
        assert plan.rename_map["48"] == "1/48"
        assert [plan.rename_map[n] for n in ("49", "50", "51", "52")] == [
            "1/A1", "1/A2", "1/A3", "1/A4",
        ]
        assert len(plan.rename_map) == 52
        assert plan.applied and plan.is_clean
        assert plan.warnings == []
        assert plan.unused_target == []

    def test_pairings_keep_source_order_and_coordinates(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE)
        assert [p.source for p in plan.pairings] == _bare(52)
        uplink = plan.pairings[48]
        assert (uplink.source, uplink.target) == ("49", "1/A1")
        assert (uplink.role, uplink.member_rank, uplink.position) == ("uplink", 0, 0)

    def test_it_runs_both_ways(self):
        plan = plan_port_mapping(STACKED_48_MODULE, STANDALONE_48)
        assert plan.rename_map["1/A1"] == "49"
        assert plan.rename_map["1/24"] == "24"

    def test_same_names_on_both_sides_are_pinned_not_omitted(self):
        """An identity pair still goes in the map: an explicit entry
        stops the name-shape translator re-deciding a name the model
        data has already settled."""
        plan = plan_port_mapping(STANDALONE_48, STANDALONE_48)
        assert plan.rename_map["7"] == "7"
        assert len(plan.rename_map) == 52

    def test_position_is_computed_not_read_from_a_stored_ordinal(self):
        """Two inventories need not number the same ports.  Pairing is
        the k-th port of a role with the k-th, whatever ``ordinal`` each
        side stored."""
        odd = Inventory(vendor="x", evidence="vendor-doc", ports=[
            PhysicalPort(name="u1", member_rank=0, role="uplink", ordinal=7),
            PhysicalPort(name="u2", member_rank=0, role="uplink", ordinal=9),
        ])
        plain = _inventory((0, "uplink", ["A1", "A2"]))
        assert plan_port_mapping(plain, odd).rename_map == {"A1": "u1", "A2": "u2"}

    def test_descriptions_carry_through(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE)
        assert plan.source.description == "standalone 48 + 4"
        assert plan.target.description == "stacked 48 + module"
        assert (plan.source.port_count, plan.target.port_count) == (52, 52)


class TestOrder:
    def test_pairings_are_in_the_source_devices_port_order(self):
        """A FortiGate 100E lists WAN, DMZ, management and HA ports
        before its numbered ports: roles interleave.  The plan lists
        its pairings as the device lists its ports, not role by role."""
        source = _inventory(
            (0, "uplink", ["wan1"]), (0, "access", ["dmz"]),
            (0, "uplink", ["wan2"]), (0, "access", ["port1"]),
        )
        target = _inventory((0, "access", ["a1", "a2"]), (0, "uplink", ["u1", "u2"]))
        plan = plan_port_mapping(source, target)
        assert [p.source for p in plan.pairings] == ["wan1", "dmz", "wan2", "port1"]
        assert [p.target for p in plan.pairings] == ["u1", "a1", "u2", "a2"]


class TestUnplaced:
    def test_overflow_is_reported_per_port_and_never_spilled(self):
        """A 48-port source onto a 24-port target: ports 25-48 have
        nowhere to go.  They must not land on a spare uplink."""
        plan = plan_port_mapping(STANDALONE_48, STACKED_24_MODULE)
        assert [p.source for p in plan.unplaced] == _bare(24, 25)
        assert {p.reason for p in plan.unplaced} == {"no-position"}
        assert {p.role for p in plan.unplaced} == {"access"}
        # The uplinks still pair — overflow in one role does not shift another.
        assert plan.rename_map["49"] == "1/A1"
        assert plan.unused_target == []
        assert not plan.is_clean

    def test_an_unplaced_port_is_dropped_explicitly(self):
        """Never "no entry": a port left to the name-shape translator
        keeps its old name on a same-vendor pair, and that name may be
        one another port was just mapped onto."""
        plan = plan_port_mapping(STANDALONE_48, STACKED_24_MODULE)
        assert plan.rename_map["25"] is None
        assert plan.rename_map["48"] is None
        assert plan.rename_map["24"] == "1/24"
        assert set(plan.rename_map) == set(_bare(52))

    def test_the_plans_own_map_never_puts_two_ports_on_one_name(self):
        """48 + 4 onto a standalone 24 + 4: source uplink ``49`` lands
        on target port ``25``.  Source access port ``25`` has no
        position.  If it were merely left out of the map it would stay
        ``25`` — the same name — and the two would be fused.

        This is the map the plan itself decides.  A name the plan
        leaves to the name-shape translator is checked after the run
        (``TestSettlePlan``, and every job in
        ``test_run_plan_with_models.py``)."""
        plan = plan_port_mapping(STANDALONE_48, STANDALONE_24)
        assert plan.rename_map["49"] == "25"
        assert plan.rename_map["25"] is None
        kept = [t for t in plan.rename_map.values() if t is not None]
        assert len(kept) == len(set(kept)) == 28

    def test_the_warning_names_the_role_and_the_ports(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_24_MODULE)
        assert len(plan.warnings) == 1
        assert "24 source access port(s)" in plan.warnings[0]
        assert "DROPPED" in plan.warnings[0]
        assert "25, 26" in plan.warnings[0] and "and 16 more" in plan.warnings[0]

    def test_a_role_the_target_lacks_is_unplaced_not_reassigned(self):
        no_uplinks = _inventory((0, "access", [f"1/{n}" for n in range(1, 49)]))
        plan = plan_port_mapping(STANDALONE_48, no_uplinks)
        assert [p.source for p in plan.unplaced] == ["49", "50", "51", "52"]
        assert "4 source uplink port(s)" in plan.warnings[0]

    def test_a_source_member_beyond_the_target_is_not_folded(self):
        two = _inventory(
            (0, "access", ["1/1", "1/2"]), (1, "access", ["2/1", "2/2"]),
        )
        one = _inventory((0, "access", ["1", "2", "3", "4"]))
        plan = plan_port_mapping(two, one)
        assert plan.rename_map == {"1/1": "1", "1/2": "2", "2/1": None, "2/2": None}
        assert [(p.source, p.reason) for p in plan.unplaced] == [
            ("2/1", "no-member"), ("2/2", "no-member"),
        ]
        assert plan.unused_target == ["3", "4"]
        assert "a member the target does not have" in plan.warnings[0]

    def test_members_pair_by_rank_not_by_vendor_id(self):
        """A lone member that calls itself 3 is still the first member."""
        lone_three = _inventory((0, "access", ["3/1", "3/2"]))
        target = _inventory((0, "access", ["1/1", "1/2"]))
        plan = plan_port_mapping(lone_three, target)
        assert plan.rename_map == {"3/1": "1/1", "3/2": "1/2"}

    def test_spare_target_ports_are_listed(self):
        plan = plan_port_mapping(STACKED_24_MODULE, STANDALONE_48)
        assert plan.unused_target == _bare(24, 25)
        assert plan.is_clean


class TestManagementPorts:
    """An unplaced management port is not dropped by the plan.  The
    name-shape translator turns a source management port into what
    the target uses for out-of-band management (the ``oobm`` block
    on AOS-S); deleting it would be a regression against a run with
    no models declared.  But whether the target HAS a management
    interface is not something the plan knows, so the port needs
    the operator's eye like any other the plan could not place."""

    SOURCE = _inventory((0, "access", ["Gi1/0/1"]), (0, "mgmt", ["Gi0/0"]))

    def test_it_is_left_to_the_name_shape_translator(self):
        plan = plan_port_mapping(self.SOURCE, _inventory((0, "access", ["1/1"])))
        assert plan.rename_map == {"Gi1/0/1": "1/1"}
        (port,) = plan.unplaced
        assert (port.source, port.role, port.dropped) == ("Gi0/0", "mgmt", False)
        assert plan.used_dropped == []

    def test_it_needs_a_decision_like_any_port_without_a_place(self):
        """A 2930F has no out-of-band port at all; rendering an
        ``oobm`` block for one and calling the job complete would be
        a quiet wrong answer."""
        plan = plan_port_mapping(self.SOURCE, _inventory((0, "access", ["1/1"])))
        assert not plan.is_clean
        assert plan.unresolved() == ["Gi0/0"]
        assert plan.unresolved({"Gi0/0"}) == []
        assert plan.warnings == [
            "port mapping: 1 source management port(s) have no management "
            "port in the target model and are left to name-shape "
            "translation (Gi0/0); confirm the target has a management "
            "interface, or drop them",
        ]

    def test_it_pairs_when_the_target_has_one(self):
        target = _inventory((0, "access", ["Eth1"]), (0, "mgmt", ["Management1"]))
        plan = plan_port_mapping(self.SOURCE, target)
        assert plan.rename_map == {"Gi1/0/1": "Eth1", "Gi0/0": "Management1"}
        assert plan.unplaced == [] and plan.warnings == []


class TestUsedNames:
    def test_only_used_ports_are_problems(self):
        """A 48-port source that uses 20 ports fits a 24-port target."""
        used = [*_bare(20), "49", "50"]
        plan = plan_port_mapping(STANDALONE_48, STACKED_24_MODULE, used)
        assert plan.is_clean
        assert plan.warnings == []
        assert sorted(plan.rename_map) == sorted(used)
        assert len(plan.used_pairings) == 22
        # The unused overflow is still on the plan, marked as such.
        assert [p.source for p in plan.unplaced if not p.used] == _bare(24, 25)
        assert plan.used_unplaced == []

    def test_the_map_names_no_port_the_config_does_not_use(self):
        """The translator warns about a rename entry for a port that is
        not in the config, so the map is limited to what is used."""
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE, ["3", "49"])
        assert plan.rename_map == {"3": "1/3", "49": "1/A1"}

    def test_a_used_overflow_port_is_a_problem(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_24_MODULE, ["1", "30"])
        assert plan.rename_map == {"1": "1/1", "30": None}
        assert [p.source for p in plan.used_unplaced] == ["30"]
        assert "30" in plan.warnings[0]

    def test_a_used_name_the_source_model_lacks_is_off_inventory(self):
        """The tripwire for a wrongly declared source model: the config
        uses ``A1`` and the declared source has no module slot."""
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE, ["1", "A1", "1/7"])
        assert plan.off_inventory == ["1/7", "A1"]
        assert "A1" not in plan.rename_map and "1/7" not in plan.rename_map
        assert plan.rename_map == {"1": "1/1"}
        assert not plan.is_clean
        assert "not ports of the declared source device" in plan.warnings[0]
        assert "check the source model" in plan.warnings[0]
        assert plan.unresolved_ports == ["1/7", "A1"]

    def test_no_used_names_means_everything_is_used(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE)
        assert plan.off_inventory == []
        assert all(p.used for p in plan.pairings)

    def test_an_empty_config_uses_nothing(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_24_MODULE, [])
        assert plan.rename_map == {}
        assert plan.is_clean and plan.warnings == []


class TestNotModelled:
    """A profile that lists no ports is "not modelled", not "a device
    with no ports".  Under a total mapping the second reading would
    drop every port in the config."""

    @pytest.mark.parametrize(
        ("source", "target", "who"),
        [
            (STANDALONE_48, _inventory(), "target"),
            (_inventory(), STANDALONE_48, "source"),
            (_inventory(), _inventory(), "source and the target"),
        ],
    )
    def test_nothing_is_paired_and_nothing_is_dropped(self, source, target, who):
        plan = plan_port_mapping(source, target, ["1", "2"])
        assert not plan.applied
        assert plan.rename_map == {}
        assert plan.pairings == [] and plan.unplaced == []
        assert not plan.is_clean
        assert f"the {who} device lists no ports" in plan.warnings[0]


class TestSpeedAndPower:
    def test_a_faster_source_port_on_a_slower_target_port_is_flagged(self):
        source = _inventory((0, "uplink", ["49"]), speed={"49": "10gig"})
        target = _inventory((0, "uplink", ["1/A1"]), speed={"1/A1": "gig"})
        plan = plan_port_mapping(source, target)
        pairing = plan.pairings[0]
        assert pairing.slower
        assert (pairing.source_speed, pairing.target_speed) == ("10gig", "gig")
        assert "land on a slower target port: 49 -> 1/A1" in plan.warnings[0]
        # Flagged, still mapped — it is the right port, at a lower speed.
        assert plan.rename_map == {"49": "1/A1"}

    @pytest.mark.parametrize(
        ("source_speed", "target_speed"),
        [("gig", "10gig"), ("gig", "gig"), ("", "gig"), ("10gig", ""), ("odd", "gig")],
    )
    def test_no_flag_without_a_stated_downshift(self, source_speed, target_speed):
        """An unstated or unrecognised speed is unknown — it is never
        treated as a match AND never as a downshift."""
        source = _inventory((0, "access", ["1"]), speed={"1": source_speed})
        target = _inventory((0, "access", ["1/1"]), speed={"1/1": target_speed})
        plan = plan_port_mapping(source, target)
        assert not plan.pairings[0].slower
        assert plan.warnings == []

    def test_poe_onto_a_port_without_poe_is_flagged(self):
        source = _inventory((0, "access", ["1", "2"]), poe={"1", "2"})
        target = _inventory((0, "access", ["1/1", "1/2"]), poe={"1/2"})
        plan = plan_port_mapping(source, target)
        assert [p.poe_lost for p in plan.pairings] == [True, False]
        assert "1 PoE port(s) land on a target port without PoE: 1 -> 1/1" in plan.warnings[0]

    def test_an_unused_port_raises_no_speed_or_power_warning(self):
        source = _inventory((0, "access", ["1", "2"]), poe={"1", "2"})
        target = _inventory((0, "access", ["1/1", "1/2"]))
        plan = plan_port_mapping(source, target, ["9"])
        assert len(plan.warnings) == 1
        assert "not ports of the declared source device (9)" in plan.warnings[0]


class TestEvidence:
    @pytest.mark.parametrize(
        ("source", "target", "expected"),
        [
            ("capture", "capture", "capture"),
            ("capture", "vendor-doc", "vendor-doc"),
            ("inferred", "capture", "inferred"),
            ("capture", None, None),
            (None, "inferred", None),
        ],
    )
    def test_a_plan_is_as_good_as_its_weaker_side(self, source, target, expected):
        """Ungraded is weaker than every grade — it is not skipped."""
        plan = plan_port_mapping(
            _inventory((0, "access", ["1"]), evidence=source),
            _inventory((0, "access", ["1/1"]), evidence=target),
        )
        assert plan.evidence == expected
        assert plan.pairings[0].evidence == expected

    def test_each_pairing_carries_its_own_grade(self):
        """Forty-eight captured ports and four inferred ones are not
        fifty-two doubtful ports."""
        source = _inventory((0, "access", ["1"]), (0, "uplink", ["49"]), evidence="capture")
        target = Inventory(vendor="x", evidence="inferred", ports=[
            PhysicalPort(name="1/1", member_rank=0, role="access", ordinal=0,
                         evidence="capture"),
            PhysicalPort(name="1/A1", member_rank=0, role="uplink", ordinal=0,
                         evidence="inferred"),
        ])
        plan = plan_port_mapping(source, target)
        assert [p.evidence for p in plan.pairings] == ["capture", "inferred"]
        assert plan.evidence == "inferred"

    def test_caveats_of_both_sides_are_kept_once(self):
        plan = plan_port_mapping(
            _inventory((0, "access", ["1"]), caveats=["shared", "source only"]),
            _inventory((0, "access", ["1/1"]), caveats=["shared", "target only"]),
        )
        assert plan.caveats == ["shared", "source only", "target only"]

    def test_a_legacy_profiles_order_is_flagged_as_unvouched(self):
        """A flat target profile lists ports in YAML order.  Pairing a
        switch's port 1 with whatever a firewall profile happens to
        list first is a starting point, and the plan says so."""
        legacy = _inventory((0, "access", ["dmz", "ha1"]), origin="legacy-profile")
        plan = plan_port_mapping(_inventory((0, "access", ["1", "2"])), legacy)
        assert plan.rename_map == {"1": "dmz", "2": "ha1"}
        assert any(
            "the target port order is the list order of a target profile" in w
            for w in plan.warnings
        )
        assert not any(
            "list order" in w for w in
            plan_port_mapping(STANDALONE_48, STACKED_48_MODULE).warnings
        )


class TestPlanIsSafeToPutOnAJob:
    def test_the_plan_is_plain_data(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_24_MODULE)
        assert MappingPlan.model_validate(plan.model_dump()).rename_map == plan.rename_map

    def test_no_warning_puts_a_port_name_in_single_quotes(self):
        """The migrate page turns any single-quoted token in a job
        warning into an extra row of its rename table.  A mapper
        warning that quoted port names would grow the table by one
        bogus row per name."""
        plans = [
            plan_port_mapping(STANDALONE_48, STACKED_24_MODULE),
            plan_port_mapping(STANDALONE_48, STACKED_48_MODULE, ["1", "A1"]),
            plan_port_mapping(STANDALONE_48, _inventory()),
            plan_port_mapping(
                _inventory((0, "access", ["1"]), speed={"1": "10gig"}, poe={"1"}),
                _inventory((0, "access", ["x"]), speed={"x": "gig"}, origin="legacy-profile"),
            ),
        ]
        warnings = [w for plan in plans for w in plan.warnings]
        assert len(warnings) >= 6
        assert not [w for w in warnings if "'" in w]


class TestRepeatedNames:
    def test_an_inventory_that_lists_a_name_twice_is_not_paired(self):
        """A position is only a port when each name occurs once.  An
        operator's own profile can list an id twice; pairing it would
        send two source ports to one target name without a word."""
        twice = _inventory((0, "access", ["1", "2", "2"]))
        for source, target, side in (
            (STANDALONE_48, twice, "target"), (twice, STANDALONE_48, "source"),
        ):
            plan = plan_port_mapping(source, target)
            assert not plan.applied
            assert plan.rename_map == {}
            assert f"the {side} device lists a port name more than once (2)" in (
                plan.warnings[0]
            )

    def test_two_spellings_of_one_name_are_a_repeat(self):
        plan = plan_port_mapping(STANDALONE_48, _inventory((0, "access", ["1/A1", "1/a1"])))
        assert not plan.applied


class TestFusedTargets:
    """Read from what a run reports -- whoever decided each name."""

    def test_two_sources_on_one_target(self):
        assert fused_targets(["a", "b", "c"], {"a": "x", "b": "x"}, []) == {
            "x": ["a", "b"],
        }

    def test_a_name_that_was_not_renamed_stands_for_itself(self):
        """``port_renames`` holds only names that changed."""
        assert fused_targets(["25", "49"], {"49": "25"}, []) == {"25": ["25", "49"]}

    def test_a_dropped_source_holds_no_target(self):
        assert fused_targets(["25", "49"], {"49": "25"}, ["25"]) == {}

    def test_distinct_targets_are_not_fused(self):
        assert fused_targets(["a", "b"], {"a": "x", "b": "y"}, []) == {}

    @pytest.mark.parametrize("spelling", ["1/a1", " 1/A1", "1/A1 ", "1/A1"])
    def test_a_target_is_the_same_port_in_any_case_and_spacing(self, spelling):
        """An override typed ``1/a1`` lands on the port ``1/A1``.  Compared
        as exact strings the two would be different targets, and two
        source ports on one physical port would go unseen."""
        fused = fused_targets(["49", "50"], {"49": "1/A1", "50": spelling}, [])
        assert list(fused.values()) == [["49", "50"]]
        assert [name_key(target) for target in fused] == ["1/a1"]

    def test_two_spellings_of_one_source_are_not_two_ports(self):
        """AOS-S prints a trunk as ``trk1`` where it is defined and
        ``Trk1`` in a VLAN list.  One LAG, not a fusion of two."""
        assert fused_targets(["trk1", "Trk1"], {}, []) == {}

    def test_a_name_given_twice_is_one_name(self):
        assert fused_targets(["7", "7"], {}, []) == {}

    def test_where_case_is_part_of_a_name_two_spellings_are_two_names(self):
        """FortiOS: ``dmz`` is a port and ``DMZ`` a VLAN interface.
        An entry that sends ``DMZ`` to ``dmz`` puts two interfaces on
        one name.  Folded together as one source, the pair had one
        member and the fusion went unreported."""
        names, renames = ["dmz", "DMZ"], {"DMZ": "dmz"}
        assert fused_targets(names, renames, []) == {}
        assert fused_targets(
            names, renames, [], fold_source=False, fold_target=False,
        ) == {"dmz": ["dmz", "DMZ"]}
        # ...and left alone, they are two names on two targets.
        assert fused_targets(names, {}, [], fold_source=False, fold_target=False) == {}

    def test_the_two_sides_fold_separately(self):
        """A case-sensitive source onto a target that is not: ``A``
        and ``a`` are two source interfaces, and ``X`` and ``x`` one
        target."""
        assert fused_targets(
            ["A", "a"], {"A": "X", "a": "x"}, [], fold_source=False,
        ) == {"X": ["A", "a"]}

    def test_the_key_keeps_case_only_when_told_to(self):
        assert name_key(" 1/A1 ") == "1/a1"
        assert name_key(" 1/A1 ", fold=False) == "1/A1"

    def test_only_a_clash_that_involves_a_hardware_port_when_asked(self):
        """Every name the config references goes in, logical ones
        included -- an aggregate the translator calls physical lands on
        a physical port's name.  Two LAGs that clash with each other
        are the translator's own business."""
        names = ["dmz", "fortilink", "Po1", "Po2"]
        renames = {"dmz": "Ethernet1", "fortilink": "Ethernet1", "Po1": "Trk1", "Po2": "Trk1"}
        assert fused_targets(names, renames, []) == {
            "Ethernet1": ["dmz", "fortilink"], "Trk1": ["Po1", "Po2"],
        }
        assert fused_targets(names, renames, [], involving=["dmz"]) == {
            "Ethernet1": ["dmz", "fortilink"],
        }


def _settled(plan: MappingPlan, used, *, renames=None, drops=(), operator=None,
             target=STACKED_24_MODULE, every=None, **outcome) -> MappingPlan:
    """Settle *plan* against a run that did what the merged map says,
    plus whatever *renames* and *drops* add on top."""
    operator = operator or {}
    merged = {**plan.rename_map, **operator}
    port_renames = {s: t for s, t in merged.items() if t is not None and t != s}
    port_renames.update(renames or {})
    port_drops = sorted({s for s, t in merged.items() if t is None} | set(drops))
    settle_plan(
        plan,
        operator_map=operator,
        used_names=list(used),
        every_name=list(every if every is not None else used),
        port_renames=port_renames,
        port_drops=port_drops,
        target_names=target.names(),
        **outcome,
    )
    return plan


class TestSettlePlan:
    """A plan states an intention; ``settle_plan`` makes its flags and
    warnings describe what the run did."""

    USED = _bare(52)

    def _plan(self) -> MappingPlan:
        return plan_port_mapping(STANDALONE_48, STACKED_24_MODULE, self.USED)

    def test_an_unsettled_plan_already_lists_what_needs_a_decision(self):
        assert self._plan().unresolved_ports == _bare(24, 25)

    def test_nothing_overridden_changes_nothing(self):
        before = self._plan()
        after = _settled(self._plan(), self.USED)
        assert after.warnings == before.warnings
        assert after.unresolved_ports == _bare(24, 25)
        assert (after.overridden, after.displaced, after.fused, after.off_target) == (
            [], [], {}, [],
        )
        assert after.unused_target == before.unused_target == []

    def test_an_acknowledged_drop_is_resolved_and_not_warned_about(self):
        plan = _settled(self._plan(), self.USED, operator=dict.fromkeys(_bare(24, 25)))
        assert plan.unresolved_ports == [] and plan.is_clean
        assert plan.overridden == sorted(_bare(24, 25))
        assert plan.warnings == []
        assert {p.dropped for p in plan.unplaced} == {True}

    def test_an_unplaced_port_the_operator_placed_was_not_dropped(self):
        """The plan would have dropped port 25; the operator gave it a
        target.  The plan must not go on saying it was dropped."""
        plan = _settled(self._plan(), self.USED, operator={"25": "1/A4", "52": None})
        kept = next(p for p in plan.unplaced if p.source == "25")
        assert (kept.dropped, kept.landed) == (False, "1/A4")
        assert "25" not in plan.unresolved_ports
        (line,) = [w for w in plan.warnings if "were DROPPED" in w]
        assert "23 source access port(s)" in line and "26, 27" in line

    def test_the_pairing_is_kept_as_made_and_overridden_says_which_moved(self):
        """``pairings`` and ``rename_map`` are the pairing before the
        operator's map.  A client that draws the final mapping from
        them shows a port where it did not go -- ``overridden`` is what
        tells it which rows are stale."""
        plan = _settled(self._plan(), self.USED, operator={"49": "1/A4", "52": None})
        assert plan.rename_map["49"] == "1/A1"
        assert next(p for p in plan.pairings if p.source == "49").target == "1/A1"
        assert plan.overridden == ["49", "52"]

    def test_unused_target_is_what_is_free_after_the_run(self):
        """Port 49 was moved off ``1/A1`` onto ``1/A4`` and 52 dropped:
        ``1/A1`` is free now, and ``1/A4`` is not."""
        plan = _settled(self._plan(), self.USED, operator={"49": "1/A4", "52": None})
        assert plan.unused_target == ["1/A1"]

    def test_a_management_port_the_translator_dropped_is_reported_as_dropped(self):
        source = _inventory((0, "access", ["Eth1"]), (0, "mgmt", ["Management1"]))
        target = _inventory((0, "access", ["ether1"]))
        plan = plan_port_mapping(source, target, ["Eth1", "Management1"])
        assert not plan.unplaced[0].dropped
        _settled(plan, ["Eth1", "Management1"], drops=["Management1"], target=target)
        assert plan.unplaced[0].dropped and plan.unplaced[0].landed == ""
        assert plan.unresolved_ports == ["Management1"]
        assert not plan.is_clean
        (line,) = plan.warnings
        assert "1 source management port(s)" in line and "DROPPED" in line
        assert "name-shape translation" not in line

    def test_a_management_port_the_translator_kept_says_where_it_went(self):
        source = _inventory((0, "access", ["Gi1/0/1"]), (0, "mgmt", ["Gi0/0"]))
        target = _inventory((0, "access", ["1/1"]))
        used = ["Gi1/0/1", "Gi0/0"]
        plan = plan_port_mapping(source, target, used)
        _settled(plan, used, renames={"Gi0/0": "oobm"}, target=target)
        assert (plan.unplaced[0].dropped, plan.unplaced[0].landed) == (False, "oobm")
        assert plan.unresolved_ports == ["Gi0/0"] and not plan.is_clean
        assert "were kept by name-shape translation (Gi0/0 -> oobm)" in plan.warnings[0]

    def test_naming_a_kept_management_port_is_the_decision(self):
        """...and sending it to ``oobm`` is not "a target the device
        lacks": the target model lists no management port, so there is
        no inventory name the operator could have chosen instead."""
        source = _inventory((0, "access", ["Gi1/0/1"]), (0, "mgmt", ["Gi0/0"]))
        target = _inventory((0, "access", ["1/1"]))
        used = ["Gi1/0/1", "Gi0/0"]
        plan = plan_port_mapping(source, target, used)
        _settled(plan, used, operator={"Gi0/0": "oobm"}, target=target,
                 management_forms={"Gi0/0": "oobm"})
        assert plan.unresolved_ports == [] and plan.is_clean
        assert plan.off_target == [] and plan.warnings == []

    def test_any_other_name_for_it_is_as_off_target_as_for_any_port(self):
        """The exemption is for the one name the target vendor gives
        a management port, not for whatever is typed."""
        source = _inventory((0, "access", ["Gi1/0/1"]), (0, "mgmt", ["Gi0/0"]))
        target = _inventory((0, "access", ["1/1"]))
        used = ["Gi1/0/1", "Gi0/0"]
        for typed in ("Gi0/0", "OOBM2"):
            plan = plan_port_mapping(source, target, used)
            _settled(plan, used, operator={"Gi0/0": typed}, target=target,
                     management_forms={"Gi0/0": "oobm"})
            assert plan.off_target == [typed]
        plan = plan_port_mapping(source, target, used)
        _settled(plan, used, operator={"Gi0/0": "oobm"}, target=target)
        assert plan.off_target == ["oobm"]

    def test_a_displaced_name_is_unresolved_whoever_asks(self):
        plan = plan_port_mapping(STANDALONE_24, STANDALONE_48, [*_bare(28), "49"])
        assert plan.off_inventory == ["49"]
        _settled(plan, [*_bare(28), "49"], drops=["49"], target=STANDALONE_48,
                 displaced=["49"])
        assert plan.displaced == ["49"]
        assert plan.unresolved_ports == ["49"]
        assert plan.unresolved({"49"}) == ["49"]
        assert not plan.is_clean
        (line,) = plan.warnings
        assert "1 name(s) nobody decided" in line and "DROPPED" in line
        # ...and it is not reported a second time as merely off-inventory.
        assert "check the source model" not in line

    def test_two_ports_on_one_target_are_recorded(self):
        same = plan_port_mapping(STANDALONE_48, STANDALONE_48, self.USED)
        _settled(same, self.USED, operator={"5": "1"}, target=STANDALONE_48)
        assert same.fused == {"1": ["1", "5"]}
        assert not same.is_clean
        assert any("1 <- 1, 5" in w for w in same.warnings)

    def test_a_logical_name_on_a_hardware_ports_target_is_a_fusion(self):
        """The run is read over every name, not only the hardware
        ones the plan was made for."""
        source = _inventory((0, "access", ["dmz"]))
        target = _inventory((0, "access", ["Ethernet1"]))
        plan = plan_port_mapping(source, target, ["dmz"])
        _settled(plan, ["dmz"], every=["dmz", "fortilink"],
                 renames={"fortilink": "Ethernet1"}, target=target)
        assert plan.fused == {"Ethernet1": ["dmz", "fortilink"]}

    def test_more_fused_targets_than_fit_on_a_line_are_counted(self):
        same = plan_port_mapping(STANDALONE_48, STANDALONE_48, self.USED)
        _settled(same, self.USED, operator={str(n): str(n + 20) for n in range(1, 9)},
                 target=STANDALONE_48)
        (line,) = [w for w in same.warnings if "receive more than one" in w]
        assert "8 target port(s)" in line and "and 2 more" in line

    def test_an_override_target_the_device_lacks_is_listed(self):
        same = plan_port_mapping(STANDALONE_48, STANDALONE_48, self.USED)
        _settled(same, self.USED, operator={"5": "77", "6": None}, target=STANDALONE_48)
        assert same.off_target == ["77"]
        assert same.is_clean and same.unresolved_ports == []
        (line,) = [w for w in same.warnings if "override target(s)" in w]
        assert "are not names the declared target device lists for its ports: 77;" in line
        # It does not say the name is no port -- an abbreviation would be one.
        assert "another spelling of a port" in line

    def test_an_override_for_a_port_the_config_does_not_have_is_not_listed(self):
        """The translator ignores such an entry; reporting its target
        would describe something that did not happen."""
        same = plan_port_mapping(STANDALONE_48, STANDALONE_48, self.USED)
        _settled(same, self.USED, operator={"999": "77"}, target=STANDALONE_48)
        assert same.off_target == []

    def test_a_target_in_another_case_is_a_port_of_the_device(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE, self.USED)
        _settled(plan, self.USED, operator={"52": None, "5": "1/a4"},
                 target=STACKED_48_MODULE)
        assert plan.off_target == []

    def test_an_overridden_pairing_raises_no_speed_warning(self):
        """The flag describes the target the PLAN chose.  Once the
        operator sends the port elsewhere it describes nothing."""
        source = _inventory((0, "uplink", ["49"]), speed={"49": "10gig"})
        target = _inventory((0, "uplink", ["1/A1"]), speed={"1/A1": "gig"})
        plan = plan_port_mapping(source, target, ["49"])
        assert any("slower target port" in w for w in plan.warnings)
        _settled(plan, ["49"], operator={"49": "1/A1"}, target=target)
        assert not [w for w in plan.warnings if "slower target port" in w]

    def test_what_a_dropped_port_took_with_it_is_named(self):
        plan = _settled(
            self._plan(), self.USED, emptied_lags=["Trk1"], shrunk_lags=["Trk2"],
            lost_routes=["0.0.0.0/0", "10.50.0.0/16"], lost_dhcp_pools=["10.1.0.0/24"],
        )
        assert (plan.emptied_lags, plan.shrunk_lags) == (["Trk1"], ["Trk2"])
        text = " | ".join(plan.warnings)
        assert "every member port of 1 LAG(s) was dropped" in text and "Trk1" in text
        assert "1 LAG(s) lost a member port" in text and "Trk2" in text
        assert (
            "2 static route(s) that named a dropped port were removed with it: "
            "0.0.0.0/0, 10.50.0.0/16"
        ) in text
        assert (
            "1 DHCP pool(s) bound to a dropped port were removed with it: "
            "10.1.0.0/24"
        ) in text

    def test_a_blank_override_is_said_to_have_been_ignored(self):
        plan = _settled(self._plan(), self.USED, ignored_overrides=["25", "zz"])
        # ``zz`` is not a name the config has: nothing stands for it.
        assert plan.ignored_overrides == ["25"]
        assert "25" in plan.unresolved_ports
        (line,) = [w for w in plan.warnings if "were ignored" in w]
        assert "1 override(s) had no usable target" in line and line.endswith("stands for: 25")

    def test_a_displaced_management_port_is_reported_once(self):
        """Dropped because it clashed, not because the target has no
        form for it: one line, the displaced one."""
        source = _inventory((0, "access", ["p1"]), (0, "mgmt", ["m0"]))
        target = _inventory((0, "access", ["x1"]))
        plan = plan_port_mapping(source, target, ["p1", "m0"])
        _settled(plan, ["p1", "m0"], drops=["m0"], displaced=["m0"], target=target)
        text = " | ".join(plan.warnings)
        assert "nobody decided" in text
        assert "source management port(s)" not in text

    def test_a_unit_that_simply_moved_with_its_port_is_not_news(self):
        source = _inventory((0, "access", ["ge-0/0/0"]))
        target = _inventory((0, "access", ["ge-0/0/5"]))
        used = ["ge-0/0/0", "ge-0/0/0.54"]
        plan = plan_port_mapping(source, target, used)
        _settled(plan, used, target=target, sub_interfaces={"ge-0/0/0.54": "ge-0/0/5.54"})
        assert plan.warnings == [] and plan.is_clean

    def test_an_off_inventory_name_the_operator_named_is_not_reported(self):
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE, ["1", "A1"])
        _settled(plan, ["1", "A1"], operator={"A1": "1/A1"}, target=STACKED_48_MODULE)
        assert plan.unresolved_ports == []
        assert not [w for w in plan.warnings if "declared source device" in w]

    def test_tracking_and_a_vtep_source_lost_with_a_port_are_said(self):
        plan = _settled(
            self._plan(), self.USED,
            lost_tracking=["Vlan20", "Vlan10"], lost_vtep_sources=["Loopback0"],
        )
        assert plan.lost_tracking == ["Vlan10", "Vlan20"]
        assert plan.lost_vtep_sources == ["Loopback0"]
        text = " | ".join(plan.warnings)
        assert "2 interface(s) lost a VRRP track entry that named a dropped port" in text
        assert "the VXLAN source interface was dropped (Loopback0)" in text

    def test_a_name_with_a_dot_is_not_a_unit_of_a_port(self):
        """``ether1.backup`` is a name with a dot in it.  A unit
        suffix is a number."""
        source = _inventory((0, "access", ["ether1"]))
        used = ["ether1", "ether1.backup", "ether1.5"]
        plan = plan_port_mapping(source, _inventory((0, "access", ["x1"])), used)
        unit = [w for w in plan.warnings if "sub-interface name(s)" in w]
        other = [w for w in plan.warnings if "declared source device (" in w]
        assert len(unit) == 1 and "(ether1.5)" in unit[0]
        assert len(other) == 1 and "(ether1.backup)" in other[0]

    def test_a_sub_interface_that_followed_its_port_is_accounted_for(self):
        source = _inventory((0, "access", ["ge-0/0/0", "ge-0/0/1"]))
        target = _inventory((0, "access", ["ge-0/0/5", "ge-0/0/6"]))
        used = ["ge-0/0/0", "ge-0/0/0.54", "ge-0/0/1.7"]
        plan = plan_port_mapping(source, target, used)
        assert plan.off_inventory == ["ge-0/0/0.54", "ge-0/0/1.7"]
        _settled(plan, used, target=target, renames={"ge-0/0/0.54": "ge-0/0/5.54"},
                 sub_interfaces={"ge-0/0/0.54": "ge-0/0/5.54"})
        assert plan.sub_interfaces == {"ge-0/0/0.54": "ge-0/0/5.54"}
        assert plan.off_inventory == ["ge-0/0/1.7"]
        assert plan.unresolved_ports == ["ge-0/0/1.7"]

    def test_a_sub_interface_dropped_with_its_port_is_said_so(self):
        source = _inventory((0, "access", ["ge-0/0/0", "ge-0/0/1"]))
        target = _inventory((0, "access", ["ge-0/0/5"]))
        used = ["ge-0/0/0", "ge-0/0/1", "ge-0/0/1.7"]
        plan = plan_port_mapping(source, target, used)
        _settled(plan, used, target=target, drops=["ge-0/0/1.7"],
                 sub_interfaces={"ge-0/0/1.7": None})
        assert plan.unresolved_ports == ["ge-0/0/1"]
        assert any(
            "1 sub-interface name(s) were DROPPED with the port they belong to: "
            "ge-0/0/1.7" in w for w in plan.warnings
        )

    def test_a_sub_interface_is_told_apart_from_a_wrong_model(self):
        """``Gi1/0/1.100`` is not a port of the device, and that says
        nothing against the declared model: its parent is one.  An
        address is not a sub-interface because it contains a dot."""
        source = _inventory((0, "access", ["Gi1/0/1", "Gi1/0/2"]))
        target = _inventory((0, "access", ["ge-0/0/0", "ge-0/0/1"]))
        used = ["Gi1/0/1", "Gi1/0/1.100", "Te9/9/9", "192.168.100.1", "ssl.root"]
        plan = plan_port_mapping(source, target, used)
        _settled(plan, used, target=target)
        sub = next(w for w in plan.warnings if "sub-interface" in w)
        wrong = next(w for w in plan.warnings if "check the source model" in w)
        assert "1 sub-interface name(s)" in sub and "Gi1/0/1.100" in sub
        assert "did NOT move with their port" in sub
        for name in ("Te9/9/9", "192.168.100.1", "ssl.root"):
            assert name in wrong and name not in sub

    def test_a_displaced_sub_interface_has_a_line_of_its_own(self):
        """Across codecs a sub-interface is left to the name-shape
        translator.  A classifier that folds the unit into the port
        (Junos) sends it onto its own parent, or onto its sibling
        units, so it is dropped -- and the line says it is a
        sub-interface, not "a name nobody decided"."""
        source = _inventory((0, "access", ["ge-0/0/0"]))
        target = _inventory((0, "access", ["1/1"]))
        used = ["ge-0/0/0", "ge-0/0/0.54"]
        plan = plan_port_mapping(source, target, used)
        _settled(plan, used, target=target, drops=["ge-0/0/0.54"],
                 displaced=["ge-0/0/0.54"])
        (line,) = plan.warnings
        assert "1 sub-interface name(s) could not be given a name of their own" in line
        assert "nobody decided" not in line

    def test_off_inventory_names_the_translator_dropped_are_counted(self):
        """"Nothing was dropped" is not true of an off-inventory name:
        the name-shape translator strips what the target cannot name."""
        plan = plan_port_mapping(STANDALONE_48, STACKED_48_MODULE, ["1", "A1", "A2"])
        _settled(plan, ["1", "A1", "A2"], drops=["A1"], target=STACKED_48_MODULE)
        (line,) = [w for w in plan.warnings if "check the source model" in w]
        assert "which dropped 1 of them" in line

    def test_a_plan_that_was_not_made_keeps_its_reason(self):
        plan = plan_port_mapping(STANDALONE_48, _inventory(), ["1"])
        reason = list(plan.warnings)
        settle_plan(
            plan, operator_map={"1": "x"}, used_names=["1"], every_name=["1"],
            port_renames={"1": "x"}, port_drops=[], target_names=[],
        )
        assert plan.warnings == reason and not plan.applied
        assert plan.off_target == [] and plan.fused == {}


class TestNoWarningCanBeReadAsATableRow:
    """The migrate page reads single-quoted tokens out of job warnings
    as extra rows of its rename table."""

    def test_every_kind_of_line_and_none_has_a_quote(self):
        two = _inventory((0, "access", ["1/1"]), (1, "access", ["2/1"]), (0, "mgmt", ["mgmt0"]))
        one = _inventory((0, "access", ["x1"]))
        used = ["1/1", "2/1", "mgmt0", "A1", "1/1.5", "49.7"]
        plan = plan_port_mapping(two, one, used)
        _settled(
            plan, used, target=one, operator={"1/1": "9/9", "nope": "8/8"},
            drops=["A1", "mgmt0"], displaced=["A1", "1/1.5"],
            emptied_lags=["Trk1"], shrunk_lags=["Trk2"], lost_routes=["0.0.0.0/0"],
            lost_dhcp_pools=["10.0.0.0/24"], ignored_overrides=["2/1"],
            sub_interfaces={"49.7": None},
            lost_tracking=["Vlan10"], lost_vtep_sources=["Loopback0"],
        )
        kinds = (
            "belong to a member the target does not have",
            "source management port(s) have no management port",
            "nobody decided",
            "could not be given a name of their own",
            "were DROPPED with the port they belong to",
            "override target(s) are not names",
            "had no usable target",
            "lost a VRRP track entry",
            "VXLAN source interface was dropped",
            "every member port of",
            "lost a member port",
            "static route(s)",
            "DHCP pool(s)",
        )
        text = " | ".join(plan.warnings)
        for kind in kinds:
            assert kind in text, kind
        assert "'" not in text
        assert plan.warnings == describe_plan(
            plan, decided={"1/1", "nope"}, dropped={"A1", "mgmt0", "2/1"},
        )

    def test_an_apostrophe_in_a_port_name_does_not_make_one(self):
        """RouterOS and FortiGate interface names are free text."""
        source = _inventory((0, "access", ["ether1"]))
        used = ["ether1", "bob's uplink", "alice's port"]
        plan = plan_port_mapping(source, _inventory((0, "access", ["x1"])), used)
        (line,) = plan.warnings
        assert "'" not in line
        assert "bob\u2019s uplink" in line and "alice\u2019s port" in line
