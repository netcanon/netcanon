"""Shipped device-model families — the guards that keep them describing hardware.

``test_device_models.py`` pins how the compiler behaves on a made-up
family.  This module is about the REAL data under
``netcanon/definitions/library/model_families/``: every name it
produces is written verbatim into a generated config, so a wrong value
here is a config naming a port the device does not have.

The guards, each answering a way the older target-profile registry went
wrong before the 2026-10 audit:

* **Strict load.**  The runtime loader skips a family file that fails
  validation so one bad file cannot stop the application; here every
  shipped file must load, and the runtime registry must hold all of them.
* **Capture conformance.**  A ``capture`` grade exists only as a
  ``captures:`` claim in a family file.  Each claim is re-proven here:
  the fixture must identify itself as that model, and the hardware ports
  it names must EQUAL the inventory compiled from the claimed deployment
  — a capture that names only some ports cannot be claimed.  The claims
  are pinned whole (fixture, marker, mode, each member's model, id and
  modules), so one can neither appear, vanish nor change unreviewed; and
  the engine's own list of claims that grant the grade
  (``PROVEN_CAPTURE_CLAIMS``) must be exactly the ones re-proven here.
* **Exact inventories, written by hand.**  A capture proves NAMES.  It
  cannot prove which ports are uplinks (AOS-S names carry no role), and
  most models have no capture at all.  So the ``(name, role)`` sequence
  of every shipped model, in every mode, with every module, is pinned
  here as literals — not regenerated from the code under test.
* **Grammar round trip.**  Every compiled name the vendor's own codec
  recognises must classify to the member, slot and port number that
  produced it.  One form is not recognised yet and is pinned as a known
  gap: the bare-letter module port of a switch that is not stacked
  (``A1``).  This is a pipeline-compatibility check, not evidence: the
  data and the codec can be wrong together.
* **Agreement with the flat profiles.**  Where a target profile and a
  device model describe the same device in the same state, they must
  list the same ports with the same roles, so an operator is never shown
  one name in a dropdown and given another in the output.

* **Pinned part numbers and grades.**  Which J-number is which model,
  and how well each fact is graded, are tables in this file — a swap or
  a regrade in a family file is a test edit, not a silent change.

What none of this proves: a part graded ``vendor-doc`` or ``inferred`` is
only as good as the reading behind it.
"""

from __future__ import annotations

import logging
import re
from itertools import product
from pathlib import Path

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration import device_models as dm
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.device_models import (
    Deployment,
    DeviceModelRegistry,
    FamilyDef,
    Inventory,
    MemberSpec,
    ModelDef,
    compile_deployment,
    inventory_from_profile,
    load_family_file,
    load_model_families_dir,
)
from netcanon.migration.target_profiles import load_profiles_dir

from ._capture_ports import ports_in_capture, vendor_of

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILIES_DIR = LIBRARY_DIR / "model_families"
FAMILY_FILES = sorted(FAMILIES_DIR.glob("*.yaml"))


def _strict_registry() -> DeviceModelRegistry:
    """Every shipped file, loaded so that a defect RAISES.

    The runtime loader logs and skips a bad file.  Built with it, a
    shipped file that fails to load would surface here as a
    ``KeyError`` on the family's name while this module is being
    collected, and the test that says what is wrong would never run.
    """
    registry = DeviceModelRegistry()
    for path in FAMILY_FILES:
        registry.add(load_family_file(path))
    return registry


REGISTRY = _strict_registry()
PROFILES = load_profiles_dir(LIBRARY_DIR / "target_profiles")


def _compile(vendor: str, mode: str | None, *members: dict) -> Inventory:
    return compile_deployment(
        Deployment(
            vendor=vendor, mode=mode,
            members=[MemberSpec(**m) for m in members],
        ),
        REGISTRY,
    )


def _every_model() -> list[tuple[FamilyDef, ModelDef]]:
    return [
        (family, model)
        for family in REGISTRY.families.values()
        for model in family.models.values()
    ]


def _model_id(value: object) -> str:
    return getattr(value, "model", None) or getattr(value, "family", str(value))


def _module_choices(model: ModelDef) -> list[dict[str, str | None]]:
    """Every way to populate the model's bays, the empty bay included."""
    bays = list(model.bays)
    options = [[None, *model.bays[bay].accepts] for bay in bays]
    return [dict(zip(bays, choice, strict=True)) for choice in product(*options)]


def _run(start: int, count: int, prefix: str = "") -> list[str]:
    return [f"{prefix}{n}" for n in range(start, start + count)]


# ---------------------------------------------------------------------------
# Strict load
# ---------------------------------------------------------------------------


