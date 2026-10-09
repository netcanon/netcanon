"""
API integration tests for model-to-model port mapping.

Covers:
  * GET  /api/v1/migration/model-families — the families a picker is built from
  * POST /api/v1/migration/inventory — one declared device, compiled to its ports
  * POST /api/v1/migration/plan (and the per-pane endpoints) with
    ``source_deployment`` / ``target_deployment`` or profile keys —
    positional port pairing and ``port_mapping_plan`` on the job

The pairing policy is unit-tested in ``tests/unit/migration/
test_port_mapping.py`` and the pipeline in ``test_run_plan_with_models.py``;
here the subject is the HTTP contract: what engages the feature, what
is a 422, and what a request that predates the feature still gets.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A real standalone Aruba 2930F-48G-4SFP (JL260A); names ports 1-52.
CAPTURE_2930F = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
).read_text(encoding="utf-8")

SOURCE_2930F = {"mode": "standalone", "members": [{"model": "JL260A"}]}
TARGET_2930M = {
    "mode": "stacked",
    "members": [{"model": "JL322A", "modules": {"A": "JL083A"}}],
}


def _plan_body(**extra) -> dict:
    return {
        "source": "aruba_aoss",
        "target": "aruba_aoss",
        "raw_text": CAPTURE_2930F,
        **extra,
    }


def _models_body(**extra) -> dict:
    return _plan_body(
        source_deployment=SOURCE_2930F, target_deployment=TARGET_2930M, **extra,
    )


# ---------------------------------------------------------------------------
# Model families
# ---------------------------------------------------------------------------


class TestModelFamilies:
    def test_lists_the_shipped_families(self, client: TestClient) -> None:
        resp = client.get("/api/v1/migration/model-families")
        assert resp.status_code == 200
        families = {(f["vendor"], f["family"]): f for f in resp.json()}
        assert ("aruba_aoss", "2930F") in families
        assert ("aruba_aoss", "2930M") in families

    def test_a_family_carries_what_a_picker_needs(self, client: TestClient) -> None:
        families = client.get("/api/v1/migration/model-families").json()
        family = next(f for f in families if f["family"] == "2930M")
        assert family["schema"] == 1
        assert family["default_mode"] == "stacked"
        assert family["modes"]["stacked"]["member_ids"] == [1, 10]
        assert family["modes"]["standalone"]["member_ids"] is None
        assert family["modes"]["stacked"]["label"]
        model = family["models"]["2930M-48G-PoEP"]
        assert model["skus"] == ["JL322A"]
        assert model["display_name"] == "Aruba 2930M-48G-PoE+ (JL322A)"
        assert model["bays"]["A"]["accepts"] == ["JL083A", "JL078A", "JL081A"]
        assert family["modules"]["JL083A"]["description"]

    def test_a_family_has_no_port_names(self, client: TestClient) -> None:
        """Names depend on the mode, the member ids and the fitted
        modules.  A client gets them from /inventory, never by
        expanding a family itself."""
        families = client.get("/api/v1/migration/model-families").json()
        model = next(f for f in families if f["family"] == "2930F")["models"][
            "2930F-48G-4SFP"
        ]
        assert model["ports"] == [
            {"role": "access", "count": 48, "slot": "", "speed": "gig",
             "cage": "rj45", "poe": False, "notes": ""},
            {"role": "uplink", "count": 4, "slot": "", "speed": "gig",
             "cage": "sfp", "poe": False, "notes": ""},
        ]

    def test_filter_by_vendor(self, client: TestClient) -> None:
        aruba = client.get("/api/v1/migration/model-families?vendor=aruba_aoss").json()
        assert {f["vendor"] for f in aruba} == {"aruba_aoss"}
        assert client.get(
            "/api/v1/migration/model-families?vendor=no-such-vendor"
        ).json() == []

    def test_the_shipped_families_load_under_a_relocated_definitions_dir(
        self, client: TestClient, sample_definitions_dir: Path,
    ) -> None:
        """This test app's definitions directory is a temp folder with
        no ``model_families/`` in it — the position of an operator who
        keeps their own backup definitions.  The shipped families must
        still be there."""
        assert not (sample_definitions_dir / "model_families").exists()
        resp = client.get("/api/v1/migration/model-families")
        assert resp.status_code == 200
        assert {(f["vendor"], f["family"]) for f in resp.json()} >= {
            ("aruba_aoss", "2930F"), ("aruba_aoss", "2930M"),
        }


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


class TestInventory:
    def test_compiles_a_deployment_to_real_port_names(self, client: TestClient) -> None:
        resp = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss", "deployment": TARGET_2930M,
        })
        assert resp.status_code == 200
        inventory = resp.json()
        names = [p["name"] for p in inventory["ports"]]
        assert names[0] == "1/1" and names[47] == "1/48"
        assert names[48:] == ["1/A1", "1/A2", "1/A3", "1/A4"]
        assert inventory["port_count"] == 52
        uplink = inventory["ports"][48]
        assert (uplink["role"], uplink["slot"], uplink["index"], uplink["module"]) == (
            "uplink", "A", 0, "JL083A",
        )

    def test_the_same_device_with_stacking_disabled(self, client: TestClient) -> None:
        inventory = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss",
            "deployment": {**TARGET_2930M, "mode": "standalone"},
        }).json()
        names = [p["name"] for p in inventory["ports"]]
        assert names[0] == "1" and names[48:] == ["A1", "A2", "A3", "A4"]

    def test_it_echoes_what_was_resolved(self, client: TestClient) -> None:
        """The caller typed a part number in lower case and no mode.
        The response says which model, which mode, which member id —
        and that the mode was a default."""
        inventory = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss",
            "deployment": {"members": [{"model": "jl322a"}]},
        }).json()
        assert inventory["family"] == "aruba_aoss/2930M"
        assert (inventory["mode"], inventory["mode_defaulted"]) == ("stacked", True)
        member = inventory["members"][0]
        assert (member["model"], member["member_id"]) == ("2930M-48G-PoEP", 1)
        assert member["unstated_bays"] == ["A"]
        assert any("No deployment mode was stated" in c for c in inventory["caveats"])

    def test_an_empty_mode_is_a_defaulted_one(self, client: TestClient) -> None:
        """A picker whose first option is empty posts ``""``."""
        inventory = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss",
            "deployment": {"mode": "", "members": [{"model": "JL322A"}]},
        }).json()
        assert (inventory["mode"], inventory["mode_defaulted"]) == ("stacked", True)

    def test_a_profiles_module_is_matched_in_any_case_and_may_be_none(
        self, client: TestClient,
    ) -> None:
        """Absent takes the profile's default module, ``""`` states
        that none is fitted, and a known SKU matches in any case."""
        def uplinks(**module: str) -> list[str]:
            body = {"codec": "aruba_aoss", "profile": "aruba_aoss/3810M-48G-PoEP",
                    **module}
            ports = client.post("/api/v1/migration/inventory", json=body).json()["ports"]
            return [p["name"] for p in ports if p["role"] == "uplink"]

        assert uplinks() == ["1/A1", "1/A2", "1/A3", "1/A4"]
        assert uplinks(module="jl078a") == ["1/A1"]
        assert uplinks(module="") == []

    def test_every_port_carries_its_own_evidence_grade(self, client: TestClient) -> None:
        inventory = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss", "deployment": SOURCE_2930F,
        }).json()
        assert inventory["evidence"] == "capture"
        assert {p["evidence"] for p in inventory["ports"]} == {"capture"}
        fixture, panel = inventory["evidence_refs"]
        assert fixture == (
            "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
        )
        # ...and what establishes the panel: a capture proves the names.
        assert panel.startswith("2930F Installation Guide 5200-1194d")

    def test_a_flat_target_profile_compiles_too(self, client: TestClient) -> None:
        inventory = client.post("/api/v1/migration/inventory", json={
            "codec": "cisco_iosxe_cli",
            "profile": "cisco_iosxe/C9300-24UX",
            "module": "NM-2Q",
        }).json()
        assert inventory["origin"] == "legacy-profile"
        names = [p["name"] for p in inventory["ports"]]
        assert "TenGigabitEthernet1/0/24" in names
        assert "FortyGigabitEthernet1/1/2" in names

    @pytest.mark.parametrize(
        ("body", "needle"),
        [
            ({"codec": "aruba_aoss"}, "Exactly one of"),
            ({"codec": "aruba_aoss", "deployment": TARGET_2930M,
              "profile": "aruba_aoss/2930F-48G"}, "Exactly one of"),
            ({"codec": "no-such-codec", "deployment": TARGET_2930M}, "unknown device adapter"),
            ({"codec": "aruba_aoss",
              "deployment": {"members": [{"model": "JL999Z"}]}},
             "deployment: no device model 'JL999Z'"),
            ({"codec": "aruba_aoss",
              "deployment": {"mode": "vsf", "members": [{"model": "JL322A"}]}},
             "has no mode 'vsf' (modes: stacked, standalone)"),
            ({"codec": "aruba_aoss",
              "deployment": {"members": [{"model": "JL322A", "modules": {"A": "JL079A"}}]}},
             "does not take 'JL079A'"),
            ({"codec": "aruba_aoss",
              "deployment": {"mode": "standalone",
                             "members": [{"model": "JL322A"}, {"model": "JL322A"}]}},
             "is a single device"),
            ({"codec": "aruba_aoss", "profile": "aruba_aoss/NOPE"},
             "profile: unknown target profile"),
            ({"codec": "aruba_aoss", "profile": "cisco_iosxe/C9300-24UX"},
             "is a cisco_iosxe profile"),
            # A typo must not compile as the chassis with no module.
            ({"codec": "aruba_aoss", "profile": "aruba_aoss/3810M-48G-PoEP",
              "module": "JL083"},
             "module: aruba_aoss/3810M-48G-PoEP has no module 'JL083' "
             "(modules: JL083A, JL078A)"),
            ({"codec": "aruba_aoss", "profile": "aruba_aoss/2930F-48G",
              "module": "JL083A"},
             "has no module 'JL083A' (modules: none)"),
            # A model is looked up under the CODEC's vendor.
            ({"codec": "cisco_iosxe_cli",
              "deployment": {"members": [{"model": "JL322A"}]}},
             "no device model 'JL322A' is defined for cisco_iosxe"),
        ],
    )
    def test_a_bad_declaration_is_a_422_that_says_what_is_wrong(
        self, client: TestClient, body: dict, needle: str,
    ) -> None:
        resp = client.post("/api/v1/migration/inventory", json=body)
        assert resp.status_code == 422
        assert needle in resp.json()["detail"]

    def test_an_unknown_field_in_a_deployment_is_rejected(
        self, client: TestClient,
    ) -> None:
        """A misspelt ``modules`` would otherwise compile as an empty
        bay and silently lose the operator's uplinks."""
        resp = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss",
            "deployment": {"members": [{"model": "JL322A", "module": {"A": "JL083A"}}]},
        })
        assert resp.status_code == 422

    @pytest.mark.parametrize("member_id", ["2", 2.0, True])
    def test_a_member_id_is_an_integer_and_nothing_else(
        self, client: TestClient, member_id: object,
    ) -> None:
        """``true`` must not be read as member 1."""
        resp = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss",
            "deployment": {"mode": "stacked",
                           "members": [{"model": "JL322A", "id": member_id}]},
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Plan with both devices declared
# ---------------------------------------------------------------------------


