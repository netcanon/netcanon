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

    def test_no_evidence_ref_leans_on_a_legend_only_a_comment_holds(self) -> None:
        """A ``ref`` is served to API clients, who see neither the
        YAML comments nor the other family file.  A short tag defined
        in a header comment (and meaning a different document in each
        file) is of no use to them, and neither is "real configs"
        with nothing to find them by."""
        tags = re.compile(r"\b(IGSG|QS|ATMG|MCG|BP|DS)\b")
        for family in REGISTRY.families.values():
            grades = [mode.naming for mode in family.modes.values()]
            grades += [m.bay_naming for m in family.modes.values() if m.bay_naming]
            grades += [module.inventory for module in family.modules.values()]
            grades += [model.panel for model in family.models.values()]
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
        inventory = _compile(vendor, mode, {"model": model, "modules": dict(fitted)})
        assert inventory.names(role="access") == access
        assert inventory.names(role="uplink") == uplinks
        assert inventory.names() == access + uplinks
        assert inventory.names(role="mgmt") == []

    @pytest.mark.parametrize(("family", "model"), _every_model(), ids=_model_id)
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


def _codec_for(vendor: str):
    for name in list_public_codecs():
        if vendor_of(name) == vendor:
            return get_codec(name)
    raise AssertionError(f"no codec is filed under vendor {vendor!r}")


class TestCompiledNamesRoundTripThroughTheCodec:
    """Will this name survive the render path?  NOT evidence that the
    name is right — the data and the classifier can be wrong together."""

    @pytest.mark.parametrize(("family", "model"), _every_model(), ids=_model_id)
    def test_the_classifier_recovers_member_slot_and_port(
        self, family: FamilyDef, model: ModelDef,
    ) -> None:
        codec = _codec_for(family.vendor)
        checked = 0
        for mode_name, modules in product(family.modes, _module_choices(model)):
            if not family.supports(model, mode_name):
                continue
            inventory = _compile(
                family.vendor, mode_name,
                {"model": model.model, "modules": modules},
            )
            for port in inventory.ports:
                identity = codec.classify_port_name(port.name)
                where = (model.model, mode_name, port.name)
                if identity.kind == "unknown":
                    assert port.member_id is None and (
                        _UNCLASSIFIED_BARE_LETTER.match(port.name)
                    ), where
                    continue
                assert identity.kind == "physical", (*where, identity.kind)
                assert identity.stack == port.member_id, where
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
#: by the part number in their display name).
#:
#: Where both exist, the family is authoritative for port mapping; the
#: profile keeps feeding the older dropdown until it is retired.
PROFILE_AGREES_WITH: dict[str, dict] = {
    "aruba_aoss/2930F-24G": {"mode": "standalone", "members": [{"model": "JL253A"}]},
    "aruba_aoss/2930F-24G-PoEP": {"mode": "standalone", "members": [{"model": "JL255A"}]},
    "aruba_aoss/2930F-48G": {"mode": "standalone", "members": [{"model": "JL260A"}]},
    "aruba_aoss/2930F-48G-PoEP": {"mode": "standalone", "members": [{"model": "JL256A"}]},
}

_PART_NUMBER = re.compile(r"\(([A-Z0-9-]+)\)")


def _comparable(inventory: Inventory) -> list[tuple]:
    return [
        (p.name, p.role, p.ordinal, p.speed, p.poe) for p in inventory.ports
    ]


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
            for part in _PART_NUMBER.findall(profile.display_name):
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
EXPECTED_PART_NUMBERS: dict[str, str] = {
    # Aruba 2930F
    "JL253A": "2930F-24G-4SFPP",
    "JL254A": "2930F-48G-4SFPP",
    "JL255A": "2930F-24G-PoEP-4SFPP",
    "JL256A": "2930F-48G-PoEP-4SFPP",
    "JL258A": "2930F-8G-PoEP-2SFPP",
    "JL259A": "2930F-24G-4SFP",
    "JL260A": "2930F-48G-4SFP",
    "JL261A": "2930F-24G-PoEP-4SFP",
    "JL262A": "2930F-48G-PoEP-4SFP",
    "JL263A": "2930F-24G-PoEP-4SFPP-TAA",
    "JL264A": "2930F-48G-PoEP-4SFPP-TAA",
    "JL557A": "2930F-48G-740W-PoEP-4SFP",
    "JL558A": "2930F-48G-740W-PoEP-4SFPP",
    "JL559A": "2930F-48G-740W-PoEP-4SFPP-TAA",
    "JL692A": "2930F-8G-PoEP-2SFPP-TAA",
    "JL693A": "2930F-12G-PoEP-2G-2SFPP",
    # Aruba 2930M
    "JL319A": "2930M-24G",
    "JL320A": "2930M-24G-PoEP",
    "JL321A": "2930M-48G",
    "JL322A": "2930M-48G-PoEP",
    "JL323A": "2930M-40G-8SR-PoEP",
    "JL324A": "2930M-24SR-PoEP",
    "R0M67A": "2930M-40G-8SR-PoE-Class6",
    "R0M68A": "2930M-24SR-PoE-Class6",
}

#: Parts graded ``inferred``, as ``family key / kind / name``.  Every
#: other graded part is ``vendor-doc``.  Empty today; a part that is
#: lowered to ``inferred``, or raised out of it, changes this set in the
#: same review.
KNOWN_INFERRED_PARTS: set[str] = set()


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
    return parts


class TestPinnedIdentityAndGrades:
    def test_every_part_number_is_the_model_it_should_be(self) -> None:
        for sku, key in EXPECTED_PART_NUMBERS.items():
            hit = REGISTRY.resolve("aruba_aoss", sku)
            assert hit is not None and hit[1].model == key, (sku, key)
            assert hit[1].skus[0] == sku, (sku, hit[1].skus)

    def test_every_shipped_model_is_in_the_table(self) -> None:
        shipped = {
            model.skus[0]: model.model
            for _, model in _every_model()
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