class TestShippedFamiliesLoad:
    def test_there_are_shipped_families(self) -> None:
        assert FAMILY_FILES, "no model-family files are shipped"

    def test_the_directory_holds_only_family_yaml(self) -> None:
        """The loader and the wheel's package-data glob both match
        ``*.yaml``.  A family saved as ``.yml`` would simply not ship,
        and nothing would say so."""
        strays = sorted(
            p.name for p in FAMILIES_DIR.iterdir()
            if p.suffix != ".yaml" or not p.is_file()
        )
        assert not strays, strays

    @pytest.mark.parametrize("path", FAMILY_FILES, ids=lambda p: p.name)
    def test_every_family_file_loads_strictly(self, path: Path) -> None:
        """The runtime loader logs and skips a bad file.  A typo in a
        shipped one must fail here instead of removing a family from
        the product with every other test green."""
        family = load_family_file(path)
        assert path.name == f"{family.vendor}_{family.family.lower()}.yaml", (
            f"{path.name}: a family file is named <vendor>_<family>.yaml"
        )

    def test_the_runtime_registry_holds_every_shipped_file(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The loader the application uses takes every shipped file,
        and has nothing to warn about in any of them."""
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            runtime = load_model_families_dir(FAMILIES_DIR)
        assert list(runtime.families) == list(REGISTRY.families)
        assert len(runtime) == len(FAMILY_FILES)
        assert not caplog.records, [r.getMessage() for r in caplog.records]

    @pytest.mark.parametrize(("family", "model"), _every_model(), ids=_model_id)
    def test_every_model_states_what_it_is(
        self, family: FamilyDef, model: ModelDef,
    ) -> None:
        assert model.display_name.strip(), model.model
        assert model.skus, (
            f"{model.model}: a shipped model names the part number(s) it "
            f"describes — that is what a config prints and what the "
            f"evidence is about"
        )
        assert model.skus[0] in model.display_name, model.model
        assert model.panel.ref.strip(), (
            f"{model.model}: a shipped model says what establishes its panel"
        )

    def test_every_grade_names_what_backs_it(self) -> None:
        for family in REGISTRY.families.values():
            for name, mode in family.modes.items():
                assert mode.naming.ref.strip(), (family.key, name)
                if mode.bay_naming is not None:
                    assert mode.bay_naming.ref.strip(), (family.key, name)
            for sku, module in family.modules.items():
                assert module.inventory.ref.strip(), (family.key, sku)
            for port in family.deployment_ports:
                assert port.naming.ref.strip(), (family.key, port.name)

    def test_no_evidence_ref_leans_on_a_legend_only_a_comment_holds(self) -> None:
        """A ``ref`` is served to API clients, who see neither the
        YAML comments nor the other family file.  A short tag defined
        in a header comment (and meaning a different document in each
        file) is of no use to them, and neither is "real configs"
        with nothing to find them by."""
        tags = re.compile(r"\b(IGSG|QS|ATMG|MCG|BP|DS|HIG|CG|CR)\b")
        for family in REGISTRY.families.values():
            grades = [mode.naming for mode in family.modes.values()]
            grades += [m.bay_naming for m in family.modes.values() if m.bay_naming]
            grades += [module.inventory for module in family.modules.values()]
            grades += [model.panel for model in family.models.values()]
            grades += [port.naming for port in family.deployment_ports]
            for grade in grades:
                assert not tags.search(grade.ref), grade.ref
                assert "real " not in grade.ref, grade.ref

    def test_every_vendor_is_one_a_codec_translates(self) -> None:
        vendor_ids = {vendor_of(name) for name in list_public_codecs()}
        for family in REGISTRY.families.values():
            assert family.vendor in vendor_ids, family.key


# ---------------------------------------------------------------------------
# Capture conformance
# ---------------------------------------------------------------------------

#: Every capture claim the shipped families make, whole: fixture ->
#: ``(family, mode, marker, members)``, each member as ``(model key,
#: member id, modules)``.  Pinned, so a ``capture`` grade can neither
#: be claimed, dropped nor re-pointed without this table changing in
#: the same review.  The marker is here and not only beside the claim
#: it guards: replacing ``module 1 type jl258a`` by a line every AOS-S
#: capture contains would otherwise pass.
EXPECTED_CLAIMS: dict[str, tuple[str, str, str, list[tuple]]] = {
    "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg": (
        "aruba_aoss/2930F", "standalone", "module 1 type jl260a",
        [("2930F-48G-4SFP", None, {})],
    ),
    "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1610_dhcp_server.cfg": (
        "aruba_aoss/2930F", "standalone", "module 1 type jl258a",
        [("2930F-8G-PoEP-2SFPP", None, {})],
    ),
    "tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg": (
        "aruba_aoss/2930M", "stacked", 'member 1 type "jl323a"',
        [("2930M-40G-8SR-PoEP", 1, {"A": "JL083A"})],
    ),
}


def _claims() -> list[tuple[FamilyDef, object]]:
    return [
        (family, claim)
        for family in REGISTRY.families.values()
        for claim in family.captures
    ]


def _claim_id(value: object) -> str:
    fixture = getattr(value, "fixture", None)
    return Path(fixture).name if fixture else getattr(value, "family", str(value))


def _claim_inventory(family: FamilyDef, claim) -> Inventory:
    return compile_deployment(
        Deployment(vendor=family.vendor, mode=claim.mode, members=claim.members),
        REGISTRY,
    )


class TestCaptureConformance:
    def test_the_claims_are_the_ones_we_expect(self) -> None:
        declared = {
            claim.fixture: (
                family.key, claim.mode, claim.marker,
                [
                    (REGISTRY.resolve(family.vendor, m.model)[1].model, m.id,
                     dict(m.modules))
                    for m in claim.members
                ],
            )
            for family, claim in _claims()
        }
        assert declared == EXPECTED_CLAIMS

    def test_the_claims_that_grant_the_grade_are_the_ones_proven_here(self) -> None:
        """``capture`` means "a test re-proves it on every run".  The
        engine grants the grade only to the claims it lists, so that
        list must be exactly the claims this module re-proves: one
        missing is a proven capture that grants nothing, one extra is
        a grade nothing checks."""
        proven = {
            (
                family, fixture, mode,
                tuple(
                    (model, member_id, tuple(sorted(modules.items())))
                    for model, member_id, modules in members
                ),
            )
            for fixture, (family, mode, _marker, members) in EXPECTED_CLAIMS.items()
        }
        assert proven == dm.PROVEN_CAPTURE_CLAIMS

    def test_a_proven_fixture_cited_for_another_deployment_grants_nothing(self) -> None:
        """The grade is granted to a whole claim, not to a fixture.
        The JL260A capture re-pointed at the JL254A -- the same port
        names, a different switch -- is a claim nothing re-proves."""
        family = REGISTRY.families["aruba_aoss/2930F"]
        data = family.model_dump(by_alias=True)
        (claim,) = [c for c in data["captures"] if "wc1607" in c["fixture"]]
        claim["members"] = [{"model": "2930F-48G-4SFPP"}]
        registry = DeviceModelRegistry([FamilyDef.model_validate(data)])
        for sku in ("JL254A", "JL260A"):
            inventory = compile_deployment(
                Deployment(vendor="aruba_aoss", mode="standalone",
                           members=[MemberSpec(model=sku)]),
                registry,
            )
            assert inventory.evidence == "vendor-doc", sku

    @pytest.mark.parametrize(("family", "claim"), _claims(), ids=_claim_id)
    def test_the_capture_is_a_committed_fixture_of_that_model(
        self, family: FamilyDef, claim,
    ) -> None:
        parts = Path(claim.fixture).parts
        assert parts[:3] == ("tests", "fixtures", "real") and ".." not in parts, (
            claim.fixture
        )
        path = REPO_ROOT / claim.fixture
        assert path.is_file(), claim.fixture
        _, text = ports_in_capture(path, family.vendor)
        assert claim.marker == claim.marker.lower(), claim.marker
        assert claim.marker in text, (
            f"{claim.fixture} does not identify itself as this model "
            f"(no {claim.marker!r} line)"
        )
        # ...and the marker is about THIS model: it carries one of the
        # part numbers of a member the claim names.
        skus = [
            sku.lower()
            for member in claim.members
            for sku in REGISTRY.resolve(family.vendor, member.model)[1].skus
        ]
        assert any(sku in claim.marker for sku in skus), (
            f"{claim.fixture}: marker {claim.marker!r} names none of {skus}"
        )

    @pytest.mark.parametrize(("family", "claim"), _claims(), ids=_claim_id)
    def test_the_capture_names_exactly_the_inventorys_ports(
        self, family: FamilyDef, claim,
    ) -> None:
        seen, _ = ports_in_capture(REPO_ROOT / claim.fixture, family.vendor)
        assert seen, f"{claim.fixture}: names no hardware port; it proves nothing"
        names = set(_claim_inventory(family, claim).names())
        unknown = sorted(seen - names)
        assert not unknown, (
            f"{claim.fixture} is a real device of this model and names "
            f"ports the model data does not have: {unknown[:12]}.  The "
            f"capture is right; the family file or the naming rule is wrong."
        )
        invented = sorted(names - seen)
        assert not invented, (
            f"the model data has ports {claim.fixture} does not show: "
            f"{invented[:12]}.  A claim grants `capture` to every port of "
            f"the deployment, so the capture has to name every one."
        )

    @pytest.mark.parametrize(("family", "claim"), _claims(), ids=_claim_id)
    def test_the_claimed_deployment_is_capture_graded_port_by_port(
        self, family: FamilyDef, claim,
    ) -> None:
        inventory = _claim_inventory(family, claim)
        assert inventory.evidence == "capture"
        assert {p.evidence for p in inventory.ports} == {"capture"}
        assert claim.fixture in inventory.evidence_refs

    def test_nothing_else_is_capture_graded(self) -> None:
        """A sibling model, another mode, another member id: none of
        them inherits a capture it is not in."""
        claimed = {
            (family.key, claim.mode, REGISTRY.resolve(family.vendor, m.model)[1].model)
            for family, claim in _claims() for m in claim.members
        }
        for family, model in _every_model():
            for mode_name in family.modes:
                if not family.supports(model, mode_name):
                    continue
                for modules in _module_choices(model):
                    inventory = _compile(
                        family.vendor, mode_name,
                        {"model": model.model, "modules": modules},
                    )
                    graded = {p.evidence for p in inventory.ports}
                    if (family.key, mode_name, model.model) in claimed:
                        continue
                    assert "capture" not in graded, (model.model, mode_name, modules)

    def test_a_captured_model_is_not_capture_graded_as_another_member(self) -> None:
        """The JL260A capture is a standalone switch.  The same model
        as a VSF member has names (``1/49``) no committed capture shows."""
        inventory = _compile("aruba_aoss", "vsf", {"model": "JL260A"})
        assert inventory.evidence == "vendor-doc"


# ---------------------------------------------------------------------------
# Exact inventories, written by hand
# ---------------------------------------------------------------------------

#: ``(vendor, model key, mode, modules)`` -> the access names and the
#: uplink names, in order.  Literals on purpose: these are the ports the
#: hardware has, typed from the sources each family file cites, and the
#: code under test must reproduce them.  Regenerating this table from
#: the compiler would make it agree with any defect.
_F = "aruba_aoss"

#: Aruba 2930F.  No bay; the uplinks continue the access numbering.
#: ``(access count, uplink port numbers)`` -> the models with that
#: panel.  The numbers are HPE's: the faceplate pictures and Table 3 of
#: the 2930F Installation and Getting Started Guide.
_2930F_PANELS: dict[tuple[int, tuple[str, ...]], list[str]] = {
    (24, ("25", "26", "27", "28")): [
        "2930F-24G-4SFPP",              # JL253A
        "2930F-24G-PoEP-4SFPP",         # JL255A
        "2930F-24G-PoEP-4SFPP-TAA",     # JL263A
        "2930F-24G-4SFP",               # JL259A
        "2930F-24G-PoEP-4SFP",          # JL261A
    ],
    (48, ("49", "50", "51", "52")): [
        "2930F-48G-4SFPP",              # JL254A
        "2930F-48G-PoEP-4SFPP",         # JL256A
        "2930F-48G-PoEP-4SFPP-TAA",     # JL264A
        "2930F-48G-4SFP",               # JL260A
        "2930F-48G-PoEP-4SFP",          # JL262A
        "2930F-48G-740W-PoEP-4SFP",     # JL557A
        "2930F-48G-740W-PoEP-4SFPP",    # JL558A
        "2930F-48G-740W-PoEP-4SFPP-TAA",  # JL559A
    ],
    (8, ("9", "10")): [
        "2930F-8G-PoEP-2SFPP",          # JL258A
        "2930F-8G-PoEP-2SFPP-TAA",      # JL692A
    ],
    (12, ("13", "14", "15", "16")): [
        "2930F-12G-PoEP-2G-2SFPP",      # JL693A
    ],
}

EXPECTED_INVENTORIES: dict[tuple[str, str, str, tuple], tuple[list[str], list[str]]] = {}
for (_access, _uplinks), _models in _2930F_PANELS.items():
    for _model in _models:
        # VSF off: bare numbers.  VSF on: every port, uplinks included,
        # takes the member number.
        EXPECTED_INVENTORIES[(_F, _model, "standalone", ())] = (
            _run(1, _access), list(_uplinks),
        )
        EXPECTED_INVENTORIES[(_F, _model, "vsf", ())] = (
            _run(1, _access, "1/"), [f"1/{n}" for n in _uplinks],
        )


#: Aruba 2930M.  A fixed panel of 24 or 48 ports with no gaps, and one
#: bay, ``A``, that is empty or holds one module.  The fixed panel is
#: all ACCESS ports (the dual-personality ports sit inside the range
#: the chassis labels "Ports (1-48T)"); every uplink comes from the bay.
#: Sources: the 2930M install guide's Tables 3 and 9, and the AOS-S
#: 16.11 Advanced Traffic Management Guide's printed configs.
_2930M_PANELS: dict[int, list[str]] = {
    24: [
        "2930M-24G",                    # JL319A
        "2930M-24G-PoEP",               # JL320A
        "2930M-24SR-PoEP",              # JL324A
        "2930M-24SR-PoE-Class6",        # R0M68A
    ],
    48: [
        "2930M-48G",                    # JL321A
        "2930M-48G-PoEP",               # JL322A
        "2930M-40G-8SR-PoEP",           # JL323A
        "2930M-40G-8SR-PoE-Class6",     # R0M67A
    ],
}
#: Bay A: what each module contributes.  ``()`` is the empty bay.
_2930M_BAY_A: dict[tuple, list[str]] = {
    (): [],
    (("A", "JL083A"),): ["A1", "A2", "A3", "A4"],   # 4 x SFP+
    (("A", "JL078A"),): ["A1"],                     # 1 x QSFP+
    (("A", "JL081A"),): ["A1", "A2", "A3", "A4"],   # 4 x Smart Rate
}
for _access, _models in _2930M_PANELS.items():
    for _model in _models:
        for _fitted, _uplinks in _2930M_BAY_A.items():
            # Stacking off: bare numbers and bare `A1`.  Stacking on:
            # the member number in front of both.
            EXPECTED_INVENTORIES[(_F, _model, "standalone", _fitted)] = (
                _run(1, _access), list(_uplinks),
            )
            EXPECTED_INVENTORIES[(_F, _model, "stacked", _fitted)] = (
                _run(1, _access, "1/"), [f"1/{n}" for n in _uplinks],
            )


#: Cisco Catalyst 9300, the higher-scale models included.  Switch 1 (the
#: number a member takes when none is stated); the fixed panel is module
#: 0 and the network module module 1.  A name is the interface type,
#: then switch/module/port, and the type is the port's top speed, so a
#: panel of two speeds is two types numbered straight through (the
#: 48UXM).  Sources: the C9300 Hardware Installation Guide's Product
#: Overview and network-module tables, the data sheet's Table 2 and the
#: IOS XE 17.12 configuration guide and command reference.
_C = "cisco_iosxe"
_C9300_PANELS: dict[str, list[str]] = {
    "C9300-24T": _run(1, 24, "GigabitEthernet1/0/"),
    "C9300-48T": _run(1, 48, "GigabitEthernet1/0/"),
    "C9300-24P": _run(1, 24, "GigabitEthernet1/0/"),
    "C9300-48P": _run(1, 48, "GigabitEthernet1/0/"),
    "C9300-24U": _run(1, 24, "GigabitEthernet1/0/"),
    "C9300-48U": _run(1, 48, "GigabitEthernet1/0/"),
    "C9300-24H": _run(1, 24, "GigabitEthernet1/0/"),
    "C9300-48H": _run(1, 48, "GigabitEthernet1/0/"),
    "C9300-24S": _run(1, 24, "GigabitEthernet1/0/"),
    "C9300-48S": _run(1, 48, "GigabitEthernet1/0/"),
    "C9300-24UX": _run(1, 24, "TenGigabitEthernet1/0/"),
    "C9300-48UXM": [
        *_run(1, 36, "TwoGigabitEthernet1/0/"), *_run(37, 12, "TenGigabitEthernet1/0/"),
    ],
    "C9300-48UN": _run(1, 48, "FiveGigabitEthernet1/0/"),
    "C9300-24UB": _run(1, 24, "GigabitEthernet1/0/"),
    "C9300-48UB": _run(1, 48, "GigabitEthernet1/0/"),
    "C9300-24UXB": _run(1, 24, "TenGigabitEthernet1/0/"),
}
#: Bay 1: what each network module contributes.  ``()`` is the empty bay.
_C9300_BAY_1: dict[tuple, list[str]] = {
    (): [],
    (("1", "C9300-NM-4G"),): _run(1, 4, "GigabitEthernet1/1/"),
    (("1", "C9300-NM-4M"),): _run(1, 4, "TenGigabitEthernet1/1/"),
    (("1", "C9300-NM-8X"),): _run(1, 8, "TenGigabitEthernet1/1/"),
    (("1", "C9300-NM-2Q"),): _run(1, 2, "FortyGigabitEthernet1/1/"),
    (("1", "C9300-NM-2Y"),): _run(1, 2, "TwentyFiveGigE1/1/"),
}
for _model, _access_names in _C9300_PANELS.items():
    for _fitted, _uplinks in _C9300_BAY_1.items():
        EXPECTED_INVENTORIES[(_C, _model, "stack", _fitted)] = (
            list(_access_names), list(_uplinks),
        )

#: Cisco Catalyst 9300X, in the C9300 family: a panel of one type, and a
#: bay that takes the C9300X network modules only -- the C9300X-NM-4C
#: only on the 24Y, 48HX and 48TX, as the data sheet and the hardware
#: guide's network-module chapter say.  The panels' names are inferred
#: (see KNOWN_INFERRED_PARTS); the modules' are the hardware guide's
#: Tables 6-9.
_C9300X_PANELS: dict[str, list[str]] = {
    "C9300X-12Y": _run(1, 12, "TwentyFiveGigE1/0/"),
    "C9300X-24Y": _run(1, 24, "TwentyFiveGigE1/0/"),
    "C9300X-24HX": _run(1, 24, "TenGigabitEthernet1/0/"),
    "C9300X-48HX": _run(1, 48, "TenGigabitEthernet1/0/"),
    "C9300X-48TX": _run(1, 48, "TenGigabitEthernet1/0/"),
}
_C9300X_BAY_1: dict[tuple, list[str]] = {
    (): [],
    (("1", "C9300X-NM-8M"),): _run(1, 8, "TenGigabitEthernet1/1/"),
    (("1", "C9300X-NM-8Y"),): _run(1, 8, "TwentyFiveGigE1/1/"),
    (("1", "C9300X-NM-2C"),): _run(1, 2, "HundredGigE1/1/"),
    (("1", "C9300X-NM-4C"),): _run(1, 4, "HundredGigE1/1/"),
}
_C9300X_TAKES_THE_NM_4C = {"C9300X-24Y", "C9300X-48HX", "C9300X-48TX"}
for _model, _access_names in _C9300X_PANELS.items():
    for _fitted, _uplinks in _C9300X_BAY_1.items():
        if _fitted == (("1", "C9300X-NM-4C"),) and _model not in _C9300X_TAKES_THE_NM_4C:
            continue
        EXPECTED_INVENTORIES[(_C, _model, "stack", _fitted)] = (
            list(_access_names), list(_uplinks),
        )

#: Cisco Catalyst 9200, the PB models included: switch 1, the panel
#: module 0, the bay module 1.  A PXG panel is GigabitEthernet and then
#: its Multigigabit ports as TenGigabitEthernet, numbered straight
#: through: the command reference puts the Multigigabit ports of a
#: 24-port switch at 17-24 and of a 48-port one at 41-48.  Sources: the
#: C9200 Hardware Installation Guide's Product Overview tables, the
#: data sheet's Tables 2 and 3 and the IOS XE 17.12 configuration
#: guide and command reference.
_C9200_PANELS: dict[str, list[str]] = {
    "C9200-24T": _run(1, 24, "GigabitEthernet1/0/"),
    "C9200-48T": _run(1, 48, "GigabitEthernet1/0/"),
    "C9200-24P": _run(1, 24, "GigabitEthernet1/0/"),
    "C9200-48P": _run(1, 48, "GigabitEthernet1/0/"),
    "C9200-48PL": _run(1, 48, "GigabitEthernet1/0/"),
    "C9200-24PB": _run(1, 24, "GigabitEthernet1/0/"),
    "C9200-48PB": _run(1, 48, "GigabitEthernet1/0/"),
    "C9200-24PXG": [
        *_run(1, 16, "GigabitEthernet1/0/"), *_run(17, 8, "TenGigabitEthernet1/0/"),
    ],
    "C9200-48PXG": [
        *_run(1, 40, "GigabitEthernet1/0/"), *_run(41, 8, "TenGigabitEthernet1/0/"),
    ],
}
#: Bay 1: the data sheet's Table 3 says which models take which module.
_C9200_NM_4G = (("1", "C9200-NM-4G"),)
_C9200_NM_4X = (("1", "C9200-NM-4X"),)
_C9200_NM_2Y = (("1", "C9200-NM-2Y"),)
_C9200_BAY_1: dict[tuple, list[str]] = {
    (): [],
    _C9200_NM_4G: _run(1, 4, "GigabitEthernet1/1/"),
    _C9200_NM_4X: _run(1, 4, "TenGigabitEthernet1/1/"),
    _C9200_NM_2Y: _run(1, 2, "TwentyFiveGigE1/1/"),
}
for _model, _access_names in _C9200_PANELS.items():
    _takes = (
        ((), _C9200_NM_4X, _C9200_NM_2Y) if "PXG" in _model
        else ((), _C9200_NM_4G, _C9200_NM_4X)
    )
    for _fitted in _takes:
        EXPECTED_INVENTORIES[(_C, _model, "stack", _fitted)] = (
            list(_access_names), list(_C9200_BAY_1[_fitted]),
        )

#: Cisco Catalyst 9200L: no bay; the fixed uplinks are module 1 of the
#: switch all the same (the configuration guide: "On a device with SFP
#: uplink ports, the module number is 1 and the port numbers
#: restart").  The C9200L-48PXG-4X's twelve Multigigabit ports at 37-48
#: are inferred, and graded so (see KNOWN_INFERRED_PARTS).
_GI_UPLINKS = _run(1, 4, "GigabitEthernet1/1/")
_TE_UPLINKS = _run(1, 4, "TenGigabitEthernet1/1/")
_TWE_UPLINKS = _run(1, 2, "TwentyFiveGigE1/1/")
_C9200L: dict[str, tuple[list[str], list[str]]] = {
    "C9200L-24T-4G": (_run(1, 24, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9200L-48T-4G": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9200L-24P-4G": (_run(1, 24, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9200L-48P-4G": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9200L-48PL-4G": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9200L-24T-4X": (_run(1, 24, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9200L-48T-4X": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9200L-24P-4X": (_run(1, 24, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9200L-48P-4X": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9200L-48PL-4X": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9200L-24PXG-4X": (
        [*_run(1, 16, "GigabitEthernet1/0/"), *_run(17, 8, "TenGigabitEthernet1/0/")],
        _TE_UPLINKS,
    ),
    "C9200L-48PXG-4X": (
        [*_run(1, 36, "GigabitEthernet1/0/"), *_run(37, 12, "TenGigabitEthernet1/0/")],
        _TE_UPLINKS,
    ),
    "C9200L-24PXG-2Y": (
        [*_run(1, 16, "GigabitEthernet1/0/"), *_run(17, 8, "TenGigabitEthernet1/0/")],
        _TWE_UPLINKS,
    ),
    "C9200L-48PXG-2Y": (
        [*_run(1, 40, "GigabitEthernet1/0/"), *_run(41, 8, "TenGigabitEthernet1/0/")],
        _TWE_UPLINKS,
    ),
}
for _model, (_access_names, _uplinks) in _C9200L.items():
    EXPECTED_INVENTORIES[(_C, _model, "stack", ())] = (
        list(_access_names), list(_uplinks),
    )

#: Cisco Catalyst 3850: one bay, named as a C9300's is.  Sources: the
#: 3850 Hardware Installation Guide's Product Overview, the data sheet's
#: Tables 1 and 2, and the IOS XE 16.12 configuration guide and command
#: reference.  Two parts are inferred (see KNOWN_INFERRED_PARTS): the
#: WS-C3850-12X48U's Multigigabit ports at 37-48, and the C3850-NM-2-10G's
#: four names.  The C3850-NM-2-40G is not modelled.
_C3850_PANELS: dict[str, list[str]] = {
    "WS-C3850-24T": _run(1, 24, "GigabitEthernet1/0/"),
    "WS-C3850-48T": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3850-24P": _run(1, 24, "GigabitEthernet1/0/"),
    "WS-C3850-48P": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3850-48F": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3850-24U": _run(1, 24, "GigabitEthernet1/0/"),
    "WS-C3850-48U": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3850-24XU": _run(1, 24, "TenGigabitEthernet1/0/"),
    "WS-C3850-12X48U": [
        *_run(1, 36, "GigabitEthernet1/0/"), *_run(37, 12, "TenGigabitEthernet1/0/"),
    ],
    "WS-C3850-12S": _run(1, 12, "GigabitEthernet1/0/"),
    "WS-C3850-24S": _run(1, 24, "GigabitEthernet1/0/"),
    "WS-C3850-12XS": _run(1, 12, "TenGigabitEthernet1/0/"),
    "WS-C3850-24XS": _run(1, 24, "TenGigabitEthernet1/0/"),
}
_C3850_NM_4_1G = (("1", "C3850-NM-4-1G"),)
_C3850_NM_2_10G = (("1", "C3850-NM-2-10G"),)
_C3850_NM_4_10G = (("1", "C3850-NM-4-10G"),)
_C3850_NM_8_10G = (("1", "C3850-NM-8-10G"),)
_C3850_BAY_1: dict[tuple, list[str]] = {
    (): [],
    _C3850_NM_4_1G: _run(1, 4, "GigabitEthernet1/1/"),
    _C3850_NM_2_10G: [*_run(1, 2, "GigabitEthernet1/1/"), *_run(3, 2, "TenGigabitEthernet1/1/")],
    _C3850_NM_4_10G: _run(1, 4, "TenGigabitEthernet1/1/"),
    _C3850_NM_8_10G: _run(1, 8, "TenGigabitEthernet1/1/"),
}
#: The data sheet's Table 2, typed out per model.
_C3850_TAKES: dict[str, tuple] = {
    **dict.fromkeys(
        ("WS-C3850-24T", "WS-C3850-24P", "WS-C3850-24U", "WS-C3850-12S", "WS-C3850-24S"),
        ((), _C3850_NM_4_1G, _C3850_NM_2_10G),
    ),
    **dict.fromkeys(
        ("WS-C3850-48T", "WS-C3850-48P", "WS-C3850-48F", "WS-C3850-48U"),
        ((), _C3850_NM_4_1G, _C3850_NM_2_10G, _C3850_NM_4_10G),
    ),
    **dict.fromkeys(
        ("WS-C3850-24XU", "WS-C3850-12X48U"),
        ((), _C3850_NM_4_1G, _C3850_NM_2_10G, _C3850_NM_4_10G, _C3850_NM_8_10G),
    ),
    "WS-C3850-12XS": ((), _C3850_NM_4_10G),
    "WS-C3850-24XS": ((), _C3850_NM_4_10G, _C3850_NM_8_10G),
}
for _model, _access_names in _C3850_PANELS.items():
    for _fitted in _C3850_TAKES[_model]:
        EXPECTED_INVENTORIES[(_C, _model, "stack", _fitted)] = (
            list(_access_names), list(_C3850_BAY_1[_fitted]),
        )

#: Cisco Catalyst 3650: fixed uplinks, module 1 of the switch, as a
#: C9200L's are.  Sources: the 3650 Hardware Installation Guide's
#: Overview (Table 1-1, the uplink ports and their LED labels), and the
#: IOS XE 16.12 configuration guide and command reference.  Inferred
#: (see KNOWN_INFERRED_PARTS): the names of the two 1G and two 10G
#: uplinks, and the Multigigabit ports of the 12X48UQ and -UR at 37-48.
#: Four models are not modelled; the YAML says why.
_C3650_TWO_AND_TWO = [*_run(1, 2, "GigabitEthernet1/1/"), *_run(3, 2, "TenGigabitEthernet1/1/")]
_C3650_MGIG = [*_run(1, 36, "GigabitEthernet1/0/"), *_run(37, 12, "TenGigabitEthernet1/0/")]
_C3650: dict[str, tuple[list[str], list[str]]] = {
    "WS-C3650-24TS": (_run(1, 24, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "WS-C3650-48TS": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "WS-C3650-24PS": (_run(1, 24, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "WS-C3650-48PS": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "WS-C3650-48FS": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "WS-C3650-24TD": (_run(1, 24, "GigabitEthernet1/0/"), _C3650_TWO_AND_TWO),
    "WS-C3650-48TD": (_run(1, 48, "GigabitEthernet1/0/"), _C3650_TWO_AND_TWO),
    "WS-C3650-24PD": (_run(1, 24, "GigabitEthernet1/0/"), _C3650_TWO_AND_TWO),
    "WS-C3650-48PD": (_run(1, 48, "GigabitEthernet1/0/"), _C3650_TWO_AND_TWO),
    "WS-C3650-48FD": (_run(1, 48, "GigabitEthernet1/0/"), _C3650_TWO_AND_TWO),
    "WS-C3650-24PDM": (_run(1, 24, "GigabitEthernet1/0/"), _C3650_TWO_AND_TWO),
    "WS-C3650-48TQ": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "WS-C3650-48PQ": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "WS-C3650-48FQ": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "WS-C3650-48FQM": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "WS-C3650-12X48UQ": (_C3650_MGIG, _TE_UPLINKS),
    "WS-C3650-12X48UR": (_C3650_MGIG, _run(1, 8, "TenGigabitEthernet1/1/")),
}
for _model, (_access_names, _uplinks) in _C3650.items():
    EXPECTED_INVENTORIES[(_C, _model, "stack", ())] = (
        list(_access_names), list(_uplinks),
    )

#: Cisco Catalyst 9300L and 9300LM: one family, since Cisco stacks them
#: together and with nothing else; fixed uplinks, module 1 of the switch.
#: Sources: the C9300 Hardware Installation Guide's Product Overview
#: (Tables 2 and 3), the data sheet's Table 2, and the IOS XE 17.12
#: configuration guides and command reference.  Inferred (see
#: KNOWN_INFERRED_PARTS): the Multigigabit ports of the UXG models and
#: of the C9300LM-48UX at the end of the panel, and the C9300LM's four
#: TwentyFiveGigE uplinks.
_FO_UPLINKS = _run(1, 2, "FortyGigabitEthernet1/1/")
_TWE4_UPLINKS = _run(1, 4, "TwentyFiveGigE1/1/")
_C9300L_24UXG = [*_run(1, 16, "GigabitEthernet1/0/"), *_run(17, 8, "TenGigabitEthernet1/0/")]
_C9300L_48UXG = [*_run(1, 36, "GigabitEthernet1/0/"), *_run(37, 12, "TenGigabitEthernet1/0/")]
_C9300L: dict[str, tuple[list[str], list[str]]] = {
    "C9300L-24T-4G": (_run(1, 24, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9300L-24P-4G": (_run(1, 24, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9300L-24T-4X": (_run(1, 24, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9300L-24P-4X": (_run(1, 24, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9300L-48T-4G": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9300L-48P-4G": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9300L-48T-4X": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9300L-48P-4X": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9300L-48PF-4G": (_run(1, 48, "GigabitEthernet1/0/"), _GI_UPLINKS),
    "C9300L-48PF-4X": (_run(1, 48, "GigabitEthernet1/0/"), _TE_UPLINKS),
    "C9300L-24UXG-4X": (_C9300L_24UXG, _TE_UPLINKS),
    "C9300L-24UXG-2Q": (_C9300L_24UXG, _FO_UPLINKS),
    "C9300L-48UXG-4X": (_C9300L_48UXG, _TE_UPLINKS),
    "C9300L-48UXG-2Q": (_C9300L_48UXG, _FO_UPLINKS),
    "C9300LM-48T-4Y": (_run(1, 48, "GigabitEthernet1/0/"), _TWE4_UPLINKS),
    "C9300LM-24U-4Y": (_run(1, 24, "GigabitEthernet1/0/"), _TWE4_UPLINKS),
    "C9300LM-48U-4Y": (_run(1, 48, "GigabitEthernet1/0/"), _TWE4_UPLINKS),
    "C9300LM-48UX-4Y": (
        [*_run(1, 40, "GigabitEthernet1/0/"), *_run(41, 8, "TenGigabitEthernet1/0/")],
        _TWE4_UPLINKS,
    ),
}
for _model, (_access_names, _uplinks) in _C9300L.items():
    EXPECTED_INVENTORIES[(_C, _model, "stack", ())] = (
        list(_access_names), list(_uplinks),
    )

#: Cisco Catalyst 2960-X and 2960-XR: three families, since a LAN Base
#: 2960-X stacks with no 2960-XR and a LAN Lite switch does not stack.
#: Every port is module 0 of the switch, and "SFP module ports are
#: numbered consecutively following the 10/100/1000 ports".  Sources:
#: the 2960-X and 2960-XR Hardware Installation Guide's Product
#: Overview, the data sheet's Table 27, and the 15.2(2)E and 15.2(6)E
#: configuration guides.  Inferred (see KNOWN_INFERRED_PARTS): a D
#: model's two SFP+ uplinks, TenGigabitEthernet<n>/0/1-2, and every
#: name of a LAN Lite switch.  The
#: WS-C2960X-24PSQ-L is not modelled; the YAML says why.
_C2960X_TE = _run(1, 2, "TenGigabitEthernet1/0/")
_C2960X: dict[str, tuple[list[str], list[str]]] = {
    "WS-C2960X-48FPD-L": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960X-48LPD-L": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960X-24PD-L": (_run(1, 24, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960X-48TD-L": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960X-24TD-L": (_run(1, 24, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960X-48FPS-L": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960X-48LPS-L": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960X-24PS-L": (_run(1, 24, "GigabitEthernet1/0/"), _run(25, 4, "GigabitEthernet1/0/")),
    "WS-C2960X-48TS-L": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960X-24TS-L": (_run(1, 24, "GigabitEthernet1/0/"), _run(25, 4, "GigabitEthernet1/0/")),
}
_C2960X_LL: dict[str, tuple[list[str], list[str]]] = {
    "WS-C2960X-48TS-LL": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 2, "GigabitEthernet1/0/")),
    "WS-C2960X-24TS-LL": (_run(1, 24, "GigabitEthernet1/0/"), _run(25, 2, "GigabitEthernet1/0/")),
}
_C2960XR: dict[str, tuple[list[str], list[str]]] = {
    "WS-C2960XR-48FPD-I": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960XR-48LPD-I": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960XR-24PD-I": (_run(1, 24, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960XR-48TD-I": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960XR-24TD-I": (_run(1, 24, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960XR-48FPS-I": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960XR-48LPS-I": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960XR-24PS-I": (_run(1, 24, "GigabitEthernet1/0/"), _run(25, 4, "GigabitEthernet1/0/")),
    "WS-C2960XR-48TS-I": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960XR-24TS-I": (_run(1, 24, "GigabitEthernet1/0/"), _run(25, 4, "GigabitEthernet1/0/")),
}
#: Cisco Catalyst 2960-S: the LAN Base models, a FlexStack stack of up
#: to four, named as a 2960-X's are.  Sources: the 2960-S Hardware
#: Installation Guide's Product Overview (Table 1-1 and the front-panel
#: figures), the end-of-sale announcement's part numbers, and the
#: 15.0(2)SE configuration guide.  Inferred (see KNOWN_INFERRED_PARTS):
#: a D model's two SFP+ uplinks, TenGigabitEthernet<n>/0/1-2.  The LAN
#: Lite models, the 2960-SF and the 48TS-J1 are not modelled; the YAML
#: says why.
_C2960S: dict[str, tuple[list[str], list[str]]] = {
    "WS-C2960S-48FPD-L": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960S-48LPD-L": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960S-24PD-L": (_run(1, 24, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960S-48TD-L": (_run(1, 48, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960S-24TD-L": (_run(1, 24, "GigabitEthernet1/0/"), _C2960X_TE),
    "WS-C2960S-48FPS-L": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960S-48LPS-L": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960S-24PS-L": (_run(1, 24, "GigabitEthernet1/0/"), _run(25, 4, "GigabitEthernet1/0/")),
    "WS-C2960S-48TS-L": (_run(1, 48, "GigabitEthernet1/0/"), _run(49, 4, "GigabitEthernet1/0/")),
    "WS-C2960S-24TS-L": (_run(1, 24, "GigabitEthernet1/0/"), _run(25, 4, "GigabitEthernet1/0/")),
}
for _models, _mode in (
    (_C2960X, "stack"), (_C2960X_LL, "standalone"), (_C2960XR, "stack"), (_C2960S, "stack"),
):
    for _model, (_access_names, _uplinks) in _models.items():
        EXPECTED_INVENTORIES[(_C, _model, _mode, ())] = (
            list(_access_names), list(_uplinks),
        )

#: Cisco Catalyst 3750-X: one bay, its ports module 1, as a 3850's are.
#: Sources: the 3750-X and 3560-X Hardware Installation Guide's Product
#: Overview (Tables 1-1 and 1-3), the network modules' installation
#: notes, and the 15.0(2)SE and 15.2(4)E configuration guides.  The
#: C3KX-NM-10G and C3KX-SM-10G are described with an SFP+ in each 10G
#: slot, the names Cisco gives them at 10G.  Inferred (see
#: KNOWN_INFERRED_PARTS): the C3KX-NM-1G's and C3KX-NM-10GT's names, and
#: the SFP downlinks of the 12S and 24S.  Every model's bay takes every
#: module: the hardware guide lists the four for the switch and names no
#: exception.
_C3750X_PANELS: dict[str, list[str]] = {
    "WS-C3750X-24T": _run(1, 24, "GigabitEthernet1/0/"),
    "WS-C3750X-48T": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3750X-24P": _run(1, 24, "GigabitEthernet1/0/"),
    "WS-C3750X-48P": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3750X-48PF": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3750X-24U": _run(1, 24, "GigabitEthernet1/0/"),
    "WS-C3750X-48U": _run(1, 48, "GigabitEthernet1/0/"),
    "WS-C3750X-12S": _run(1, 12, "GigabitEthernet1/0/"),
    "WS-C3750X-24S": _run(1, 24, "GigabitEthernet1/0/"),
}
_C3750X_BAY_1: dict[tuple, list[str]] = {
    (): [],
    (("1", "C3KX-NM-1G"),): _run(1, 4, "GigabitEthernet1/1/"),
    (("1", "C3KX-NM-10G"),): _run(1, 2, "TenGigabitEthernet1/1/"),
    (("1", "C3KX-NM-10GT"),): _run(1, 2, "TenGigabitEthernet1/1/"),
    (("1", "C3KX-SM-10G"),): _run(1, 2, "TenGigabitEthernet1/1/"),
}
for _model, _access_names in _C3750X_PANELS.items():
    for _fitted, _uplinks in _C3750X_BAY_1.items():
        EXPECTED_INVENTORIES[(_C, _model, "stack", _fitted)] = (
            list(_access_names), list(_uplinks),
        )

#: Family key -> the ports of the whole deployment, after every
#: member's: a stack has ONE management interface, whichever switch is
#: active.
EXPECTED_DEPLOYMENT_PORTS: dict[str, list[str]] = {
    "cisco_iosxe/C9300": ["GigabitEthernet0/0"],
    "cisco_iosxe/C9300-higher-scale": ["GigabitEthernet0/0"],
    "cisco_iosxe/C9200": ["GigabitEthernet0/0"],
    "cisco_iosxe/C9200-PB": ["GigabitEthernet0/0"],
    "cisco_iosxe/C9200L": ["GigabitEthernet0/0"],
    "cisco_iosxe/C3850": ["GigabitEthernet0/0"],
    "cisco_iosxe/C3650": ["GigabitEthernet0/0"],
    "cisco_iosxe/C9300L": ["GigabitEthernet0/0"],
    "cisco_iosxe/C2960X": ["FastEthernet0"],
    "cisco_iosxe/C2960X-LL": ["FastEthernet0"],
    "cisco_iosxe/C2960S": ["FastEthernet0"],
    "cisco_iosxe/C2960XR": ["FastEthernet0"],
    "cisco_iosxe/C3750X": ["FastEthernet0"],
}


def _every_combination() -> list[tuple[str, str, str, tuple]]:
    out = []
    for family, model in _every_model():
        for mode_name in family.modes:
            if not family.supports(model, mode_name):
                continue
            for modules in _module_choices(model):
                fitted = tuple(sorted((b, s) for b, s in modules.items() if s))
                out.append((family.vendor, model.model, mode_name, fitted))
    return out


class TestExactInventories:
    def test_every_shipped_combination_is_pinned(self) -> None:
        """A model, a mode or a module added to a family file without
        its ports being written out here is not covered by anything."""
        assert set(_every_combination()) == set(EXPECTED_INVENTORIES)

    @pytest.mark.parametrize(
        "combo", sorted(EXPECTED_INVENTORIES), ids=lambda c: f"{c[1]}-{c[2]}-{c[3]}",
    )
    def test_ports_and_roles(self, combo: tuple[str, str, str, tuple]) -> None:
        vendor, model, mode, fitted = combo
        access, uplinks = EXPECTED_INVENTORIES[combo]
        family = REGISTRY.resolve(vendor, model)[0]
        mgmt = EXPECTED_DEPLOYMENT_PORTS.get(family.key, [])
        inventory = _compile(vendor, mode, {"model": model, "modules": dict(fitted)})
        assert inventory.names(role="access") == access
        assert inventory.names(role="uplink") == uplinks
        assert inventory.names(role="mgmt") == mgmt
        assert inventory.names() == access + uplinks + mgmt

    def test_every_deployment_port_is_pinned(self) -> None:
        assert {
            family.key: [p.name for p in family.deployment_ports]
            for family in REGISTRY.families.values() if family.deployment_ports
        } == EXPECTED_DEPLOYMENT_PORTS

    @pytest.mark.parametrize(
        ("family", "model"),
        [(f, m) for f, m in _every_model() if f.naming == "aoss"],
        ids=_model_id,
    )
    def test_the_name_says_how_many_access_ports(
        self, family: FamilyDef, model: ModelDef,
    ) -> None:
        """``48G`` in a product name is 48 gigabit access ports, and
        ``8SR`` is eight Smart Rate (multi-gigabit) ones: a 2930M
        "40G 8SR" has 40 + 8, not 40.  Catches a count typed against
        the wrong model."""
        gig = re.search(r"-(\d+)G\b", model.display_name)
        smart_rate = re.search(r"-(\d+)SR\b", model.display_name)
        assert gig or smart_rate, model.display_name
        access = [g for g in model.ports if g.role == "access"]
        assert sum(g.count for g in access if g.speed == "gig") == (
            int(gig.group(1)) if gig else 0
        ), model.display_name
        assert sum(g.count for g in access if g.speed != "gig") == (
            int(smart_rate.group(1)) if smart_rate else 0
        ), model.display_name

    @pytest.mark.parametrize(
        ("family", "model"),
        [(f, m) for f, m in _every_model() if f.naming == "catalyst"],
        ids=_model_id,
    )
    def test_a_catalyst_pid_says_how_many_access_ports(
        self, family: FamilyDef, model: ModelDef,
    ) -> None:
        """``C9300-48UXM`` is 48 access ports, whatever their types, a
        3850's ``12X48U`` is 48 of which twelve are Multigigabit, a
        C9200L's ``-4X`` is its four fixed 10G uplinks, a C9300L's
        ``-2Q`` its two 40G ones, and a C9300X's ``-48HX`` or a 3750-X's
        ``-48PF`` 48 access ports and no fixed uplink.  A 3650's letter
        after its PoE letter is its fixed uplinks, as the hardware
        guide's Table 1-1 gives them for the models modelled: S four 1G,
        D two 1G and two 10G, Q four 10G, R eight 10G.  A 2960-X's,
        2960-XR's or 2960-S's letter after its PoE letters is its fixed
        uplinks, as the hardware guides' Product Overviews give them: D
        two SFP+ (10G), S four SFP (1G), or two on a LAN Lite (``-LL``)
        switch."""
        sku = model.skus[0]
        fixed = [(g.count, g.speed) for g in model.ports if g.role == "uplink"]
        if sku.startswith("WS-C3650-"):
            count = re.fullmatch(r"WS-C3650-(?:\d+X(?=\d))?(\d+)[TPFU]([SDQR])M?", sku)
            assert count, sku
            assert fixed == {
                "S": [(4, "gig")], "D": [(2, "gig"), (2, "10gig")],
                "Q": [(4, "10gig")], "R": [(8, "10gig")],
            }[count.group(2)], sku
        elif sku.startswith(("WS-C2960X", "WS-C2960S")):
            count = re.fullmatch(r"WS-C2960(?:XR?|S)-(\d+)(?:FP|LP|P|T)([DS])-(LL|L|I)", sku)
            assert count, sku
            assert fixed == (
                [(2, "10gig")] if count.group(2) == "D"
                else [(2, "gig")] if count.group(3) == "LL"
                else [(4, "gig")]
            ), sku
        else:
            count = re.fullmatch(
                r"(?:C9[23]00(?:LM|L|X)?|WS-C3850|WS-C3750X)-(?:\d+X(?=\d))?(\d+)[A-Z]+(?:-(\d)([GXQY]))?",
                sku,
            )
            assert count, sku
            if count.group(2) is None:
                assert not fixed, sku
            else:
                speed = {"G": "gig", "X": "10gig", "Q": "40gig", "Y": "25gig"}[count.group(3)]
                assert fixed == [(int(count.group(2)), speed)], sku
        assert sum(g.count for g in model.ports if g.role == "access") == int(
            count.group(1)
        ), sku


#: A Catalyst interface type and the top speed it stands for, typed from
#: the configuration guide's list of interface types (HundredGigE from
#: the hardware guide's C9300X network-module tables; FastEthernet, a
#: 2960-X's 10/100 management port, from its configuration guide).  The
#: data says both for every group; they are stated apart, so they can
#: disagree.
_SPEED_OF_TYPE: dict[str, str] = {
    "FastEthernet": "fast",
    "GigabitEthernet": "gig",
    "TwoGigabitEthernet": "2.5gig",
    "FiveGigabitEthernet": "5gig",
    "TenGigabitEthernet": "10gig",
    "TwentyFiveGigE": "25gig",
    "FortyGigabitEthernet": "40gig",
    "HundredGigE": "100gig",
}


class TestCatalystTypeAndSpeed:
    @pytest.mark.parametrize(
        "family",
        [f for f in REGISTRY.families.values() if f.naming == "catalyst"],
        ids=lambda f: f.key,
    )
    def test_every_group_states_the_speed_its_type_names(self, family: FamilyDef) -> None:
        groups = [
            (model.model, group)
            for model in family.models.values() for group in model.ports
        ] + [
            (module.sku, group)
            for module in family.modules.values() for group in module.ports
        ]
        for owner, group in groups:
            assert _SPEED_OF_TYPE[group.prefix] == group.speed, (owner, group.prefix)
        for port in family.deployment_ports:
            prefix = re.match(r"[A-Za-z]+", port.name).group(0)
            assert _SPEED_OF_TYPE[prefix] == port.speed, port.name


# ---------------------------------------------------------------------------
# Grammar round trip
# ---------------------------------------------------------------------------

#: Names the vendor's own classifier does not recognise although the
#: device uses them.  AOS-S names a flexible-module port on a switch that
#: is NOT in stacking mode with a bare letter and number (``A1``); the
#: AOS-S classifier knows the stacked form (``1/A1``) only.  Model-driven
#: mapping does not need a name to classify — an explicit rename entry is
#: applied before classification — so this is a pinned gap, not a
#: blocker.  Rot-fail: when the classifier learns the form, the test
#: below fails and this exception goes in the same change.
_UNCLASSIFIED_BARE_LETTER = re.compile(r"^[A-Z]\d+$")


#: Naming rule -> the codec whose grammar it writes.  Two codecs share
#: the ``cisco_iosxe`` vendor id; the Catalyst names are the CLI's.
_CODEC_OF_RULE: dict[str, str] = {
    "aoss": "aruba_aoss",
    "catalyst": "cisco_iosxe_cli",
}


class TestCompiledNamesRoundTripThroughTheCodec:
    """Will this name survive the render path?  NOT evidence that the
    name is right — the data and the classifier can be wrong together."""

    def test_every_rule_has_its_codec(self) -> None:
        assert set(_CODEC_OF_RULE) == set(dm._naming_rules())
        for rule, codec in _CODEC_OF_RULE.items():
            assert codec in list_public_codecs(), rule

    @pytest.mark.parametrize(("family", "model"), _every_model(), ids=_model_id)
    def test_the_classifier_recovers_member_slot_and_port(
        self, family: FamilyDef, model: ModelDef,
    ) -> None:
        codec = get_codec(_CODEC_OF_RULE[family.naming])
        assert vendor_of(_CODEC_OF_RULE[family.naming]) == family.vendor
        checked = 0
        for mode_name, modules in product(family.modes, _module_choices(model)):
            if not family.supports(model, mode_name):
                continue
            inventory = _compile(
                family.vendor, mode_name,
                {"model": model.model, "modules": modules},
            )
            for port in inventory.ports:
                if port.member_rank is None:
                    # A port of the whole deployment is typed whole in
                    # the family file; no rule made it.
                    continue
                identity = codec.classify_port_name(port.name)
                where = (model.model, mode_name, port.name)
                if identity.kind == "unknown":
                    assert port.member_id is None and (
                        _UNCLASSIFIED_BARE_LETTER.match(port.name)
                    ), where
                    continue
                assert identity.kind == "physical", (*where, identity.kind)
                assert identity.stack == port.member_id, where
                if family.naming == "catalyst":
                    assert identity.module == int(port.slot or "0"), where
                else:
                    assert identity.subslot_letter == port.slot, where
                assert identity.port == port.index + 1, where
                checked += 1
        assert checked, f"{model.model}: no name was checked"

    def test_the_bare_letter_gap_is_still_a_gap(self) -> None:
        """Rot-fail for :data:`_UNCLASSIFIED_BARE_LETTER`."""
        assert get_codec("aruba_aoss").classify_port_name("A1").kind == "unknown"


# ---------------------------------------------------------------------------
# Agreement with the flat target profiles
# ---------------------------------------------------------------------------

#: Target profiles that describe a device a family also models, with the
#: deployment that is the profile's stated state — addressed by PART
#: NUMBER, never by key: the legacy keys are not consistent with each
#: other (``2930F-24G`` is the SFP+ model, ``2930F-48G`` the 1G-SFP one).
#: Every such profile must be listed (the completeness test finds them
#: by the part number in their display name, or by a model that is a
#: part number a family models).  A Cisco profile states the network
#: module it preselects (the C9300-NM-8X) and stack member 1.
#:
#: Where both exist, the family is authoritative for port mapping; the
#: profile keeps feeding the older dropdown until it is retired.
PROFILE_AGREES_WITH: dict[str, dict] = {
    "aruba_aoss/2930F-24G": {"mode": "standalone", "members": [{"model": "JL253A"}]},
    "aruba_aoss/2930F-24G-PoEP": {"mode": "standalone", "members": [{"model": "JL255A"}]},
    "aruba_aoss/2930F-48G": {"mode": "standalone", "members": [{"model": "JL260A"}]},
    "aruba_aoss/2930F-48G-PoEP": {"mode": "standalone", "members": [{"model": "JL256A"}]},
    **{
        f"cisco_iosxe/{pid}": {
            "mode": "stack",
            "members": [{"model": pid, "id": 1, "modules": {"1": "C9300-NM-8X"}}],
        }
        for pid in (
            "C9300-24P", "C9300-24U", "C9300-24UX",
            "C9300-48P", "C9300-48U", "C9300-48UXM",
        )
    },
}

_PART_NUMBER = re.compile(r"\(([A-Z0-9-]+)\)")


def _comparable(inventory: Inventory) -> list[tuple]:
    """The ports as one role's list after another.  A profile lists its
    management port among the chassis ports and a family after every
    member's: where it sits in the list is not something either says."""
    return sorted(
        ((p.role, p.ordinal, p.name, p.speed, p.poe) for p in inventory.ports),
    )


class TestAgreementWithTargetProfiles:
    @pytest.mark.parametrize("key", sorted(PROFILE_AGREES_WITH))
    def test_profile_and_model_describe_the_same_ports(self, key: str) -> None:
        profile = PROFILES[key]
        spec = PROFILE_AGREES_WITH[key]
        compiled = _compile(profile.vendor, spec["mode"], *spec["members"])
        assert _comparable(inventory_from_profile(profile)) == _comparable(compiled), (
            f"{key} and the device model disagree about the same device"
        )

    def test_every_profile_of_a_modelled_device_is_checked(self) -> None:
        """A profile whose display name carries a part number a family
        models must be in :data:`PROFILE_AGREES_WITH` — otherwise the
        two registries can drift apart on that device unnoticed."""
        modelled = set()
        for key, profile in PROFILES.items():
            for part in [*_PART_NUMBER.findall(profile.display_name), profile.model]:
                if REGISTRY.resolve(profile.vendor, part) is not None:
                    modelled.add(key)
        assert modelled == set(PROFILE_AGREES_WITH)

    def test_a_family_key_never_collides_with_an_unrelated_profile_key(self) -> None:
        """A family model may share a key with a profile only when the
        two are the SAME device (listed above).  ``2930F-48G`` as a
        family key for the SFP+ model would silently pair it with the
        legacy 1G-SFP profile of that name."""
        for family, model in _every_model():
            key = f"{family.vendor}/{model.model}"
            if key not in PROFILES:
                continue
            assert key in PROFILE_AGREES_WITH, key
            twin = PROFILE_AGREES_WITH[key]["members"][0]["model"]
            assert REGISTRY.resolve(family.vendor, twin)[1].model == model.model, key


# ---------------------------------------------------------------------------
# Hardware facts, pinned
# ---------------------------------------------------------------------------

#: Part numbers that are NOT port-contributing modules.  The 2026-10
#: registry audit found a stacking module and a power supply listed as
#: 40G uplink modules in the older registry; this keeps the same mistake
#: out of the new one.
_NOT_A_PORT_MODULE = {
    "JL084A",  # 3810M stacking module
    "JL085A",  # 250 W power supply
    "JL325A",  # 2930M stacking module
    "J9733A",  # 2920 stacking module
}


class TestNoStackingModuleOrPowerSupplyIsAPortModule:
    def test_module_keys(self) -> None:
        for family in REGISTRY.families.values():
            assert not _NOT_A_PORT_MODULE & set(family.modules), family.key


class TestAruba2930F:
    """A 2930F has no module slot; its uplinks continue the access
    numbering; and VSF, not the model, decides whether a name carries a
    member number."""

    FAMILY = REGISTRY.families["aruba_aoss/2930F"]

    def test_no_2930f_has_a_bay_or_a_letter_port(self) -> None:
        assert not self.FAMILY.modules
        for model in self.FAMILY.models.values():
            assert not model.bays, model.model
            for mode_name in self.FAMILY.modes:
                names = _compile("aruba_aoss", mode_name, {"model": model.model}).names()
                lettered = [n for n in names if any(ch.isalpha() for ch in n)]
                assert not lettered, (model.model, mode_name, lettered)

    def test_a_lone_vsf_member_need_not_be_member_one(self) -> None:
        inventory = _compile("aruba_aoss", "vsf", {"model": "JL253A", "id": 3})
        assert inventory.names(role="uplink") == ["3/25", "3/26", "3/27", "3/28"]

    def test_a_vsf_fabric_holds_eight_members_and_mixes_models(self) -> None:
        eight = [{"model": "JL260A"}] * 4 + [{"model": "JL253A"}] * 4
        inventory = _compile("aruba_aoss", "vsf", *eight)
        assert inventory.member_count == 8
        assert inventory.names(member_rank=7)[-1] == "8/28"
        with pytest.raises(Exception, match="at most 8 members"):
            _compile("aruba_aoss", "vsf", *eight, {"model": "JL253A"})

    def test_standalone_is_the_default_and_is_one_device(self) -> None:
        assert self.FAMILY.default_mode == "standalone"
        inventory = _compile("aruba_aoss", None, {"model": "JL260A"})
        assert inventory.names()[0] == "1"
        assert inventory.mode_defaulted

    def test_there_are_sixteen_2930f_models(self) -> None:
        """HPE has shipped sixteen 2930F chassis J-numbers (the install
        guide, the QuickSpecs, the configuration guide and the vendor
        MIB each enumerate the same set)."""
        skus = sorted(m.skus[0] for m in self.FAMILY.models.values())
        assert skus == [
            "JL253A", "JL254A", "JL255A", "JL256A", "JL258A", "JL259A",
            "JL260A", "JL261A", "JL262A", "JL263A", "JL264A", "JL557A",
            "JL558A", "JL559A", "JL692A", "JL693A",
        ]

    @pytest.mark.parametrize(
        ("sku", "speed", "cage"),
        [
            # "4SFP" in the product name: 1G SFP cages.
            ("JL259A", "gig", "sfp"), ("JL260A", "gig", "sfp"),
            ("JL261A", "gig", "sfp"), ("JL262A", "gig", "sfp"),
            # The JL557A is 1G SFP although the current QuickSpecs
            # prints "4 SFP+" in its block (the same block gives 104
            # Gb/s, which only 1G uplinks add up to).
            ("JL557A", "gig", "sfp"),
            # "4SFP+" / "2SFP+": 1G/10G SFP+ cages.
            ("JL253A", "10gig", "sfp+"), ("JL254A", "10gig", "sfp+"),
            ("JL255A", "10gig", "sfp+"), ("JL256A", "10gig", "sfp+"),
            ("JL258A", "10gig", "sfp+"), ("JL263A", "10gig", "sfp+"),
            ("JL264A", "10gig", "sfp+"), ("JL692A", "10gig", "sfp+"),
            # The JL558A is SFP+ although the QuickSpecs ordering table
            # gives it the 1G-only transceiver rules (and, in V20,
            # printed "4 SFP 1G ports" for it).
            ("JL558A", "10gig", "sfp+"), ("JL559A", "10gig", "sfp+"),
        ],
    )
    def test_uplink_class(self, sku: str, speed: str, cage: str) -> None:
        uplinks = [
            p for p in _compile("aruba_aoss", None, {"model": sku}).ports
            if p.role == "uplink"
        ]
        assert {(p.speed, p.cage) for p in uplinks} == {(speed, cage)}, sku

    def test_the_12_port_model_has_two_kinds_of_uplink(self) -> None:
        """JL693A: ports 13-14 are copper gigabit WITHOUT PoE, 15-16
        are SFP+.  HPE calls all four uplinks."""
        ports = {p.name: p for p in _compile("aruba_aoss", None, {"model": "JL693A"}).ports}
        assert all(ports[str(n)].poe for n in range(1, 13))
        for name in ("13", "14"):
            assert (ports[name].role, ports[name].speed, ports[name].cage,
                    ports[name].poe) == ("uplink", "gig", "rj45", False)
        for name in ("15", "16"):
            assert (ports[name].role, ports[name].speed, ports[name].cage) == (
                "uplink", "10gig", "sfp+")

    def test_poe_models(self) -> None:
        for model in self.FAMILY.models.values():
            access = [g for g in model.ports if g.role == "access"]
            assert all(g.poe for g in access) == ("PoE" in model.display_name), (
                model.display_name
            )

    def test_a_taa_twin_does_not_inherit_its_siblings_capture(self) -> None:
        """Same ports, different J-number.  A JL692A config identifies
        itself as a JL692A; the committed JL258A capture proves nothing
        about it."""
        twin = _compile("aruba_aoss", "standalone", {"model": "JL692A"})
        captured = _compile("aruba_aoss", "standalone", {"model": "JL258A"})
        assert twin.names() == captured.names()
        assert captured.evidence == "capture"
        assert twin.evidence == "vendor-doc"

    def test_an_ordering_alias_resolves_to_the_same_hardware(self) -> None:
        """``JL256ACM`` is how the JL256A is ordered in the US and
        Canada; an operator reading a purchase order may type it."""
        assert REGISTRY.resolve("aruba_aoss", "JL256ACM")[1].model == (
            REGISTRY.resolve("aruba_aoss", "JL256A")[1].model
        )


class TestAruba2930M:
    """A 2930M has one uplink bay, ``A``, and names its ports with or
    without a member number depending on whether stacking is enabled —
    a state that depends on the unit's history, not its model."""

    FAMILY = REGISTRY.families["aruba_aoss/2930M"]

    def test_there_are_eight_2930m_models(self) -> None:
        skus = sorted(m.skus[0] for m in self.FAMILY.models.values())
        assert skus == [
            "JL319A", "JL320A", "JL321A", "JL322A", "JL323A", "JL324A",
            "R0M67A", "R0M68A",
        ]

    def test_every_model_has_exactly_bay_a_taking_the_three_modules(self) -> None:
        """One bay, lettered ``A``, on every chassis; it takes the SFP+,
        QSFP+ or Smart Rate module.  The JL079A (2-port QSFP+) is a
        3810M module and is not accepted."""
        assert set(self.FAMILY.modules) == {"JL083A", "JL078A", "JL081A"}
        for model in self.FAMILY.models.values():
            assert list(model.bays) == ["A"], model.model
            assert model.bays["A"].accepts == ["JL083A", "JL078A", "JL081A"]

    def test_the_fixed_panel_is_all_access_ports(self) -> None:
        """The dual-personality ports are access ports.  As uplinks
        they would take a 2930F's 49-52 ahead of the SFP+ module and
        push four access ports off the end."""
        for model in self.FAMILY.models.values():
            assert {g.role for g in model.ports} == {"access"}, model.model
            assert not any(g.slot for g in model.ports), model.model

    def test_a_48_port_poe_with_the_sfp_plus_module_stacked(self) -> None:
        """2930M-48G-PoE+ with a JL083A, stacking enabled, one unit:
        ``1/1``-``1/48`` and ``1/A1``-``1/A4``."""
        inventory = _compile(
            "aruba_aoss", "stacked",
            {"model": "JL322A", "modules": {"A": "JL083A"}},
        )
        assert inventory.names(role="access") == _run(1, 48, "1/")
        assert inventory.names(role="uplink") == ["1/A1", "1/A2", "1/A3", "1/A4"]
        assert inventory.evidence == "vendor-doc"

    def test_the_same_unit_with_stacking_disabled(self) -> None:
        inventory = _compile(
            "aruba_aoss", "standalone",
            {"model": "JL322A", "modules": {"A": "JL083A"}},
        )
        assert inventory.names() == [*_run(1, 48), "A1", "A2", "A3", "A4"]

    def test_stacking_is_the_default_and_the_inventory_says_so(self) -> None:
        inventory = _compile("aruba_aoss", None, {"model": "JL322A"})
        assert (inventory.mode, inventory.mode_defaulted) == ("stacked", True)
        assert inventory.names()[0] == "1/1"
        assert any("No deployment mode was stated" in c for c in inventory.caveats)

    def test_an_empty_bay_has_no_uplinks(self) -> None:
        inventory = _compile("aruba_aoss", "stacked", {"model": "JL322A", "modules": {"A": None}})
        assert inventory.names(role="uplink") == []
        assert len(inventory.ports) == 48

    def test_the_qsfp_module_is_one_port(self) -> None:
        inventory = _compile(
            "aruba_aoss", "stacked", {"model": "JL322A", "modules": {"A": "JL078A"}},
        )
        (port,) = [p for p in inventory.ports if p.role == "uplink"]
        assert (port.name, port.speed, port.cage) == ("1/A1", "40gig", "qsfp+")

    def test_smart_rate_ports_come_first_on_the_40g_8sr_models(self) -> None:
        """The chassis prints "HPE Smart Rate ... Ports (1-8)" and
        "10/100/1000 BASE-T ... Ports (9-48T)".  HPE's QuickSpecs lists
        the port types in another order (36, 4 combo, 8 Smart Rate),
        which is a listing order and not the faceplate."""
        for sku in ("JL323A", "R0M67A"):
            ports = _compile("aruba_aoss", "standalone", {"model": sku}).ports
            assert {p.speed for p in ports[:8]} == {"10gig"}, sku
            assert {p.speed for p in ports[8:]} == {"gig"}, sku
            assert {p.cage for p in ports[44:]} == {"combo"}, sku
            assert {p.cage for p in ports[:44]} == {"rj45"}, sku

    @pytest.mark.parametrize(
        ("sku", "combo"),
        [("JL319A", _run(21, 4)), ("JL320A", _run(21, 4)),
         ("JL321A", _run(45, 4)), ("JL322A", _run(45, 4)),
         ("JL324A", []), ("R0M68A", [])],
    )
    def test_dual_personality_ports_are_the_last_four(
        self, sku: str, combo: list[str],
    ) -> None:
        ports = _compile("aruba_aoss", "standalone", {"model": sku}).ports
        assert [p.name for p in ports if p.cage == "combo"] == combo

    def test_the_all_smart_rate_models_top_out_at_five_gig(self) -> None:
        """JL324A / R0M68A Smart Rate ports are 1/2.5/5G — "no 10G
        support" (install guide, Table 3 note)."""
        for sku in ("JL324A", "R0M68A"):
            ports = _compile("aruba_aoss", "standalone", {"model": sku}).ports
            assert {p.speed for p in ports} == {"5gig"}, sku

    def test_a_stack_holds_ten_members_and_mixes_models(self) -> None:
        ten = [{"model": "JL322A", "modules": {"A": "JL083A"}}] * 5 + [{"model": "JL319A"}] * 5
        inventory = _compile("aruba_aoss", "stacked", *ten)
        assert inventory.member_count == 10
        assert inventory.names(member_rank=0)[-1] == "1/A4"
        assert inventory.names(member_rank=9) == _run(1, 24, "10/")
        with pytest.raises(Exception, match="at most 10 members"):
            _compile("aruba_aoss", "stacked", *ten, {"model": "JL319A"})

    def test_a_2930m_and_a_2930f_cannot_share_a_deployment(self) -> None:
        """HPE: "You cannot stack a 2930M with a 2920 switch. You can
        only stack similar switches"."""
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("aruba_aoss", "stacked", {"model": "JL322A"}, {"model": "JL260A"})

    def test_the_capture_covers_exactly_what_it_shows(self) -> None:
        """The committed capture is a JL323A + JL083A as member 1.  A
        JL322A — the same port names — is a different model; the same
        JL323A with the QSFP+ module, or as member 2, is a deployment
        the capture does not show."""
        captured = _compile(
            "aruba_aoss", "stacked",
            {"model": "JL323A", "id": 1, "modules": {"A": "JL083A"}},
        )
        assert {p.evidence for p in captured.ports} == {"capture"}
        sibling = _compile(
            "aruba_aoss", "stacked", {"model": "JL322A", "modules": {"A": "JL083A"}},
        )
        assert sibling.names() == captured.names()
        assert "capture" not in {p.evidence for p in sibling.ports}
        other_module = _compile(
            "aruba_aoss", "stacked", {"model": "JL323A", "modules": {"A": "JL078A"}},
        )
        assert {p.evidence for p in other_module.ports if not p.module} == {"capture"}
        assert {p.evidence for p in other_module.ports if p.module} == {"vendor-doc"}
        as_member_two = _compile(
            "aruba_aoss", "stacked",
            {"model": "JL323A", "id": 2, "modules": {"A": "JL083A"}},
        )
        assert "capture" not in {p.evidence for p in as_member_two.ports}


# ---------------------------------------------------------------------------
# Part numbers and grades, pinned
# ---------------------------------------------------------------------------

#: Part number -> model key, typed by hand from the vendor's own lists
#: (the install guides' Table 3 and the QuickSpecs).  A comment beside a
#: panel table is not a guard: two J-numbers swapped in a family file
#: would compile a 48-port switch as a 24-port one with every other
#: test green.
EXPECTED_PART_NUMBERS: dict[tuple[str, str], str] = {
    # Aruba 2930F
    ("aruba_aoss", "JL253A"): "2930F-24G-4SFPP",
    ("aruba_aoss", "JL254A"): "2930F-48G-4SFPP",
    ("aruba_aoss", "JL255A"): "2930F-24G-PoEP-4SFPP",
    ("aruba_aoss", "JL256A"): "2930F-48G-PoEP-4SFPP",
    ("aruba_aoss", "JL258A"): "2930F-8G-PoEP-2SFPP",
    ("aruba_aoss", "JL259A"): "2930F-24G-4SFP",
    ("aruba_aoss", "JL260A"): "2930F-48G-4SFP",
    ("aruba_aoss", "JL261A"): "2930F-24G-PoEP-4SFP",
    ("aruba_aoss", "JL262A"): "2930F-48G-PoEP-4SFP",
    ("aruba_aoss", "JL263A"): "2930F-24G-PoEP-4SFPP-TAA",
    ("aruba_aoss", "JL264A"): "2930F-48G-PoEP-4SFPP-TAA",
    ("aruba_aoss", "JL557A"): "2930F-48G-740W-PoEP-4SFP",
    ("aruba_aoss", "JL558A"): "2930F-48G-740W-PoEP-4SFPP",
    ("aruba_aoss", "JL559A"): "2930F-48G-740W-PoEP-4SFPP-TAA",
    ("aruba_aoss", "JL692A"): "2930F-8G-PoEP-2SFPP-TAA",
    ("aruba_aoss", "JL693A"): "2930F-12G-PoEP-2G-2SFPP",
    # Aruba 2930M
    ("aruba_aoss", "JL319A"): "2930M-24G",
    ("aruba_aoss", "JL320A"): "2930M-24G-PoEP",
    ("aruba_aoss", "JL321A"): "2930M-48G",
    ("aruba_aoss", "JL322A"): "2930M-48G-PoEP",
    ("aruba_aoss", "JL323A"): "2930M-40G-8SR-PoEP",
    ("aruba_aoss", "JL324A"): "2930M-24SR-PoEP",
    ("aruba_aoss", "R0M67A"): "2930M-40G-8SR-PoE-Class6",
    ("aruba_aoss", "R0M68A"): "2930M-24SR-PoE-Class6",
    # Cisco Catalyst 9300 and 9300X: the PID is the model key.
    **{
        ("cisco_iosxe", pid): pid
        for pid in (
            "C9300-24T", "C9300-48T", "C9300-24P", "C9300-48P",
            "C9300-24U", "C9300-48U", "C9300-24H", "C9300-48H",
            "C9300-24S", "C9300-48S", "C9300-24UX", "C9300-48UXM",
            "C9300-48UN", "C9300-24UB", "C9300-48UB", "C9300-24UXB",
            "C9300X-12Y", "C9300X-24Y", "C9300X-24HX", "C9300X-48HX", "C9300X-48TX",
        )
    },
    # Cisco Catalyst 9200, 9200L, 3850, 3650, 9300L, 9300LM, 2960-X,
    # 2960-XR, 2960-S and 3750-X: the PID is the model key (a 3850's,
    # 3650's or 3750-X's without its license suffix; a 2960-X's or
    # 2960-S's with it, since it is part of the PID).
    **{
        ("cisco_iosxe", pid): pid
        for pid in (
            *_C9200_PANELS, *_C9200L, *_C3850_PANELS, *_C3650, *_C9300L,
            *_C2960X, *_C2960X_LL, *_C2960XR, *_C2960S, *_C3750X_PANELS,
        )
    },
}

#: Parts graded ``inferred``, as ``family key / kind / name``.  Every
#: other graded part is ``vendor-doc``.  A part that is lowered to
#: ``inferred``, or raised out of it, changes this set in the same
#: review.
KNOWN_INFERRED_PARTS: set[str] = {
    # Twelve Multigigabit ports, which Cisco's "41-48" for a 48-port
    # switch cannot hold; 37-48 is read from the TenGigabitEthernet
    # range of the command reference.
    "cisco_iosxe/C9200L / panel / C9200L-48PXG-4X",
    # Twelve Multigigabit ports that Cisco numbers nowhere; 37-48 is read
    # from the command reference's TenGigabitEthernet range and the
    # configuration guide's example of port 37.
    "cisco_iosxe/C3850 / panel / WS-C3850-12X48U",
    # Two 1G slots on the left, two 1G/10G on the right, and no name
    # for any of the four in a Cisco document read.
    "cisco_iosxe/C3850 / module / C3850-NM-2-10G",
    # Two 1G and two 10G uplinks that Cisco labels G1-G4, the two on the
    # right also TE3 and TE4, and names in no interface list.
    *(
        f"cisco_iosxe/C3650 / panel / {pid}"
        for pid in (
            "WS-C3650-24TD", "WS-C3650-48TD", "WS-C3650-24PD",
            "WS-C3650-48PD", "WS-C3650-48FD", "WS-C3650-24PDM",
        )
    ),
    # Twelve Multigigabit ports that Cisco numbers nowhere; 37-48 is read
    # from the command reference's TenGigabitEthernet range and the
    # configuration guide's examples of ports 37 and 43.
    "cisco_iosxe/C3650 / panel / WS-C3650-12X48UQ",
    "cisco_iosxe/C3650 / panel / WS-C3650-12X48UR",
    # Multigigabit ports that Cisco numbers nowhere (and that the
    # configuration guide says a C9300L does not have), taken as the
    # last ports of the panel; and the C9300LM's four 25G uplinks, where
    # the command reference numbers TwentyFiveGigE ports 1 to 2 only.
    *(
        f"cisco_iosxe/C9300L / panel / {pid}"
        for pid in (
            "C9300L-24UXG-4X", "C9300L-24UXG-2Q", "C9300L-48UXG-4X", "C9300L-48UXG-2Q",
            "C9300LM-48T-4Y", "C9300LM-24U-4Y", "C9300LM-48U-4Y", "C9300LM-48UX-4Y",
        )
    ),
    # The ports of a C9300X's own panel, which no Cisco document read
    # names: the command reference names no C9300X, and its ranges hold
    # neither a TwentyFiveGigE port of module 0 nor ports 25-36.
    *(
        f"cisco_iosxe/C9300 / panel / {pid}"
        for pid in ("C9300X-12Y", "C9300X-24Y", "C9300X-24HX", "C9300X-48HX", "C9300X-48TX")
    ),
    # A 2960-X's or 2960-XR's two SFP+ uplinks, which no sentence of
    # its configuration guides numbers, and which their examples name
    # on module 0 in one release and on module 1 in the next.
    *(f"cisco_iosxe/C2960X / panel / {pid}" for pid in _C2960X if "D-" in pid),
    *(f"cisco_iosxe/C2960XR / panel / {pid}" for pid in _C2960XR if "D-" in pid),
    # A 2960-S's two SFP+ uplinks, which its configuration guide names
    # nowhere; its hardware guide labels the slots 1 and 2.
    *(f"cisco_iosxe/C2960S / panel / {pid}" for pid in _C2960S if "D-" in pid),
    # A 2960-X LAN Lite switch's names: the interface chapters of the
    # 2960-X guides give only names with a switch number and say
    # nothing of LAN Lite, and the 2960-S guide names a port of a LAN
    # Lite 2960-S with none.
    "cisco_iosxe/C2960X-LL / mode naming / standalone",
    # A 3750-X module's ports that no Cisco document read names (the
    # C3KX-NM-1G's four, the C3KX-NM-10GT's two), and the SFP downlinks
    # of the 12S and 24S, which its guides number nowhere.
    "cisco_iosxe/C3750X / module / C3KX-NM-1G",
    "cisco_iosxe/C3750X / module / C3KX-NM-10GT",
    "cisco_iosxe/C3750X / panel / WS-C3750X-12S",
    "cisco_iosxe/C3750X / panel / WS-C3750X-24S",
}


def _graded_parts() -> dict[str, str]:
    parts: dict[str, str] = {}
    for family in REGISTRY.families.values():
        for name, mode in family.modes.items():
            parts[f"{family.key} / mode naming / {name}"] = mode.naming.grade
            if mode.bay_naming is not None:
                parts[f"{family.key} / mode bay naming / {name}"] = mode.bay_naming.grade
        for sku, module in family.modules.items():
            parts[f"{family.key} / module / {sku}"] = module.inventory.grade
        for key, model in family.models.items():
            parts[f"{family.key} / panel / {key}"] = model.panel.grade
        for port in family.deployment_ports:
            parts[f"{family.key} / deployment port / {port.name}"] = port.naming.grade
    return parts


class TestPinnedIdentityAndGrades:
    def test_every_part_number_is_the_model_it_should_be(self) -> None:
        for (vendor, sku), key in EXPECTED_PART_NUMBERS.items():
            hit = REGISTRY.resolve(vendor, sku)
            assert hit is not None and hit[1].model == key, (sku, key)
            assert hit[1].skus[0] == sku, (sku, hit[1].skus)

    def test_every_shipped_model_is_in_the_table(self) -> None:
        shipped = {
            (family.vendor, model.skus[0]): model.model
            for family, model in _every_model()
        }
        assert shipped == EXPECTED_PART_NUMBERS

    def test_the_grades_are_the_ones_we_expect(self) -> None:
        parts = _graded_parts()
        assert set(parts.values()) <= {"vendor-doc", "inferred"}
        assert {name for name, grade in parts.items() if grade == "inferred"} == (
            KNOWN_INFERRED_PARTS
        )


class TestAruba2930MPowerAndModules:
    FAMILY = REGISTRY.families["aruba_aoss/2930M"]

    def test_poe_models(self) -> None:
        """Every fixed port of a PoE chassis is powered and none of a
        non-PoE one is.  A JL322A that lost its flag would raise a
        "lands on a port without PoE" warning for every PoE source port
        moved onto it."""
        for model in self.FAMILY.models.values():
            assert {g.poe for g in model.ports} == {"PoE" in model.display_name}, (
                model.display_name
            )

    @pytest.mark.parametrize(
        ("sku", "count", "speed", "cage"),
        [
            ("JL083A", 4, "10gig", "sfp+"),
            ("JL078A", 1, "40gig", "qsfp+"),
            ("JL081A", 4, "10gig", "rj45"),
        ],
    )
    def test_what_each_module_contributes(
        self, sku: str, count: int, speed: str, cage: str,
    ) -> None:
        ports = [
            p for p in _compile(
                "aruba_aoss", "stacked", {"model": "JL322A", "modules": {"A": sku}},
            ).ports
            if p.module == sku
        ]
        assert len(ports) == count
        assert {(p.role, p.speed, p.cage) for p in ports} == {("uplink", speed, cage)}

    def test_the_smart_rate_modules_power_is_said_to_be_unmodelled(self) -> None:
        """The JL081A supplies PoE+ in a PoE chassis and none in a
        JL319A or JL321A.  A port has one ``poe`` flag and the module
        one definition, so the ports are listed without PoE -- and the
        inventory has to say that the flag is not to be relied on."""
        inventory = _compile(
            "aruba_aoss", "stacked", {"model": "JL322A", "modules": {"A": "JL081A"}},
        )
        uplinks = [p for p in inventory.ports if p.role == "uplink"]
        assert {p.poe for p in uplinks} == {False}
        assert {p.notes for p in uplinks} == {"HPE Smart Rate; PoE+ depends on the chassis"}
        assert any(c.startswith("JL081A: its ports supply PoE+") for c in inventory.caveats)
        other = _compile(
            "aruba_aoss", "stacked", {"model": "JL322A", "modules": {"A": "JL083A"}},
        )
        assert not any(c.startswith("JL081A") for c in other.caveats)

    @pytest.mark.parametrize(
        "sku", ["JL319A", "JL320A", "JL321A", "JL322A", "JL323A", "R0M67A"],
    )
    def test_positions_read_from_photographs_are_said_to_be(self, sku: str) -> None:
        """Where the dual-personality and Smart Rate ports sit within
        the numbering is not in an HPE document; each model that
        depends on it says so, the captured one included -- a capture
        proves the names, not the cage behind each."""
        inventory = _compile("aruba_aoss", "standalone", {"model": sku})
        assert any("read from product photographs" in c for c in inventory.caveats), sku

    @pytest.mark.parametrize("sku", ["JL324A", "R0M68A"])
    def test_a_uniform_panel_has_no_position_to_doubt(self, sku: str) -> None:
        inventory = _compile("aruba_aoss", "standalone", {"model": sku})
        assert not any("read from product photographs" in c for c in inventory.caveats)


class TestCiscoC9300:
    """A Catalyst 9300 name always carries the switch number, a panel of
    two speeds is two interface types numbered straight through, and a
    stack has one management interface."""

    FAMILY = REGISTRY.families["cisco_iosxe/C9300"]
    HIGHER_SCALE = REGISTRY.families["cisco_iosxe/C9300-higher-scale"]

    def test_the_models(self) -> None:
        assert sorted(self.FAMILY.models) == sorted([
            "C9300-24T", "C9300-48T", "C9300-24P", "C9300-48P",
            "C9300-24U", "C9300-48U", "C9300-24H", "C9300-48H",
            "C9300-24S", "C9300-48S", "C9300-24UX", "C9300-48UXM",
            "C9300-48UN",
            "C9300X-12Y", "C9300X-24Y", "C9300X-24HX", "C9300X-48HX", "C9300X-48TX",
        ])
        assert sorted(self.HIGHER_SCALE.models) == [
            "C9300-24UB", "C9300-24UXB", "C9300-48UB",
        ]

    def test_every_model_has_bay_1_taking_its_own_series_modules(self) -> None:
        """A C9300 takes the five C9300 modules; a C9300X the C9300X
        modules only (the hardware guide: "C9300X network modules are
        supported only on C9300X switches"), and the C9300X-NM-4C only
        on a C9300X-24Y, -48HX or -48TX (the data sheet)."""
        modules = ["C9300-NM-4G", "C9300-NM-4M", "C9300-NM-8X", "C9300-NM-2Q", "C9300-NM-2Y"]
        x_modules = ["C9300X-NM-8M", "C9300X-NM-8Y", "C9300X-NM-2C", "C9300X-NM-4C"]
        assert list(self.FAMILY.modules) == modules + x_modules
        assert list(self.HIGHER_SCALE.modules) == modules
        for family in (self.FAMILY, self.HIGHER_SCALE):
            for model in family.models.values():
                assert list(model.bays) == ["1"], model.model
                if not model.model.startswith("C9300X-"):
                    expected = modules
                elif model.model in {"C9300X-24Y", "C9300X-48HX", "C9300X-48TX"}:
                    expected = x_modules
                else:
                    expected = x_modules[:3]
                assert model.bays["1"].accepts == expected, model.model

    def test_stack_is_the_only_mode_and_the_default(self) -> None:
        for family in (self.FAMILY, self.HIGHER_SCALE):
            assert list(family.modes) == ["stack"]
            inventory = _compile("cisco_iosxe", None, {"model": next(iter(family.models))})
            assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)

    def test_a_lone_switch_can_be_switch_3(self) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": "C9300-24T", "id": 3})
        assert inventory.names(role="access") == _run(1, 24, "GigabitEthernet3/0/")
        assert inventory.names(role="mgmt") == ["GigabitEthernet0/0"]

    def test_a_stack_holds_eight_members_and_mixes_models(self) -> None:
        eight = [{"model": "C9300-48P", "modules": {"1": "C9300-NM-8X"}}] * 4 + [
            {"model": "C9300-24UX"}
        ] * 4
        inventory = _compile("cisco_iosxe", "stack", *eight)
        assert inventory.member_count == 8
        assert inventory.names(member_rank=0)[-1] == "TenGigabitEthernet1/1/8"
        assert inventory.names(member_rank=7) == _run(1, 24, "TenGigabitEthernet8/0/")
        with pytest.raises(Exception, match="at most 8 members"):
            _compile("cisco_iosxe", "stack", *eight, {"model": "C9300-24T"})

    def test_one_management_port_for_the_whole_stack_after_every_member(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "C9300-48P"}, {"model": "C9300-48P"},
            {"model": "C9300-48P"},
        )
        assert inventory.names(role="mgmt") == ["GigabitEthernet0/0"]
        last = inventory.ports[-1]
        assert (last.name, last.member_rank, last.member_id) == ("GigabitEthernet0/0", None, None)

    def test_a_higher_scale_model_stacks_only_with_its_own(self) -> None:
        """Data sheet: higher-scale SKUs "need to be stacked with other
        higher-scale models"."""
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": "C9300-48UB"}, {"model": "C9300-48P"})
        both = _compile("cisco_iosxe", "stack", {"model": "C9300-48UB"}, {"model": "C9300-24UXB"})
        assert both.names(member_rank=1)[0] == "TenGigabitEthernet2/0/1"

    def test_a_c9300x_stacks_with_a_c9300(self) -> None:
        """Data sheet: a C9300X "Stacks with C9300 SKUs at StackWise-480
        speeds"."""
        inventory = _compile(
            "cisco_iosxe", "stack",
            {"model": "C9300X-48HX", "modules": {"1": "C9300X-NM-2C"}},
            {"model": "C9300-48P", "modules": {"1": "C9300-NM-8X"}},
        )
        assert inventory.names(member_rank=0) == [
            *_run(1, 48, "TenGigabitEthernet1/0/"), "HundredGigE1/1/1", "HundredGigE1/1/2",
        ]
        assert inventory.names(member_rank=1)[-1] == "TenGigabitEthernet2/1/8"
        assert inventory.names(role="mgmt") == ["GigabitEthernet0/0"]

    @pytest.mark.parametrize("other", ["C9300-48UB", "C9300L-24P-4G"])
    def test_a_c9300x_stacks_with_neither_a_higher_scale_model_nor_a_c9300l(
        self, other: str,
    ) -> None:
        """Data sheet: a C9300X does not stack with a higher-scale
        model, and a C9300L stacks only with a C9300L or C9300LM."""
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": "C9300X-24Y"}, {"model": other})

    @pytest.mark.parametrize(
        ("model", "module"),
        [
            ("C9300X-48HX", "C9300-NM-8X"), ("C9300-48P", "C9300X-NM-8Y"),
            ("C9300X-12Y", "C9300X-NM-4C"), ("C9300X-24HX", "C9300X-NM-4C"),
        ],
    )
    def test_a_bay_refuses_a_module_of_the_other_series(self, model: str, module: str) -> None:
        with pytest.raises(Exception, match="does not take"):
            _compile("cisco_iosxe", "stack", {"model": model, "modules": {"1": module}})

    def test_the_nm_4c_is_where_the_data_sheet_says_and_the_guide_is_said(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "C9300X-48TX", "modules": {"1": "C9300X-NM-4C"}},
        )
        uplinks = [p for p in inventory.ports if p.role == "uplink"]
        assert [p.name for p in uplinks] == _run(1, 4, "HundredGigE1/1/")
        assert {(p.speed, p.cage) for p in uplinks} == {("100gig", "qsfp28")}
        assert any("supported only on the C9300X-24Y" in c for c in inventory.caveats)

    @pytest.mark.parametrize("pid", ["C9300X-12Y", "C9300X-24Y", "C9300X-24HX", "C9300X-48HX", "C9300X-48TX"])
    def test_a_c9300x_panel_is_inferred_and_says_why(self, pid: str) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        assert any(
            c.startswith(f"{pid}: no Cisco document read names") and "is inferred" in c
            for c in inventory.caveats
        ), pid

    def test_what_is_not_modelled_of_the_c9300x_is_said(self) -> None:
        assert REGISTRY.resolve("cisco_iosxe", "C9300X-48HXN") is None
        text = (FAMILIES_DIR / "cisco_iosxe_c9300.yaml").read_text(encoding="utf-8")
        assert "The C9300X-48HXN." in text
        caveat = self.FAMILY.modes["stack"].caveat
        assert "Whether a C9300X config does the same is not established" in caveat
        assert "license is not checked here" in caveat

    def test_the_48uxm_is_two_types_numbered_straight_through(self) -> None:
        ports = {p.name: p for p in _compile("cisco_iosxe", "stack", {"model": "C9300-48UXM"}).ports}
        assert ports["TwoGigabitEthernet1/0/36"].speed == "2.5gig"
        assert ports["TenGigabitEthernet1/0/37"].speed == "10gig"
        assert "TwoGigabitEthernet1/0/37" not in ports
        assert "TenGigabitEthernet1/0/1" not in ports
        assert not any(n.startswith("GigabitEthernet1/") for n in ports)

    def test_a_module_is_module_1_of_its_switch_and_its_ports_are_uplinks(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "C9300-24P"},
            {"model": "C9300-24P", "modules": {"1": "C9300-NM-2Y"}},
        )
        uplinks = [p for p in inventory.ports if p.role == "uplink"]
        assert [p.name for p in uplinks] == ["TwentyFiveGigE2/1/1", "TwentyFiveGigE2/1/2"]
        assert {(p.module, p.speed, p.cage, p.member_rank) for p in uplinks} == {
            ("C9300-NM-2Y", "25gig", "sfp28", 1),
        }

    def test_poe_models(self) -> None:
        unpowered = {
            "C9300-24T", "C9300-48T", "C9300-24S", "C9300-48S",
            "C9300X-12Y", "C9300X-24Y", "C9300X-48TX",
        }
        for family in (self.FAMILY, self.HIGHER_SCALE):
            for model in family.models.values():
                assert {g.poe for g in model.ports} == {model.model not in unpowered}, model.model

    def test_the_swapped_hardware_guide_rows_are_said(self) -> None:
        """The hardware guide's Product Overview table gives the 48UN
        and the 48UXM each other's ports; the inventory says which
        source it follows."""
        for pid in ("C9300-48UN", "C9300-48UXM"):
            inventory = _compile("cisco_iosxe", "stack", {"model": pid})
            assert any("Product Overview table" in c for c in inventory.caveats), pid

    def test_a_model_nobody_has_seen_a_config_of_says_so(self) -> None:
        unseen = {
            "C9300-24S", "C9300-48S", "C9300-24UB", "C9300-48UB", "C9300-24UXB",
            "C9300X-12Y", "C9300X-24Y", "C9300X-24HX", "C9300X-48HX", "C9300X-48TX",
        }
        for family in (self.FAMILY, self.HIGHER_SCALE):
            for model in family.models.values():
                said = "no configuration of a" in (model.caveat or "")
                assert said == (model.model in unseen), model.model

    def test_unfitted_modules_names_are_said_not_to_be_ports(self) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": "C9300-48P", "modules": {"1": "C9300-NM-8X"}})
        assert "FortyGigabitEthernet1/1/1" not in inventory.names()
        assert any("fitted or not" in c for c in inventory.caveats)