class TestPlanWithDeclaredDevices:
    def test_ports_are_paired_by_position(self, client: TestClient) -> None:
        resp = client.post("/api/v1/migration/plan", json=_models_body())
        assert resp.status_code == 200
        assert resp.headers["X-Netcanon-Job-Status"] == "completed"
        job = resp.json()
        assert job["port_renames"]["1"] == "1/1"
        assert job["port_renames"]["49"] == "1/A1"
        assert len(job["port_renames"]) == 52
        assert "untagged 1/48,1/A1,1/A2,1/A3,1/A4" in job["rendered"]

    def test_the_job_carries_the_plan_as_data(self, client: TestClient) -> None:
        plan = client.post(
            "/api/v1/migration/plan", json=_models_body(),
        ).json()["port_mapping_plan"]
        assert plan["applied"] is True
        assert len(plan["pairings"]) == 52
        first_uplink = next(p for p in plan["pairings"] if p["source"] == "49")
        assert first_uplink == {
            "source": "49", "target": "1/A1", "role": "uplink", "member_rank": 0,
            "position": 0, "used": True, "source_speed": "gig",
            "target_speed": "10gig", "slower": False, "poe_lost": False,
            "evidence": "vendor-doc",
        }
        assert plan["unplaced"] == [] and plan["off_inventory"] == []
        # The outcome is data, not something to read out of warnings.
        assert (plan["unresolved_ports"], plan["displaced"], plan["fused"]) == (
            [], [], {},
        )
        assert (plan["off_target"], plan["emptied_lags"], plan["overridden"]) == (
            [], [], [],
        )
        assert plan["source"]["members"][0]["model"] == "2930F-48G-4SFP"
        assert plan["target"]["members"][0]["modules"] == {"A": "JL083A"}
        assert plan["target"]["mode"] == "stacked"

    def test_source_ports_lists_every_hardware_port(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json=_models_body()).json()
        assert sorted(job["source_ports"], key=int) == [str(n) for n in range(1, 53)]

    def test_a_target_too_small_is_partial_and_says_which_ports(
        self, client: TestClient,
    ) -> None:
        body = _models_body()
        body["target_deployment"] = {
            "mode": "stacked",
            "members": [{"model": "JL320A", "modules": {"A": "JL083A"}}],
        }
        resp = client.post("/api/v1/migration/plan", json=body)
        assert resp.headers["X-Netcanon-Job-Status"] == "partial"
        job = resp.json()
        assert job["port_drops"] == [str(n) for n in range(25, 49)]
        assert [p["source"] for p in job["port_mapping_plan"]["unplaced"]] == (
            job["port_drops"]
        )
        assert job["port_mapping_plan"]["unresolved_ports"] == sorted(job["port_drops"])
        assert "Port mapping is incomplete: 24 name(s)" in job["error"]

    def test_an_operator_override_wins(self, client: TestClient) -> None:
        job = client.post(
            "/api/v1/migration/plan",
            json=_models_body(port_rename_map={"52": None}),
        ).json()
        assert "52" not in job["port_renames"]
        assert job["port_drops"] == ["52"]
        assert job["port_mapping_plan"]["overridden"] == ["52"]
        assert job["port_renames"]["51"] == "1/A3"

    @pytest.mark.parametrize(
        "path",
        ["/plan", "/plan/ports", "/plan/vlans", "/plan/local_users",
         "/plan/snmp", "/plan/snmpv3", "/render"],
    )
    def test_every_plan_endpoint_renders_the_same_port_names(
        self, client: TestClient, path: str,
    ) -> None:
        """The same body must not translate ports one way on /plan and
        another on a per-pane endpoint."""
        job = client.post(f"/api/v1/migration{path}", json=_models_body()).json()
        assert job["port_renames"]["49"] == "1/A1", path
        assert len(job["port_renames"]) == 52, path
        assert job["port_mapping_plan"]["applied"] is True, path

    @pytest.mark.parametrize(
        "path",
        ["/plan", "/plan/ports", "/plan/vlans", "/plan/local_users",
         "/plan/snmp", "/plan/snmpv3", "/render"],
    )
    def test_the_operators_port_map_applies_on_every_plan_endpoint(
        self, client: TestClient, path: str,
    ) -> None:
        """Four of the per-pane handlers pass an empty port map to the
        pipeline on purpose ("ignore a port map posted to this
        pane").  With both devices declared the pairing IS a port
        map, so the operator's edits to it must hold whichever URL
        the body goes to."""
        resp = client.post(f"/api/v1/migration{path}", json=_models_body(
            port_rename_map={"49": "1/A4", "52": None},
        ))
        job = resp.json()
        assert job["port_renames"]["49"] == "1/A4", path
        assert job["port_drops"] == ["52"], path
        assert job["port_mapping_plan"]["overridden"] == ["49", "52"], path
        assert resp.headers["X-Netcanon-Job-Status"] == "completed", path

    @pytest.mark.parametrize(
        "path",
        ["/plan", "/plan/ports", "/plan/vlans", "/plan/local_users",
         "/plan/snmp", "/plan/snmpv3", "/render"],
    )
    @pytest.mark.parametrize("typed", ["1/a1", " 1/A1"])
    def test_a_target_typed_in_another_case_is_still_that_port(
        self, client: TestClient, path: str, typed: str,
    ) -> None:
        """``49`` is paired onto ``1/A1``.  An override that sends
        ``50`` to ``1/a1`` puts two source ports on one physical port
        -- the job must not be ``completed`` because the two were
        spelt differently."""
        resp = client.post(f"/api/v1/migration{path}", json=_models_body(
            port_rename_map={"50": typed},
        ))
        plan = resp.json()["port_mapping_plan"]
        assert plan["fused"] == {"1/A1": ["49", "50"]}, path
        assert plan["off_target"] == [], path
        assert resp.headers["X-Netcanon-Job-Status"] == "partial", path

    def test_a_blank_target_is_ignored_not_taken_as_a_decision(
        self, client: TestClient,
    ) -> None:
        """A form posts ``""`` for a field nobody touched."""
        body = _models_body(port_rename_map={"25": ""})
        body["target_deployment"] = {
            "mode": "stacked",
            "members": [{"model": "JL320A", "modules": {"A": "JL083A"}}],
        }
        job = client.post("/api/v1/migration/plan", json=body).json()
        plan = job["port_mapping_plan"]
        assert plan["ignored_overrides"] == ["25"]
        assert "25" in plan["unresolved_ports"] and "25" in job["port_drops"]

    @pytest.mark.parametrize(
        "path",
        ["/plan", "/plan/ports", "/plan/vlans", "/plan/local_users",
         "/plan/snmp", "/plan/snmpv3", "/render"],
    )
    def test_acknowledged_drops_clear_partial_on_every_plan_endpoint(
        self, client: TestClient, path: str,
    ) -> None:
        """The job's own message says "map or drop each one".  An
        operator who has done that must not be told to do it again
        because of the endpoint they posted to."""
        body = _models_body(port_rename_map={str(n): None for n in range(25, 49)})
        body["target_deployment"] = {
            "mode": "stacked",
            "members": [{"model": "JL320A", "modules": {"A": "JL083A"}}],
        }
        resp = client.post(f"/api/v1/migration{path}", json=body)
        assert resp.headers["X-Netcanon-Job-Status"] == "completed", path
        assert resp.json()["port_mapping_plan"]["unresolved_ports"] == [], path

    def test_profile_keys_work_on_both_sides(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json=_plan_body(
            source_profile="aruba_aoss/2930F-48G",
            target_profile="aruba_aoss/3810M-48G-PoEP",
            target_module="JL083A",
        )).json()
        assert job["port_renames"]["49"] == "1/A1"
        plan = job["port_mapping_plan"]
        assert (plan["source"]["origin"], plan["target"]["origin"]) == (
            "legacy-profile", "legacy-profile",
        )

    def test_a_declared_profiles_module_decides_its_ports(self, client: TestClient) -> None:
        """Stated empty, a 3810M has no uplink for the 2930F's four."""
        def run(**module: str) -> dict:
            return client.post("/api/v1/migration/plan", json=_plan_body(
                source_profile="aruba_aoss/2930F-48G",
                target_profile="aruba_aoss/3810M-48G-PoEP", **module,
            )).json()

        assert run()["port_renames"]["49"] == "1/A1"
        assert run(target_module="jl083a")["port_renames"]["49"] == "1/A1"
        assert run(target_module="")["port_drops"] == ["49", "50", "51", "52"]

    def test_a_deployment_and_a_profile_can_be_mixed(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json=_plan_body(
            source_deployment=SOURCE_2930F,
            target_profile="aruba_aoss/3810M-48G-PoEP",
            target_module="JL083A",
        )).json()
        assert job["port_renames"]["48"] == "1/48"

    def test_a_target_deployment_takes_precedence_over_a_target_profile(
        self, client: TestClient,
    ) -> None:
        """The browser sends ``target_profile`` on every request once a
        profile is picked; a declared deployment is the newer, more
        specific statement."""
        job = client.post("/api/v1/migration/plan", json=_models_body(
            target_profile="aruba_aoss/2930F-48G",
        )).json()
        assert job["port_mapping_plan"]["target"]["family"] == "aruba_aoss/2930M"