class TestCiscoC9200:
    """A Catalyst 9200 is named as a C9300 is; Cisco stacks it with
    neither a C9200L nor the PB models, and a C9200L's fixed uplinks
    are module 1 of the switch."""

    FAMILY = REGISTRY.families["cisco_iosxe/C9200"]
    PB = REGISTRY.families["cisco_iosxe/C9200-PB"]
    FIXED = REGISTRY.families["cisco_iosxe/C9200L"]

    def test_the_models(self) -> None:
        assert sorted(self.FAMILY.models) == sorted([
            "C9200-24T", "C9200-48T", "C9200-24P", "C9200-48P", "C9200-48PL",
            "C9200-24PXG", "C9200-48PXG",
        ])
        assert sorted(self.PB.models) == ["C9200-24PB", "C9200-48PB"]
        assert sorted(self.FIXED.models) == sorted([
            "C9200L-24T-4G", "C9200L-48T-4G", "C9200L-24P-4G", "C9200L-48P-4G",
            "C9200L-48PL-4G", "C9200L-24T-4X", "C9200L-48T-4X", "C9200L-24P-4X",
            "C9200L-48P-4X", "C9200L-48PL-4X", "C9200L-24PXG-4X", "C9200L-48PXG-4X",
            "C9200L-24PXG-2Y", "C9200L-48PXG-2Y",
        ])

    def test_the_bay_takes_what_the_data_sheet_says(self) -> None:
        """Data sheet, Table 3: the NM-2Y only on a PXG, the NM-4G on
        anything but; the NM-2Q is not modelled, its ports being named
        by no Catalyst 9200 document."""
        for family in (self.FAMILY, self.PB):
            assert "C9200-NM-2Q" not in family.modules
            for model in family.models.values():
                expected = (
                    ["C9200-NM-4X", "C9200-NM-2Y"] if "PXG" in model.model
                    else ["C9200-NM-4G", "C9200-NM-4X"]
                )
                assert list(model.bays) == ["1"], model.model
                assert model.bays["1"].accepts == expected, model.model
        assert not self.FIXED.modules
        assert not any(model.bays for model in self.FIXED.models.values())

    def test_stack_is_the_only_mode_and_the_default(self) -> None:
        for family in (self.FAMILY, self.PB, self.FIXED):
            assert list(family.modes) == ["stack"]
            assert family.modes["stack"].member_ids == (1, 8)
            inventory = _compile("cisco_iosxe", None, {"model": next(iter(family.models))})
            assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)

    @pytest.mark.parametrize(("one", "other"), [
        ("C9200-24PB", "C9200-24P"),
        ("C9200L-24P-4G", "C9200-24P"),
        ("C9200L-24P-4G", "C9200-48PB"),
        ("C9200L-24P-4X", "C9300-24P"),
    ])
    def test_the_stacks_cisco_does_not_build_are_refused(self, one: str, other: str) -> None:
        """Stacking and High Availability Configuration Guide (Catalyst
        9200): "Do not stack Cisco Catalyst 9200L Series Switches with
        Cisco Catalyst 9200 Series Switches"; the PB models "can only
        be stacked with each other"."""
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": one}, {"model": other})

    def test_the_pb_models_stack_with_each_other(self) -> None:
        both = _compile("cisco_iosxe", "stack", {"model": "C9200-24PB"}, {"model": "C9200-48PB"})
        assert both.names(member_rank=1)[0] == "GigabitEthernet2/0/1"

    def test_a_fixed_uplink_is_module_1_and_an_uplink(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "C9200L-24P-4G"}, {"model": "C9200L-48PXG-2Y", "id": 3},
        )
        uplinks = [(p.name, p.slot, p.module, p.speed, p.cage) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            *((f"GigabitEthernet1/1/{n}", "1", "", "gig", "sfp") for n in range(1, 5)),
            ("TwentyFiveGigE3/1/1", "1", "", "25gig", "sfp28"),
            ("TwentyFiveGigE3/1/2", "1", "", "25gig", "sfp28"),
        ]
        assert inventory.names(role="mgmt") == ["GigabitEthernet0/0"]

    @pytest.mark.parametrize(("pid", "last_gig", "first_ten"), [
        ("C9200-24PXG", 16, 17), ("C9200-48PXG", 40, 41),
        ("C9200L-24PXG-4X", 16, 17), ("C9200L-24PXG-2Y", 16, 17),
        ("C9200L-48PXG-2Y", 40, 41), ("C9200L-48PXG-4X", 36, 37),
    ])
    def test_a_pxg_panel_is_two_types_numbered_straight_through(
        self, pid: str, last_gig: int, first_ten: int,
    ) -> None:
        ports = {p.name: p for p in _compile("cisco_iosxe", "stack", {"model": pid}).ports}
        assert ports[f"GigabitEthernet1/0/{last_gig}"].speed == "gig"
        assert ports[f"TenGigabitEthernet1/0/{first_ten}"].speed == "10gig"
        assert ports[f"TenGigabitEthernet1/0/{first_ten}"].notes == "Multigigabit"
        assert f"GigabitEthernet1/0/{first_ten}" not in ports
        assert f"TenGigabitEthernet1/0/{last_gig}" not in ports

    def test_the_inferred_multigigabit_range_is_said(self) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": "C9200L-48PXG-4X"})
        assert any("37-48 is inferred" in c for c in inventory.caveats)
        assert {p.evidence for p in inventory.ports if p.member_rank is not None} == {"inferred"}
        other = _compile("cisco_iosxe", "stack", {"model": "C9200L-48PXG-2Y"})
        assert not any("inferred" in c for c in other.caveats)

    def test_poe_models(self) -> None:
        for family in (self.FAMILY, self.PB, self.FIXED):
            for model in family.models.values():
                panel = [g for g in model.ports if g.role == "access"]
                powered = "-24T" not in model.model and "-48T" not in model.model
                assert {g.poe for g in panel} == {powered}, model.model
                assert not any(g.poe for g in model.ports if g.role == "uplink"), model.model

    def test_no_configuration_was_seen_and_that_is_said(self) -> None:
        for family in (self.FAMILY, self.PB, self.FIXED):
            assert "No configuration of a Catalyst 9200" in family.modes["stack"].caveat, family.key


class TestCiscoC3850:
    """A Catalyst 3850 is named as a C9300 is, in a stack of up to nine;
    two of its parts are inferred and say so, and what no document read
    names is not modelled."""

    FAMILY = REGISTRY.families["cisco_iosxe/C3850"]

    def test_the_models(self) -> None:
        assert sorted(self.FAMILY.models) == sorted(_C3850_PANELS)
        assert "WS-C3850-48XS" not in self.FAMILY.models

    def test_the_bay_takes_what_the_data_sheet_says(self) -> None:
        """Data sheet, Table 2, less the C3850-NM-2-40G, whose ports no
        Catalyst 3850 document read names."""
        assert sorted(self.FAMILY.modules) == sorted([
            "C3850-NM-4-1G", "C3850-NM-2-10G", "C3850-NM-4-10G", "C3850-NM-8-10G",
        ])
        for key, model in self.FAMILY.models.items():
            assert list(model.bays) == ["1"], key
            assert model.bays["1"].accepts == [
                fitted[0][1] for fitted in _C3850_TAKES[key] if fitted
            ], key

    def test_a_stack_of_nine(self) -> None:
        assert list(self.FAMILY.modes) == ["stack"]
        assert self.FAMILY.modes["stack"].member_ids == (1, 9)
        inventory = _compile("cisco_iosxe", None, {"model": "WS-C3850-24P", "id": 9})
        assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)
        assert inventory.names()[0] == "GigabitEthernet9/0/1"
        with pytest.raises(Exception, match="outside 1-9"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C3850-24P", "id": 10})

    def test_what_is_not_checked_is_said(self) -> None:
        caveat = self.FAMILY.modes["stack"].caveat
        assert "maximum of 8 switches" in caveat and "not checked here" in caveat
        assert "No configuration of a Catalyst 3850 was seen" in caveat

    @pytest.mark.parametrize("other", ["C9300-24P", "C9200-24P", "C9200L-24P-4G"])
    def test_a_3850_stacks_with_no_catalyst_9000(self, other: str) -> None:
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C3850-24P"}, {"model": other})

    def test_the_nm_2_10g_is_two_types_and_inferred(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "WS-C3850-48P", "modules": {"1": "C3850-NM-2-10G"}},
        )
        uplinks = [(p.name, p.speed, p.cage, p.evidence) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            ("GigabitEthernet1/1/1", "gig", "sfp", "inferred"),
            ("GigabitEthernet1/1/2", "gig", "sfp", "inferred"),
            ("TenGigabitEthernet1/1/3", "10gig", "sfp+", "inferred"),
            ("TenGigabitEthernet1/1/4", "10gig", "sfp+", "inferred"),
        ]
        assert any("is inferred" in c and "C3850-NM-2-10G" in c for c in inventory.caveats)
        assert {p.evidence for p in inventory.ports if p.role == "access"} == {"vendor-doc"}

    def test_the_12x48u_panel_is_inferred_and_says_so(self) -> None:
        ports = {p.name: p for p in _compile("cisco_iosxe", "stack", {"model": "WS-C3850-12X48U"}).ports}
        assert ports["GigabitEthernet1/0/36"].speed == "gig"
        assert ports["TenGigabitEthernet1/0/37"].speed == "10gig"
        assert ports["TenGigabitEthernet1/0/37"].notes == "Multigigabit"
        assert {p.evidence for p in ports.values() if p.member_rank is not None} == {"inferred"}
        other = _compile("cisco_iosxe", "stack", {"model": "WS-C3850-24XU"})
        assert {p.evidence for p in other.ports} == {"vendor-doc"}
        assert not any("inferred" in c for c in other.caveats)

    def test_poe_models(self) -> None:
        for key, model in self.FAMILY.models.items():
            powered = key.endswith(("P", "F", "U"))
            assert {g.poe for g in model.ports} == {powered}, key
        for module in self.FAMILY.modules.values():
            assert not any(g.poe for g in module.ports)