class TestWhatDoesNotEngageIt:
    """Positional mapping needs the SOURCE device declared.  Nothing a
    client sent before this feature existed may start re-pairing ports."""

    def test_a_bare_request_is_unchanged(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json=_plan_body()).json()
        assert job["port_mapping_plan"] is None
        assert job["port_renames"] == {}

    def test_a_target_profile_alone_stays_advisory(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json=_plan_body(
            target_profile="aruba_aoss/3810M-48G-PoEP", target_module="JL083A",
        )).json()
        assert job["port_mapping_plan"] is None
        assert job["port_renames"] == {}

    def test_an_unknown_module_on_an_advisory_profile_is_still_accepted(
        self, client: TestClient,
    ) -> None:
        """The module check belongs to a DECLARED device.  On its own
        a target profile is advisory, and what it carries has never
        been validated on the server."""
        resp = client.post("/api/v1/migration/plan", json=_plan_body(
            target_profile="aruba_aoss/3810M-48G-PoEP", target_module="TYPO",
        ))
        assert resp.status_code == 200
        assert resp.json()["port_mapping_plan"] is None

    def test_a_misspelt_top_level_field_is_ignored_as_it_always_was(
        self, client: TestClient,
    ) -> None:
        """The plan request has never refused unknown keys, and
        starting to would break clients that predate this.  The
        ``null`` plan is the signal that nothing was paired."""
        resp = client.post("/api/v1/migration/plan", json=_plan_body(
            source_deploymnet=SOURCE_2930F,
        ))
        assert resp.status_code == 200
        assert resp.json()["port_mapping_plan"] is None

    def test_source_ports_is_populated_regardless(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json=_plan_body()).json()
        assert len(job["source_ports"]) == 52