#: The 3650 models the family leaves out, each for a reason its YAML
#: gives.
_C3650_NOT_MODELLED = (
    "WS-C3650-8X24PD", "WS-C3650-8X24UQ", "WS-C3650-12X48FD", "WS-C3650-12X48UZ",
)
_C3650_TWO_AND_TWO_MODELS = (
    "WS-C3650-24TD", "WS-C3650-48TD", "WS-C3650-24PD",
    "WS-C3650-48PD", "WS-C3650-48FD", "WS-C3650-24PDM",
)


class TestCiscoC3650:
    """A Catalyst 3650 has fixed uplinks, module 1 of the switch, in a
    stack of up to nine; what is inferred says so, and a model whose
    ports no document read places is not modelled."""

    FAMILY = REGISTRY.families["cisco_iosxe/C3650"]

    def test_the_models(self) -> None:
        assert sorted(self.FAMILY.models) == sorted(_C3650)
        text = (FAMILIES_DIR / "cisco_iosxe_c3650.yaml").read_text(encoding="utf-8")
        for left_out in _C3650_NOT_MODELLED:
            assert left_out not in self.FAMILY.models
            assert left_out in text, left_out

    def test_no_bay_and_no_module(self) -> None:
        assert not self.FAMILY.modules
        assert not any(model.bays for model in self.FAMILY.models.values())

    def test_a_stack_of_nine(self) -> None:
        assert list(self.FAMILY.modes) == ["stack"]
        assert self.FAMILY.modes["stack"].member_ids == (1, 9)
        inventory = _compile("cisco_iosxe", None, {"model": "WS-C3650-48PS", "id": 9})
        assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)
        assert inventory.names()[0] == "GigabitEthernet9/0/1"
        with pytest.raises(Exception, match="outside 1-9"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C3650-48PS", "id": 10})

    @pytest.mark.parametrize("other", ["WS-C3850-48P", "C9300-24P", "C9200L-24P-4G"])
    def test_a_3650_stacks_with_neither_a_3850_nor_a_catalyst_9000(self, other: str) -> None:
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C3650-24PS"}, {"model": other})

    def test_a_fixed_uplink_is_module_1_and_an_uplink(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "WS-C3650-24PS"}, {"model": "WS-C3650-48PQ", "id": 2},
        )
        uplinks = [(p.name, p.slot, p.module, p.speed, p.cage) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            *((f"GigabitEthernet1/1/{n}", "1", "", "gig", "sfp") for n in range(1, 5)),
            *((f"TenGigabitEthernet2/1/{n}", "1", "", "10gig", "sfp+") for n in range(1, 5)),
        ]
        assert inventory.names(role="mgmt") == ["GigabitEthernet0/0"]
        assert {p.evidence for p in inventory.ports} == {"vendor-doc"}
        assert not any("inferred" in c for c in inventory.caveats)

    @pytest.mark.parametrize("pid", _C3650_TWO_AND_TWO_MODELS)
    def test_two_and_two_uplinks_are_inferred_and_say_so(self, pid: str) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        uplinks = [(p.name, p.speed, p.cage) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            ("GigabitEthernet1/1/1", "gig", "sfp"),
            ("GigabitEthernet1/1/2", "gig", "sfp"),
            ("TenGigabitEthernet1/1/3", "10gig", "sfp+"),
            ("TenGigabitEthernet1/1/4", "10gig", "sfp+"),
        ]
        assert {p.evidence for p in inventory.ports if p.member_rank is not None} == {"inferred"}
        assert any(c.startswith(f"{pid}: ") and "is inferred" in c for c in inventory.caveats)

    @pytest.mark.parametrize("pid", ["WS-C3650-12X48UQ", "WS-C3650-12X48UR"])
    def test_the_multigigabit_range_is_inferred_and_said(self, pid: str) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        ports = {p.name: p for p in inventory.ports}
        assert ports["GigabitEthernet1/0/36"].speed == "gig"
        assert ports["TenGigabitEthernet1/0/37"].speed == "10gig"
        assert ports["TenGigabitEthernet1/0/37"].notes == "Multigigabit"
        assert "GigabitEthernet1/0/37" not in ports
        assert {p.evidence for p in ports.values() if p.member_rank is not None} == {"inferred"}
        assert any("37-48 is inferred" in c for c in inventory.caveats)

    def test_what_is_not_checked_is_said(self) -> None:
        caveat = self.FAMILY.modes["stack"].caveat
        assert "LAN Base" in caveat and "not checked here" in caveat
        assert "No configuration of a Catalyst 3650 was seen" in caveat

    def test_poe_models(self) -> None:
        for key, model in self.FAMILY.models.items():
            powered = re.search(r"\d[PFU][SDQR]M?$", key) is not None
            assert {g.poe for g in model.ports if g.role == "access"} == {powered}, key
            assert not any(g.poe for g in model.ports if g.role == "uplink"), key


_C2960X_FAMILIES = (
    ("cisco_iosxe/C2960X", "stack"),
    ("cisco_iosxe/C2960X-LL", "standalone"),
    ("cisco_iosxe/C2960XR", "stack"),
)
_C2960X_INFERRED = tuple(pid for pid in (*_C2960X, *_C2960XR) if "D-" in pid)


class TestCiscoC2960X:
    """A Catalyst 2960-X or 2960-XR has fixed uplinks, module 0 of the
    switch, and one management port, FastEthernet0.  A LAN Base 2960-X
    and a 2960-XR stack eight each and not together, a LAN Lite switch
    does not stack, what is inferred says so, and a model whose ports
    no document read places is not modelled."""

    BASE = REGISTRY.families["cisco_iosxe/C2960X"]
    LITE = REGISTRY.families["cisco_iosxe/C2960X-LL"]
    XR = REGISTRY.families["cisco_iosxe/C2960XR"]

    def test_the_models(self) -> None:
        assert sorted(self.BASE.models) == sorted(_C2960X)
        assert sorted(self.LITE.models) == sorted(_C2960X_LL)
        assert sorted(self.XR.models) == sorted(_C2960XR)

    def test_the_24psq_is_not_modelled_and_said(self) -> None:
        text = (FAMILIES_DIR / "cisco_iosxe_c2960x.yaml").read_text(encoding="utf-8")
        assert "WS-C2960X-24PSQ-L" in text
        assert REGISTRY.resolve("cisco_iosxe", "WS-C2960X-24PSQ-L") is None

    def test_no_bay_and_no_module(self) -> None:
        for family in (self.BASE, self.LITE, self.XR):
            assert not family.modules, family.key
            assert not any(model.bays for model in family.models.values()), family.key

    @pytest.mark.parametrize("pid", ["WS-C2960X-48TS-L", "WS-C2960XR-24TD-I"])
    def test_a_stack_of_eight(self, pid: str) -> None:
        family = REGISTRY.resolve("cisco_iosxe", pid)[0]
        assert list(family.modes) == ["stack"]
        assert family.modes["stack"].member_ids == (1, 8)
        inventory = _compile("cisco_iosxe", None, {"model": pid, "id": 8})
        assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)
        assert inventory.names()[0] == "GigabitEthernet8/0/1"
        with pytest.raises(Exception, match="outside 1-8"):
            _compile("cisco_iosxe", "stack", {"model": pid, "id": 9})

    def test_a_lan_lite_switch_is_alone_and_number_1(self) -> None:
        """FAQ: the LAN Lite models do not stack."""
        assert list(self.LITE.modes) == ["standalone"]
        assert self.LITE.modes["standalone"].member_ids == (1, 1)
        inventory = _compile("cisco_iosxe", None, {"model": "WS-C2960X-24TS-LL"})
        assert (inventory.mode, inventory.mode_defaulted) == ("standalone", True)
        assert inventory.names()[0] == "GigabitEthernet1/0/1"
        with pytest.raises(Exception, match="outside 1-1"):
            _compile("cisco_iosxe", None, {"model": "WS-C2960X-24TS-LL", "id": 2})
        with pytest.raises(Exception, match="allows at most 1 members"):
            _compile(
                "cisco_iosxe", None,
                {"model": "WS-C2960X-24TS-LL"}, {"model": "WS-C2960X-48TS-LL", "id": 2},
            )
        with pytest.raises(Exception, match="has no mode 'stack'"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C2960X-24TS-LL"})

    @pytest.mark.parametrize(("first", "other"), [
        ("WS-C2960X-48TS-L", "WS-C2960XR-48TS-I"),
        ("WS-C2960XR-48TS-I", "WS-C2960X-24TS-L"),
        ("WS-C2960X-48TS-L", "WS-C2960X-48TS-LL"),
        ("WS-C2960X-48TS-L", "WS-C3650-24PS"),
        ("WS-C2960XR-48TS-I", "C9200L-24P-4G"),
    ])
    def test_the_stacks_cisco_does_not_build_are_refused(self, first: str, other: str) -> None:
        """FAQ: a 2960-X and a 2960-XR "can't be stacked together"."""
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": first}, {"model": other, "id": 2})

    def test_a_fixed_uplink_is_module_0_and_an_uplink(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack",
            {"model": "WS-C2960X-48FPD-L"}, {"model": "WS-C2960X-24TS-L", "id": 2},
        )
        uplinks = [(p.name, p.slot, p.speed, p.cage) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            ("TenGigabitEthernet1/0/1", "0", "10gig", "sfp+"),
            ("TenGigabitEthernet1/0/2", "0", "10gig", "sfp+"),
            *((f"GigabitEthernet2/0/{n}", "", "gig", "sfp") for n in range(25, 29)),
        ]
        assert inventory.names(role="mgmt") == ["FastEthernet0"]

    @pytest.mark.parametrize("pid", _C2960X_INFERRED)
    def test_what_is_inferred_says_so(self, pid: str) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        assert {p.evidence for p in inventory.ports if p.member_rank is not None} == {"inferred"}
        caveat = next(c for c in inventory.caveats if c.startswith(f"{pid}: "))
        assert "is inferred" in caveat
        assert "tengigabitethernet1/1/1 - 2" in caveat

    def test_what_is_not_inferred_says_nothing_of_it(self) -> None:
        for key, mode in _C2960X_FAMILIES:
            if key == self.LITE.key:
                continue
            for pid in REGISTRY.families[key].models:
                if pid in _C2960X_INFERRED:
                    continue
                inventory = _compile("cisco_iosxe", mode, {"model": pid})
                assert {p.evidence for p in inventory.ports} == {"vendor-doc"}, pid
                assert not any("inferred" in c for c in inventory.caveats), pid

    @pytest.mark.parametrize("pid", sorted(_C2960X_LL))
    def test_a_lan_lite_switchs_names_are_inferred(self, pid: str) -> None:
        """The 2960-X guides' interface chapters name every port with its
        switch number and say nothing of LAN Lite; the 2960-S guide names a port of a LAN
        Lite 2960-S ``gigabitethernet0/4``.  The names are kept and
        graded, not swapped for the other form, and the management
        port's own grade is untouched."""
        inventory = _compile("cisco_iosxe", None, {"model": pid})
        assert inventory.names()[0] == "GigabitEthernet1/0/1"
        assert {p.evidence for p in inventory.ports if p.member_rank is not None} == {"inferred"}
        caveat = next(c for c in inventory.caveats if c.startswith("C2960X-LL: "))
        assert "GigabitEthernet1/0/N are inferred" in caveat
        assert "gigabitethernet0/4" in caveat and "is not established" in caveat
        assert [(p.name, p.evidence) for p in inventory.ports if p.member_rank is None] == [
            ("FastEthernet0", "vendor-doc"),
        ]

    def test_the_management_port_is_fast_ethernet(self) -> None:
        for key, _mode in _C2960X_FAMILIES:
            ports = REGISTRY.families[key].deployment_ports
            assert [(p.name, p.role, p.speed, p.cage) for p in ports] == [
                ("FastEthernet0", "mgmt", "fast", "rj45"),
            ], key

    def test_what_is_not_checked_is_said(self) -> None:
        base = self.BASE.modes["stack"].caveat
        assert "the 2960-S is a family of its own" in base
        assert "No configuration of a Catalyst 2960-X was seen" in base
        assert "No configuration of a Catalyst 2960-XR was seen" in self.XR.modes["stack"].caveat
        lite = self.LITE.modes["standalone"].caveat
        assert "does not stack" in lite
        assert "No configuration of a Catalyst 2960-X LAN Lite switch was seen" in lite

    def test_poe_models(self) -> None:
        for key, _mode in _C2960X_FAMILIES:
            for pid, model in REGISTRY.families[key].models.items():
                powered = re.search(r"-\d+(?:FP|LP|P)[DS]-", pid) is not None
                assert {g.poe for g in model.ports if g.role == "access"} == {powered}, pid
                assert not any(g.poe for g in model.ports if g.role == "uplink"), pid


_C2960S_INFERRED = tuple(pid for pid in _C2960S if "D-" in pid)
#: The 2960-S part numbers of the end-of-sale announcement that are not
#: modelled: the LAN Lite models, the 2960-SF and the 48TS-J1.
_C2960S_NOT_MODELLED = (
    "WS-C2960S-48TS-S", "WS-C2960S-24TS-S", "WS-C2960S-48TS-J1",
    "WS-C2960S-F48FPS-L", "WS-C2960S-F48LPS-L", "WS-C2960S-F48TS-L", "WS-C2960S-F48TS-S",
    "WS-C2960S-F24PS-L", "WS-C2960S-F24TS-L", "WS-C2960S-F24TS-S",
)


class TestCiscoC2960S:
    """A Catalyst 2960-S LAN Base switch is named as a 2960-X's is, in a
    FlexStack stack of up to four, with one management port,
    FastEthernet0.  A D model's SFP+ uplinks are inferred and say so;
    the LAN Lite models, the 2960-SF and the 48TS-J1 are not modelled,
    and the YAML says why."""

    FAMILY = REGISTRY.families["cisco_iosxe/C2960S"]

    def test_the_models(self) -> None:
        assert sorted(self.FAMILY.models) == sorted(_C2960S)
        assert not self.FAMILY.modules
        assert not any(model.bays for model in self.FAMILY.models.values())

    @pytest.mark.parametrize("pid", _C2960S_NOT_MODELLED)
    def test_what_is_not_modelled_is_not_resolved(self, pid: str) -> None:
        assert REGISTRY.resolve("cisco_iosxe", pid) is None

    def test_what_is_not_modelled_is_said(self) -> None:
        text = (FAMILIES_DIR / "cisco_iosxe_c2960s.yaml").read_text(encoding="utf-8")
        for pid in ("WS-C2960S-48TS-S", "WS-C2960S-24TS-S", "WS-C2960S-48TS-J1", "WS-C2960S-F48FPS-L"):
            assert pid in text, pid
        assert "gigabitethernet0/4" in text

    def test_a_stack_of_four(self) -> None:
        """SCG: "A switch stack is a set of up to four Catalyst 2960-S
        switches"."""
        assert list(self.FAMILY.modes) == ["stack"]
        assert self.FAMILY.modes["stack"].member_ids == (1, 4)
        inventory = _compile("cisco_iosxe", None, {"model": "WS-C2960S-48TS-L", "id": 4})
        assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)
        assert inventory.names()[0] == "GigabitEthernet4/0/1"
        with pytest.raises(Exception, match="outside 1-4"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C2960S-48TS-L", "id": 5})

    @pytest.mark.parametrize(
        "other", ["WS-C2960X-48TS-L", "WS-C2960XR-48TS-I", "WS-C2960X-24TS-LL", "WS-C3750X-48P"],
    )
    def test_a_2960s_stacks_with_no_other_family(self, other: str) -> None:
        """Cisco stacks a 2960-S with a 2960-X LAN Base switch; that
        stack is not modelled, so it is refused, as is any other."""
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C2960S-48TS-L"}, {"model": other, "id": 2})

    def test_the_uplinks(self) -> None:
        inventory = _compile(
            "cisco_iosxe", "stack",
            {"model": "WS-C2960S-48FPD-L"}, {"model": "WS-C2960S-24TS-L", "id": 2},
        )
        uplinks = [(p.name, p.slot, p.speed, p.cage) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            ("TenGigabitEthernet1/0/1", "0", "10gig", "sfp+"),
            ("TenGigabitEthernet1/0/2", "0", "10gig", "sfp+"),
            *((f"GigabitEthernet2/0/{n}", "", "gig", "sfp") for n in range(25, 29)),
        ]
        assert inventory.names(role="mgmt") == ["FastEthernet0"]

    @pytest.mark.parametrize("pid", _C2960S_INFERRED)
    def test_what_is_inferred_says_so(self, pid: str) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        assert {p.evidence for p in inventory.ports if p.member_rank is not None} == {"inferred"}
        caveat = next(c for c in inventory.caveats if c.startswith(f"{pid}: "))
        assert "is inferred" in caveat
        assert "module slot numbers as 1 and 2" in caveat

    def test_what_is_not_inferred_says_nothing_of_it(self) -> None:
        for pid in self.FAMILY.models:
            if pid in _C2960S_INFERRED:
                continue
            inventory = _compile("cisco_iosxe", "stack", {"model": pid})
            assert {p.evidence for p in inventory.ports} == {"vendor-doc"}, pid
            assert not any("inferred" in c for c in inventory.caveats), pid

    def test_the_management_port_is_fast_ethernet(self) -> None:
        assert [(p.name, p.role, p.speed, p.cage) for p in self.FAMILY.deployment_ports] == [
            ("FastEthernet0", "mgmt", "fast", "rj45"),
        ]

    def test_what_is_not_checked_is_said(self) -> None:
        caveat = self.FAMILY.modes["stack"].caveat
        assert "the 2960-X is a family of its own" in caveat
        assert "The LAN Lite models" in caveat and "2960-SF are not modelled" in caveat
        assert "No configuration of a Catalyst 2960-S was seen" in caveat

    def test_poe_models(self) -> None:
        for pid, model in self.FAMILY.models.items():
            powered = re.search(r"-\d+(?:FP|LP|P)[DS]-", pid) is not None
            assert {g.poe for g in model.ports if g.role == "access"} == {powered}, pid
            assert not any(g.poe for g in model.ports if g.role == "uplink"), pid


_C3750X_MODULES = ["C3KX-NM-1G", "C3KX-NM-10G", "C3KX-NM-10GT", "C3KX-SM-10G"]


class TestCiscoC3750X:
    """A Catalyst 3750-X is named as a 3850 is, in a stack of up to nine,
    with one management port, FastEthernet0.  A port of its 10-Gigabit
    modules has two names, by the optic in it, and a module is described
    in one state and says which; what no document read names is
    inferred and says so."""

    FAMILY = REGISTRY.families["cisco_iosxe/C3750X"]

    def _uplinks(self, model: str, module: str) -> list[tuple]:
        inventory = _compile("cisco_iosxe", "stack", {"model": model, "modules": {"1": module}})
        return [(p.name, p.speed, p.cage, p.evidence) for p in inventory.ports if p.role == "uplink"]

    def test_the_models(self) -> None:
        assert sorted(self.FAMILY.models) == sorted(_C3750X_PANELS)
        # The 3560-X does not stack and has no switch number in its names.
        assert REGISTRY.resolve("cisco_iosxe", "WS-C3560X-48P") is None

    def test_every_bay_takes_the_four_modules(self) -> None:
        """The blank module has no ports: a switch with it fitted is
        declared with its bay empty."""
        assert sorted(self.FAMILY.modules) == sorted(_C3750X_MODULES)
        for key, model in self.FAMILY.models.items():
            assert list(model.bays) == ["1"], key
            assert model.bays["1"].accepts == _C3750X_MODULES, key

    def test_a_stack_of_nine(self) -> None:
        assert list(self.FAMILY.modes) == ["stack"]
        assert self.FAMILY.modes["stack"].member_ids == (1, 9)
        inventory = _compile("cisco_iosxe", None, {"model": "WS-C3750X-24P", "id": 9})
        assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)
        assert inventory.names()[0] == "GigabitEthernet9/0/1"
        with pytest.raises(Exception, match="outside 1-9"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C3750X-24P", "id": 10})

    @pytest.mark.parametrize("module", ["C3KX-NM-10G", "C3KX-SM-10G"])
    def test_a_10g_module_is_described_with_an_sfp_plus_and_says_so(self, module: str) -> None:
        assert self._uplinks("WS-C3750X-48P", module) == [
            ("TenGigabitEthernet1/1/1", "10gig", "sfp+", "vendor-doc"),
            ("TenGigabitEthernet1/1/2", "10gig", "sfp+", "vendor-doc"),
        ]
        caveat = self.FAMILY.modules[module].caveat
        assert caveat.startswith(f"{module}: described with a 10-Gigabit SFP+ module")
        assert "is a GigabitEthernet port" in caveat and "declare the bay empty" in caveat
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "WS-C3750X-48P", "modules": {"1": module}},
        )
        assert caveat in inventory.caveats
        assert not any("inferred" in c for c in inventory.caveats)

    def test_what_is_inferred_says_so(self) -> None:
        assert self._uplinks("WS-C3750X-24T", "C3KX-NM-1G") == [
            (f"GigabitEthernet1/1/{n}", "gig", "sfp", "inferred") for n in range(1, 5)
        ]
        assert self._uplinks("WS-C3750X-24T", "C3KX-NM-10GT") == [
            (f"TenGigabitEthernet1/1/{n}", "10gig", "rj45", "inferred") for n in (1, 2)
        ]
        for module in ("C3KX-NM-1G", "C3KX-NM-10GT"):
            inventory = _compile(
                "cisco_iosxe", "stack", {"model": "WS-C3750X-24T", "modules": {"1": module}},
            )
            assert any(c.startswith(f"{module}: ") and "is inferred" in c for c in inventory.caveats)
        assert "1 Gb/s is not established" in self.FAMILY.modules["C3KX-NM-10GT"].inventory.caveat
        for pid in ("WS-C3750X-12S", "WS-C3750X-24S"):
            inventory = _compile("cisco_iosxe", "stack", {"model": pid})
            assert {p.evidence for p in inventory.ports if p.role == "access"} == {"inferred"}
            assert {p.cage for p in inventory.ports if p.role == "access"} == {"sfp"}
            assert any(c.startswith(f"{pid}: ") and "is inferred" in c for c in inventory.caveats)

    def test_what_is_not_inferred_says_nothing_of_it(self) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": "WS-C3750X-48PF"})
        assert {p.evidence for p in inventory.ports} == {"vendor-doc"}
        assert not any("inferred" in c for c in inventory.caveats)

    def test_the_management_port_is_fast_ethernet(self) -> None:
        assert [(p.name, p.role, p.speed, p.cage) for p in self.FAMILY.deployment_ports] == [
            ("FastEthernet0", "mgmt", "fast", "rj45"),
        ]
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "WS-C3750X-24P"}, {"model": "WS-C3750X-48U"},
        )
        assert [p.name for p in inventory.ports if p.role == "mgmt"] == ["FastEthernet0"]

    @pytest.mark.parametrize("other", ["WS-C3850-24P", "WS-C3650-24PS", "C9300-24P", "WS-C2960X-24PS-L"])
    def test_a_3750x_stacks_with_no_other_family(self, other: str) -> None:
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": "WS-C3750X-24P"}, {"model": other})

    def test_a_3850_module_is_refused(self) -> None:
        with pytest.raises(Exception, match="does not take 'C3850-NM-4-10G'"):
            _compile(
                "cisco_iosxe", "stack",
                {"model": "WS-C3750X-48P", "modules": {"1": "C3850-NM-4-10G"}},
            )

    def test_what_is_not_checked_is_said(self) -> None:
        caveat = self.FAMILY.modes["stack"].caveat
        assert "is not checked here" in caveat and "3750-E" in caveat
        assert "C3KX-NM_BLNK" in caveat
        assert "No configuration of a Catalyst 3750-X was seen" in caveat

    def test_poe_models(self) -> None:
        for key, model in self.FAMILY.models.items():
            powered = re.search(r"-\d+(?:PF|P|U)$", key) is not None
            assert {g.poe for g in model.ports} == {powered}, key
        for module in self.FAMILY.modules.values():
            assert not any(g.poe for g in module.ports)