class TestRequestErrors:
    @pytest.mark.parametrize(
        ("extra", "needle"),
        [
            ({"source_deployment": SOURCE_2930F},
             "declared without a target device"),
            ({"source_profile": "aruba_aoss/2930F-48G"},
             "declared without a target device"),
            ({"source_deployment": {"members": [{"model": "NOPE"}]},
              "target_deployment": TARGET_2930M},
             "source_deployment: no device model 'NOPE'"),
            ({"source_deployment": SOURCE_2930F,
              "target_deployment": {"mode": "stacked",
                                    "members": [{"model": "JL322A", "id": 11}]}},
             "target_deployment: member id 11 is outside 1-10"),
            ({"source_profile": "cisco_iosxe/C9300-24UX",
              "target_deployment": TARGET_2930M},
             "source_profile: cisco_iosxe/C9300-24UX is a cisco_iosxe profile"),
            ({"source_deployment": SOURCE_2930F,
              "target_profile": "aruba_aoss/NOPE"},
             "target_profile: unknown target profile"),
            # A target deployment is new: unlike a bare target_profile it
            # can only be half a declaration, and a completed job that
            # paired nothing would hide that.
            ({"target_deployment": TARGET_2930M},
             "a target device was declared without a source device"),
            ({"source_deployment": SOURCE_2930F,
              "source_profile": "aruba_aoss/2930F-48G",
              "target_deployment": TARGET_2930M},
             "send source_deployment or source_profile, not both"),
            ({"source_module": "NM-8X", "target_profile": "aruba_aoss/2930F-48G"},
             "source_module needs source_profile"),
            ({"source_profile": "aruba_aoss/2930F-48G",
              "target_profile": "aruba_aoss/3810M-48G-PoEP",
              "target_module": "TYPO"},
             "target_module: aruba_aoss/3810M-48G-PoEP has no module 'TYPO' "
             "(modules: JL083A, JL078A)"),
            ({"source_profile": "aruba_aoss/3810M-48G-PoEP",
              "source_module": "NOPE", "target_deployment": TARGET_2930M},
             "source_module: aruba_aoss/3810M-48G-PoEP has no module 'NOPE'"),
        ],
    )
    def test_a_bad_declaration_is_a_422(
        self, client: TestClient, extra: dict, needle: str,
    ) -> None:
        resp = client.post("/api/v1/migration/plan", json=_plan_body(**extra))
        assert resp.status_code == 422
        assert needle in resp.json()["detail"]

    @pytest.mark.parametrize(
        "extra",
        [
            {"source_deployment": SOURCE_2930F,
             "source_profile": "aruba_aoss/2930F-48G",
             "target_deployment": TARGET_2930M},
            {"source_module": "NM-8X", "target_profile": "aruba_aoss/2930F-48G"},
            {"target_deployment": TARGET_2930M},
            {"source_deployment": SOURCE_2930F},
        ],
    )
    def test_a_refused_combination_does_not_send_the_config_back(
        self, client: TestClient, extra: dict,
    ) -> None:
        """A pydantic error raised at the body level carries the whole
        body as its ``input``: a megabyte of pasted config in a 422.
        These are raised as short strings instead."""
        resp = client.post("/api/v1/migration/plan", json=_plan_body(**extra))
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], str)
        assert "DEFAULT_VLAN" in CAPTURE_2930F
        assert "DEFAULT_VLAN" not in resp.text
        assert len(resp.text) < 400

    @pytest.mark.parametrize(
        ("url", "raw"),
        [
            ("/api/v1/migration/inventory",
             b'{"codec":"aruba_aoss","deployment":{"members":[{"model":"JL\\ud800"}]}}'),
            ("/api/v1/migration/inventory",
             b'{"codec":"aruba_aoss","deployment":{"mode":"x\\ud800",'
             b'"members":[{"model":"JL322A"}]}}'),
            ("/api/v1/migration/plan",
             b'{"source":"aruba_aoss","target":"aruba_aoss","raw_text":"x",'
             b'"source_deployment":{"members":[{"model":"JL\\ud800"}]}}'),
        ],
    )
    def test_a_lone_surrogate_in_a_declared_name_is_a_422_not_a_500(
        self, client: TestClient, url: str, raw: bytes,
    ) -> None:
        """``"\\ud800"`` is valid JSON and not valid text.  The
        validation error echoes the input; written out as UTF-8 that
        echo cannot be encoded, and the 422 used to become a 500."""
        resp = client.post(url, content=raw, headers={"Content-Type": "application/json"})
        assert resp.status_code == 422
        assert resp.json()["detail"][0]["type"] == "string_unicode"

    @pytest.mark.parametrize("declared", [False, True], ids=["no-devices", "devices"])
    @pytest.mark.parametrize(
        "port_map",
        [b'{"\\ud800":""}', b'{"\\ud800":"1/1"}', b'{"1":"\\ud800"}', b'{"zz":"\\ud800"}'],
        ids=["key-blank-target", "key", "value", "value-for-an-absent-port"],
    )
    @pytest.mark.parametrize(
        "path", ["/api/v1/migration/plan", "/api/v1/migration/plan/vlans"],
    )
    def test_a_name_in_a_rename_map_that_cannot_be_written_back_is_a_422(
        self, client: TestClient, path: str, port_map: bytes, declared: bool,
    ) -> None:
        """The job echoes the names of a rename map -- in
        ``port_renames``, and on the mapping plan when an entry is set
        aside.  A lone surrogate there could not be serialised: a 500,
        and with devices declared on every endpoint, since the port
        map then applies on all of them."""
        devices = (
            b',"source_deployment":{"mode":"standalone","members":[{"model":"JL260A"}]},'
            b'"target_deployment":{"mode":"stacked","members":[{"model":"JL322A"}]}'
        ) if declared else b""
        raw = (
            b'{"source":"aruba_aoss","target":"aruba_aoss","raw_text":"vlan 1\\n",'
            b'"port_rename_map":' + port_map + devices + b"}"
        )
        resp = client.post(path, content=raw, headers={"Content-Type": "application/json"})
        assert resp.status_code == 422
        (error,) = resp.json()["detail"]
        assert error["loc"] == ["body", "port_rename_map"]
        assert "valid Unicode text" in error["msg"]

    @pytest.mark.parametrize(
        ("path", "field"),
        [
            ("/api/v1/migration/plan", "source"),
            ("/api/v1/migration/detect", "raw_text"),
            ("/api/v1/migration/inventory", "codec"),
            ("/api/v1/backups", "devices"),
        ],
    )
    @pytest.mark.parametrize(
        ("value", "echoed"),
        [("NaN", "nan"), ("Infinity", "inf"), ('{"x": "caf' + chr(233) + '"}', {"x": "caf" + chr(233)})],
        ids=["nan", "infinity", "non-ascii"],
    )
    def test_a_rejected_request_is_answered_in_strict_json(
        self, client: TestClient, path: str, field: str, value: str, echoed: object,
    ) -> None:
        """The validation handler is the application's, on every
        endpoint.  Its body is what FastAPI's own would be -- status,
        content type, a list of errors each with the input that was
        refused -- and it is always JSON a browser can parse: ASCII
        only, and no bare ``NaN``, which the request parser accepts
        and ``JSON.parse`` does not."""
        raw = ('{"' + field + '": ' + value + "}").encode("utf-8")
        resp = client.post(path, content=raw, headers={"Content-Type": "application/json"})
        assert resp.status_code == 422
        assert resp.headers["content-type"] == "application/json"
        assert resp.text.isascii()

        def refuse(token: str) -> None:
            raise AssertionError(f"not JSON: bare {token} in the body")

        detail = json.loads(resp.text, parse_constant=refuse)["detail"]
        assert detail and all({"type", "loc", "msg", "input"} <= set(e) for e in detail)
        refused = [e["input"] for e in detail if e["loc"][:2] == ["body", field]]
        assert echoed in refused

    def test_an_unknown_target_profile_alone_is_still_accepted(
        self, client: TestClient,
    ) -> None:
        """``target_profile`` on its own has never been validated on
        the server, and requests that predate this feature rely on
        that.  It is only checked once it is one half of a declared
        pair."""
        resp = client.post("/api/v1/migration/plan", json=_plan_body(
            target_profile="aruba_aoss/NOPE",
        ))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# A port's factory name (RouterOS), through the API
# ---------------------------------------------------------------------------

#: A real CRS310-8G+2S+ export.
CAPTURE_CRS310 = (
    REPO_ROOT / "tests/fixtures/real/mikrotik/user_contrib_crs310_ros7.rsc"
).read_text(encoding="utf-8")

_ROUTEROS_NAMED = """/interface ethernet
set [ find default-name=ether1 ] comment="wan"
set [ find default-name=ether2 ] name=core-a comment="core A"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=10.0.0.1/24 interface=core-a
"""


def _find_lines(job: dict) -> list[str]:
    return [line for line in job["rendered"].splitlines() if "find default-name=" in line]


class TestAPortsFactoryName:
    """An entry of ``port_rename_map`` on RouterOS gives a port a
    name, and the output finds the port by the factory name it always
    had.  Only a request that declares the target device can move a
    port onto other hardware."""

    @pytest.mark.parametrize("path", ["/plan", "/plan/ports", "/render"])
    def test_without_devices_an_entry_names_a_port(self, client: TestClient, path: str) -> None:
        """What this request rendered before the feature existed, on a
        committed capture: pinned so that the shared translator cannot
        move it again."""
        job = client.post(f"/api/v1/migration{path}", json={
            "source": "mikrotik_routeros", "target": "mikrotik_routeros",
            "raw_text": CAPTURE_CRS310,
            "port_rename_map": {"ether1": "uplink-to-core"},
        }).json()
        assert job["status"] == "completed", path
        assert job["port_renames"] == {"ether1": "uplink-to-core"}
        (line,) = [text for text in _find_lines(job) if "uplink-to-core" in text]
        assert line.startswith("set [ find default-name=ether1 ] name=uplink-to-core ")
        assert job["port_mapping_plan"] is None

    def test_with_both_devices_declared_the_hardware_moves(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json={
            "source": "mikrotik_routeros", "target": "mikrotik_routeros",
            "raw_text": CAPTURE_CRS310,
            "source_profile": "mikrotik_routeros/CRS310-8G+2S+",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
        }).json()
        assert job["status"] == "completed"
        assert [line.split("default-name=")[1].split(" ")[0] for line in _find_lines(job)] == [
            *(f"sfp-sfpplus{n}" for n in range(1, 9)), "sfp28-1", "sfp28-2",
        ]

    def test_a_port_the_operator_named_goes_by_that_name_in_the_plan(
        self, client: TestClient,
    ) -> None:
        job = client.post("/api/v1/migration/plan", json={
            "source": "mikrotik_routeros", "target": "mikrotik_routeros",
            "raw_text": _ROUTEROS_NAMED,
            "source_profile": "mikrotik_routeros/CRS310-8G+2S+",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
        }).json()
        plan = job["port_mapping_plan"]
        assert plan["labelled_ports"] == {"core-a": "ether2"}
        assert plan["target_hardware"] == {"core-a": "sfp-sfpplus2"}
        assert sorted(job["source_ports"]) == ["core-a", "ether1"]
        assert job["port_renames"] == {"ether1": "sfp-sfpplus1"}
        assert (
            'set [ find default-name=sfp-sfpplus2 ] name=core-a comment="core A" disabled=no'
            in job["rendered"]
        )
        # The fields this adds are data on every plan.
        assert (plan["landed_off_target"], plan["stale_next_hops"]) == ({}, [])

    def test_onto_another_vendor_it_takes_the_name_of_its_paired_port(
        self, client: TestClient,
    ) -> None:
        job = client.post("/api/v1/migration/plan", json={
            "source": "mikrotik_routeros", "target": "arista_eos",
            "raw_text": _ROUTEROS_NAMED,
            "source_profile": "mikrotik_routeros/CRS310-8G+2S+",
            "target_profile": "arista_eos/DCS-7050SX-64",
        }).json()
        assert job["port_renames"] == {"ether1": "Ethernet1", "core-a": "Ethernet2"}
        assert "interface Ethernet2" in job["rendered"] and "core-a" not in job["rendered"]
        assert job["status"] == "completed"