_C9300L_INFERRED = (
    "C9300L-24UXG-4X", "C9300L-24UXG-2Q", "C9300L-48UXG-4X", "C9300L-48UXG-2Q",
    "C9300LM-48T-4Y", "C9300LM-24U-4Y", "C9300LM-48U-4Y", "C9300LM-48UX-4Y",
)


class TestCiscoC9300L:
    """A Catalyst 9300L or 9300LM has fixed uplinks, module 1 of the
    switch, in a StackWise-320 stack of up to eight that Cisco builds of
    the two series and of nothing else; what is inferred says so."""

    FAMILY = REGISTRY.families["cisco_iosxe/C9300L"]

    def test_the_models(self) -> None:
        assert sorted(self.FAMILY.models) == sorted(_C9300L)

    def test_no_bay_and_no_module(self) -> None:
        assert not self.FAMILY.modules
        assert not any(model.bays for model in self.FAMILY.models.values())

    def test_a_stack_of_eight(self) -> None:
        assert list(self.FAMILY.modes) == ["stack"]
        assert self.FAMILY.modes["stack"].member_ids == (1, 8)
        inventory = _compile("cisco_iosxe", None, {"model": "C9300L-48P-4X", "id": 8})
        assert (inventory.mode, inventory.mode_defaulted) == ("stack", True)
        assert inventory.names()[0] == "GigabitEthernet8/0/1"
        with pytest.raises(Exception, match="outside 1-8"):
            _compile("cisco_iosxe", "stack", {"model": "C9300L-48P-4X", "id": 9})

    def test_a_c9300l_and_a_c9300lm_stack_together(self) -> None:
        """Data sheet: each "Stacks with other Catalyst 9300L and 9300LM
        models with same license level"."""
        inventory = _compile(
            "cisco_iosxe", "stack", {"model": "C9300L-24P-4G"}, {"model": "C9300LM-48UX-4Y", "id": 2},
        )
        uplinks = [(p.name, p.slot, p.speed, p.cage) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            *((f"GigabitEthernet1/1/{n}", "1", "gig", "sfp") for n in range(1, 5)),
            *((f"TwentyFiveGigE2/1/{n}", "1", "25gig", "sfp28") for n in range(1, 5)),
        ]
        assert inventory.names(role="mgmt") == ["GigabitEthernet0/0"]

    @pytest.mark.parametrize("other", ["C9300-24P", "C9300-24UB", "C9200L-24P-4G", "WS-C3850-24P"])
    def test_the_stacks_cisco_does_not_build_are_refused(self, other: str) -> None:
        """Data sheet: "You cannot stack fixed uplink models (C9300L SKUs)
        with modular uplink models (C9300 SKUs)"."""
        with pytest.raises(Exception, match="cannot share a deployment"):
            _compile("cisco_iosxe", "stack", {"model": "C9300L-24P-4G"}, {"model": other})

    @pytest.mark.parametrize("pid", ["C9300L-24UXG-2Q", "C9300L-48UXG-2Q"])
    def test_a_2q_is_two_forty_gig_uplinks(self, pid: str) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        uplinks = [(p.name, p.speed, p.cage) for p in inventory.ports if p.role == "uplink"]
        assert uplinks == [
            ("FortyGigabitEthernet1/1/1", "40gig", "qsfp+"),
            ("FortyGigabitEthernet1/1/2", "40gig", "qsfp+"),
        ]

    @pytest.mark.parametrize("pid", _C9300L_INFERRED)
    def test_what_is_inferred_says_so(self, pid: str) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        assert {p.evidence for p in inventory.ports if p.member_rank is not None} == {"inferred"}
        assert any(c.startswith(f"{pid}: ") and "is inferred" in c for c in inventory.caveats)

    def test_what_is_not_inferred_says_nothing_of_it(self) -> None:
        for key in self.FAMILY.models:
            if key in _C9300L_INFERRED:
                continue
            inventory = _compile("cisco_iosxe", "stack", {"model": key})
            assert {p.evidence for p in inventory.ports} == {"vendor-doc"}, key
            assert not any("inferred" in c for c in inventory.caveats), key

    @pytest.mark.parametrize(("pid", "last_gig", "first_ten"), [
        ("C9300L-24UXG-4X", 16, 17), ("C9300L-48UXG-2Q", 36, 37), ("C9300LM-48UX-4Y", 40, 41),
    ])
    def test_the_multigigabit_ports_are_the_last(self, pid: str, last_gig: int, first_ten: int) -> None:
        inventory = _compile("cisco_iosxe", "stack", {"model": pid})
        ports = {p.name: p for p in inventory.ports}
        assert ports[f"GigabitEthernet1/0/{last_gig}"].speed == "gig"
        assert ports[f"TenGigabitEthernet1/0/{first_ten}"].notes == "Multigigabit"
        assert f"GigabitEthernet1/0/{first_ten}" not in ports
        if pid.startswith("C9300L-"):
            assert any("does not support Multigigabit" in c for c in inventory.caveats)

    def test_what_is_not_checked_is_said(self) -> None:
        caveat = self.FAMILY.modes["stack"].caveat
        assert "license is not checked here" in caveat
        assert "No configuration of a Catalyst 9300L or 9300LM was seen" in caveat

    def test_poe_models(self) -> None:
        for key, model in self.FAMILY.models.items():
            powered = re.search(r"-\d+T-", key) is None
            assert {g.poe for g in model.ports if g.role == "access"} == {powered}, key
            assert not any(g.poe for g in model.ports if g.role == "uplink"), key