class TestEachNameKeyedMap:
    @pytest.mark.parametrize(
        "field",
        ["port_rename_map", "local_user_rename_map",
         "snmp_community_rename_map", "snmpv3_user_rename_map"],
    )
    @pytest.mark.parametrize(
        "entry", [b'{"\\ud800":"x"}', b'{"x":"\\ud800"}'], ids=["key", "value"],
    )
    def test_a_name_that_cannot_be_written_back_is_refused_in_every_one(
        self, client: TestClient, field: str, entry: bytes,
    ) -> None:
        """All four maps are echoed on the job.  The check is one
        validator over four fields, and each field is one argument of
        its decorator."""
        raw = (
            b'{"source":"aruba_aoss","target":"aruba_aoss","raw_text":"vlan 1\\n","'
            + field.encode() + b'":' + entry + b"}"
        )
        resp = client.post(
            "/api/v1/migration/plan", content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422
        (error,) = resp.json()["detail"]
        assert error["loc"] == ["body", field]
        assert "valid Unicode text" in error["msg"]


_EOS_TWO_ROUTED_PORTS = """hostname sw
!
interface Ethernet1
   description wan
   no switchport
   ip address 192.0.2.1/24
!
interface Ethernet2
   description lan
   no switchport
   ip address 10.0.0.1/24
!
end
"""


class TestEveryPlacedPortIsFoundByItsHardware:
    """A RouterOS target finds a port by its factory name.  With both
    devices declared, every port the mapping placed is looked up by
    the port of the target it is on -- from any source vendor."""

    def test_a_port_from_another_vendor_that_the_operator_names(
        self, client: TestClient,
    ) -> None:
        job = client.post("/api/v1/migration/plan", json={
            "source": "arista_eos", "target": "mikrotik_routeros",
            "raw_text": _EOS_TWO_ROUTED_PORTS,
            "source_profile": "arista_eos/DCS-7050SX-64",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
            "port_rename_map": {"Ethernet1": "WAN"},
        }).json()
        plan = job["port_mapping_plan"]
        assert job["status"] == "completed"
        assert _find_lines(job) == [
            'set [ find default-name=sfp-sfpplus1 ] name=WAN comment="wan" disabled=no',
            'set [ find default-name=sfp-sfpplus2 ] comment="lan" disabled=no',
        ]
        assert "find name=" not in job["rendered"]
        assert plan["target_hardware"] == {"Ethernet1": "sfp-sfpplus1"}
        assert (plan["off_target"], plan["source_hardware"]) == ([], {})
        assert any("taken as NAMES" in line for line in plan["warnings"])

    def test_an_entry_keyed_by_a_factory_name_is_taken_for_the_port(
        self, client: TestClient,
    ) -> None:
        """A requested drop used to be ignored, in a job that said
        ``completed``."""
        job = client.post("/api/v1/migration/plan", json={
            "source": "mikrotik_routeros", "target": "arista_eos",
            "raw_text": _ROUTEROS_NAMED,
            "source_profile": "mikrotik_routeros/CRS310-8G+2S+",
            "target_profile": "arista_eos/DCS-7050SX-64",
            "port_rename_map": {"ether2": None},
        }).json()
        assert job["port_drops"] == ["core-a"]
        assert "10.0.0.1" not in job["rendered"]
        assert job["port_mapping_plan"]["overridden"] == ["core-a"]

    def test_a_port_no_line_of_the_output_finds_is_reported(
        self, client: TestClient,
    ) -> None:
        """RouterOS output has no Ethernet line for a port whose name
        reads as a bridge.  The plan says so, and the job is not
        ``completed``."""
        job = client.post("/api/v1/migration/plan", json={
            "source": "arista_eos", "target": "mikrotik_routeros",
            "raw_text": _EOS_TWO_ROUTED_PORTS,
            "source_profile": "arista_eos/DCS-7050SX-64",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
            "port_rename_map": {"Ethernet1": "bridge-uplink"},
        }).json()
        plan = job["port_mapping_plan"]
        assert "sfp-sfpplus1" not in job["rendered"]
        assert plan["unbound_ports"] == {"Ethernet1": "sfp-sfpplus1"}
        assert plan["target_hardware"] == {}
        assert job["status"] == "partial"
        assert "not looked up by their hardware in the output" in job["error"]

    def test_a_management_vlan_on_a_port_the_target_lacks_asks_for_a_decision(
        self, client: TestClient,
    ) -> None:
        text = (
            'config system interface\n    edit "port1"\n        set ip 10.1.1.1 255.255.255.0\n'
            '        set type physical\n    next\n    edit "MGMT"\n'
            '        set ip 10.90.0.1 255.255.255.0\n        set interface "port1"\n'
            "        set vlanid 90\n    next\nend\n"
        )
        job = client.post("/api/v1/migration/plan", json={
            "source": "fortigate_cli", "target": "juniper_junos", "raw_text": text,
            "source_profile": "fortigate/100E", "target_profile": "juniper_junos/EX4300-48T",
            "force": True,
        }).json()
        plan = job["port_mapping_plan"]
        assert plan["landed_off_target"] == {"MGMT": "em1"}
        assert plan["unresolved_ports"] == ["MGMT"]
        assert job["status"] == "partial"
