"""
API integration tests for model-to-model port mapping.

Covers:
  * GET  /api/v1/migration/model-families — the families a picker is built from
  * POST /api/v1/migration/inventory — one declared device, compiled to its ports
  * POST /api/v1/migration/detect-deployment — the source device, read from the config
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
import re
import time
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
            {"role": "access", "count": 48, "slot": "", "prefix": "",
             "speed": "gig", "cage": "rj45", "poe": False, "notes": ""},
            {"role": "uplink", "count": 4, "slot": "", "prefix": "",
             "speed": "gig", "cage": "sfp", "poe": False, "notes": ""},
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
    @pytest.mark.parametrize("declared", [True, False], ids=["devices declared", "no devices"])
    def test_a_key_in_another_letter_case_is_that_port_on_every_plan_endpoint(
        self, client: TestClient, path: str, declared: bool,
    ) -> None:
        """One body, one answer: ``1/a1`` is the port the config calls
        ``1/A1``, whichever URL it goes to and whether or not devices
        are declared.  With them it was "does not exist ... entry
        ignored", the port stayed, and the job said ``completed``."""
        stack = {"mode": "stacked", "members": [{"model": "JL323A", "id": 1, "modules": {"A": "JL083A"}}]}
        capture = (
            REPO_ROOT / "tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg"
        ).read_text(encoding="utf-8")
        body = {
            "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": capture,
            "port_rename_map": {"1/a1": None},
        }
        if declared:
            body |= {"source_deployment": stack, "target_deployment": stack}
        # No pane sets a posted port map aside any more: the four
        # category panes did, where no devices were declared.
        job = client.post(f"/api/v1/migration{path}", json=body).json()
        assert job["port_drops"] == ["1/A1"], path
        assert not [w for w in job["warnings"] if "does not exist" in w], path
        if declared:
            assert job["port_mapping_plan"]["overridden"] == ["1/A1"], path

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

    def test_a_blank_target_is_refused(
        self, client: TestClient,
    ) -> None:
        """``""`` is neither a name nor a way to drop.  With devices
        declared the pipeline sets such an entry aside
        (``ignored_overrides``, which a caller in Python still gets);
        the API says so before any job is run, as it does with none
        declared -- see ``TestABlankTarget``."""
        body = _models_body(port_rename_map={"25": ""})
        body["target_deployment"] = {
            "mode": "stacked",
            "members": [{"model": "JL320A", "modules": {"A": "JL083A"}}],
        }
        resp = client.post("/api/v1/migration/plan", json=body)
        assert resp.status_code == 422
        (error,) = resp.json()["detail"]
        assert error["loc"] == ["body", "port_rename_map"]
        # ``null`` is how that port is dropped by decision.
        body["port_rename_map"] = {"25": None}
        job = client.post("/api/v1/migration/plan", json=body).json()
        assert job["port_mapping_plan"]["ignored_overrides"] == []
        assert "25" not in job["port_mapping_plan"]["unresolved_ports"]
        assert "25" in job["port_drops"]

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

    @pytest.mark.parametrize(
        "path",
        ["/plan", "/plan/ports", "/plan/vlans", "/plan/local_users",
         "/plan/snmp", "/plan/snmpv3", "/render"],
    )
    def test_without_devices_an_entry_names_a_port(self, client: TestClient, path: str) -> None:
        """What this request rendered before the feature existed, on a
        committed capture: pinned so that the shared translator cannot
        move it again.  (On the four category panes it rendered no
        entry at all until every plan endpoint applied the port map.)
        The capture's ``ether1`` has a name of its own, ``Desktop``,
        which every line of the config calls it by -- so that is the
        entry's key."""
        job = client.post(f"/api/v1/migration{path}", json={
            "source": "mikrotik_routeros", "target": "mikrotik_routeros",
            "raw_text": CAPTURE_CRS310,
            "port_rename_map": {"Desktop": "uplink-to-core"},
        }).json()
        assert job["status"] == "completed", path
        assert job["port_renames"] == {"Desktop": "uplink-to-core"}
        (line,) = [text for text in _find_lines(job) if "uplink-to-core" in text]
        assert line.startswith("set [ find default-name=ether1 ] name=uplink-to-core ")
        assert job["port_mapping_plan"] is None

    def test_with_both_devices_declared_the_hardware_moves(self, client: TestClient) -> None:
        """Each port is looked up by the port of the target it was
        paired with, and keeps the name the operator gave it."""
        job = client.post("/api/v1/migration/plan", json={
            "source": "mikrotik_routeros", "target": "mikrotik_routeros",
            "raw_text": CAPTURE_CRS310,
            "source_profile": "mikrotik_routeros/CRS310-8G+2S+",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
        }).json()
        assert job["status"] == "completed"
        found = {}
        for line in _find_lines(job):
            lookup = re.search(r'find default-name=(\S+) \](?: name=("[^"]*"|\S+))?', line)
            assert lookup is not None, line
            found[lookup.group(1)] = (lookup.group(2) or "").strip('"') or None
        assert found == {
            "sfp-sfpplus1": "Desktop",
            "sfp-sfpplus2": "Access Point",
            "sfp-sfpplus3": "CLUSTER - PVENAS",
            "sfp-sfpplus4": "PROD - PVENAS",
            "sfp-sfpplus5": "CLUSTER - PVE5",
            "sfp-sfpplus6": "PROD - PVE5",
            "sfp-sfpplus7": "CLUSTER - PVE3",
            "sfp-sfpplus8": "PROD - PVE3",
            "sfp28-1": "UPLINKSFP",
            "sfp28-2": None,  # the capture's sfp-sfpplus2, which has no name of its own
        }

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


#: An AOS-S config with no ``interface`` stanza: two LAG members and
#: two ports a VLAN lists.  The parser gives each of them a record.
_AOSS_TRUNK_MEMBERS_WITH_NO_STANZA = """; JL259A Configuration Editor; Created on release #WC.16.11.0003
hostname "sw"
trunk 1-2 trk1 lacp
vlan 1
   name "DEFAULT_VLAN"
   untagged 3-4
   ip address 10.0.0.2 255.255.255.0
   exit
"""

#: An OPNsense lagg.  Its members are NICs assigned to nothing (OPNsense
#: adds no other to a lagg): the config has an interface for ``lagg0``
#: and none for ``igb0`` or ``igb1``, and the parser gives each a
#: record of its own.
_OPNSENSE_LAGG = """<?xml version="1.0"?>
<opnsense>
  <system>
    <hostname>fw</hostname>
  </system>
  <interfaces>
    <lan>
      <if>lagg0</if>
      <enable>1</enable>
      <ipaddr>10.0.0.2</ipaddr>
      <subnet>24</subnet>
    </lan>
  </interfaces>
  <laggs>
    <lagg>
      <members>igb0,igb1</members>
      <laggif>lagg0</laggif>
      <proto>lacp</proto>
    </lagg>
  </laggs>
</opnsense>
"""


class TestEveryPlacedPortIsFoundByItsHardware:
    """A RouterOS target finds a port by its factory name.  With both
    devices declared, every placed port the config has an interface
    for is looked up by the port of the target it is on -- from any
    source vendor; a placed port with none is reported when an entry
    names it."""

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

    def test_a_lagg_member_is_looked_up_by_its_hardware(
        self, client: TestClient,
    ) -> None:
        """The members of an OPNsense lagg are NICs assigned to
        nothing: the config has no interface for them, and the parser
        gives each a record.  Named by an entry, one is looked up by
        the hardware it was paired with.  (With no record it was
        written into ``slaves=`` under a name no line defines.)"""
        request = {
            "source": "opnsense", "target": "mikrotik_routeros",
            "raw_text": _OPNSENSE_LAGG,
            "source_profile": "opnsense/Protectli-FW4B-IGB",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
        }
        job = client.post("/api/v1/migration/plan", json=request).json()
        assert "slaves=sfp-sfpplus1,sfp-sfpplus2" in job["rendered"]
        assert job["status"] == "completed"
        job = client.post("/api/v1/migration/plan", json={
            **request, "port_rename_map": {"igb0": "up-a"},
        }).json()
        plan = job["port_mapping_plan"]
        assert _find_lines(job) == [
            "set [ find default-name=sfp-sfpplus1 ] name=up-a disabled=no",
            "set [ find default-name=sfp-sfpplus2 ] disabled=no",
        ]
        assert "slaves=up-a,sfp-sfpplus2" in job["rendered"]
        assert (plan["unbound_ports"], plan["off_target"]) == ({}, [])
        assert plan["target_hardware"] == {"igb0": "sfp-sfpplus1"}
        assert job["status"] == "completed"

    def test_an_aoss_port_only_a_list_names(
        self, client: TestClient,
    ) -> None:
        """An AOS-S config has no stanza for a port with no setting of
        its own; the parser gives it a record all the same.  A trunk
        member and a port in a VLAN's list are each looked up by the
        hardware they were paired with, under the name an entry gives
        them."""
        job = client.post("/api/v1/migration/plan", json={
            "source": "aruba_aoss", "target": "mikrotik_routeros",
            "raw_text": _AOSS_TRUNK_MEMBERS_WITH_NO_STANZA,
            "source_deployment": {"mode": "standalone", "members": [{"model": "JL259A"}]},
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
            "port_rename_map": {"1": "up-a", "3": "srv"},
        }).json()
        plan = job["port_mapping_plan"]
        assert _find_lines(job) == [
            "set [ find default-name=sfp-sfpplus1 ] name=up-a disabled=no",
            "set [ find default-name=sfp-sfpplus2 ] disabled=no",
            "set [ find default-name=sfp-sfpplus3 ] name=srv disabled=no",
            "set [ find default-name=sfp-sfpplus4 ] disabled=no",
        ]
        assert "slaves=up-a,sfp-sfpplus2" in job["rendered"]
        assert (plan["unbound_ports"], plan["off_target"]) == ({}, [])
        assert plan["target_hardware"] == {"1": "sfp-sfpplus1", "3": "sfp-sfpplus3"}

    def test_and_so_is_one_under_a_name_with_white_space(
        self, client: TestClient,
    ) -> None:
        """A name with white space in it is written in a string, on the
        port's own line and in ``slaves=``, and read back whole."""
        job = client.post("/api/v1/migration/plan", json={
            "source": "opnsense", "target": "mikrotik_routeros",
            "raw_text": _OPNSENSE_LAGG,
            "source_profile": "opnsense/Protectli-FW4B-IGB",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
            "port_rename_map": {"igb0": "my port"},
        }).json()
        plan = job["port_mapping_plan"]
        assert _find_lines(job) == [
            'set [ find default-name=sfp-sfpplus1 ] name="my port" disabled=no',
            "set [ find default-name=sfp-sfpplus2 ] disabled=no",
        ]
        assert 'slaves="my port,sfp-sfpplus2"' in job["rendered"]
        assert (plan["unbound_ports"], plan["off_target"]) == ({}, [])
        assert plan["target_hardware"] == {"igb0": "sfp-sfpplus1"}
        assert job["status"] == "completed"

    @pytest.mark.parametrize(("name", "written"), [
        ("a,b", "slaves=a,b,sfp-sfpplus2"),
        ("a b,c", 'slaves="a b,c,sfp-sfpplus2"'),
    ])
    def test_and_one_under_a_name_a_list_cuts_is_reported(
        self, client: TestClient, name: str, written: str,
    ) -> None:
        """A comma parts two members, written bare or in a string, so a
        name with one in it is not read back whole.  The port is
        reported, though a line of its own finds its hardware; this
        used to be ``completed``."""
        resp = client.post("/api/v1/migration/plan", json={
            "source": "opnsense", "target": "mikrotik_routeros",
            "raw_text": _OPNSENSE_LAGG,
            "source_profile": "opnsense/Protectli-FW4B-IGB",
            "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
            "port_rename_map": {"igb0": name},
        })
        assert resp.headers["X-Netcanon-Job-Status"] == "partial"
        job = resp.json()
        assert written in job["rendered"]
        assert job["port_mapping_plan"]["unbound_ports"] == {"igb0": "sfp-sfpplus1"}
        assert job["port_mapping_plan"]["off_target"] == []

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
        # On the hardware switch ``internal`` it is a VLAN interface,
        # whose name the classifier reads as the management port (on
        # ``port1`` it would be a unit of the port, and follow it).
        text = (
            'config system interface\n    edit "port1"\n        set ip 10.1.1.1 255.255.255.0\n'
            '        set type physical\n    next\n    edit "MGMT"\n'
            '        set ip 10.90.0.1 255.255.255.0\n        set interface "internal"\n'
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


# ---------------------------------------------------------------------------
# Names that are no hardware port, and a unit that moved with no tag
# ---------------------------------------------------------------------------

_PLAN_PATHS = [
    "/plan", "/plan/ports", "/plan/vlans", "/plan/local_users",
    "/plan/snmp", "/plan/snmpv3", "/render",
]

#: An AOS-S LAG, named ``trk1`` where it is defined and ``Trk1`` in a
#: VLAN's list.
_AOSS_WITH_A_LAG = """; JL260A Configuration Editor; Created on release #WC.16.07.0002
hostname "sw"
trunk 51-52 trk1 lacp
vlan 1
   name "DEFAULT_VLAN"
   untagged 1-50
   tagged Trk1
   exit
"""

#: An AOS-CX sub-interface.  The config states its tag; the AOS-CX
#: parser reads none.
_AOSCX_UNIT = "\n".join([
    "!Version ArubaOS-CX FL.10.10.1010", "hostname r1", "!",
    "interface 1/1/1", "    no shutdown", "    routing", "    description PARENT",
    "interface 1/1/1.54", "    no shutdown", "    encapsulation dot1q 300",
    "    ip address 10.54.0.1/24",
    "interface 1/1/2", "    no shutdown", "    routing", "    ip address 10.2.0.1/24", "",
])


class TestNamesThatAreNoHardwarePort:
    """``source_other_names`` beside ``source_ports``.  A job from a
    vendor to itself renames no LAG and warns about none, so nothing
    else in its answer says the config has one."""

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    @pytest.mark.parametrize("declared", [False, True], ids=["no devices", "devices declared"])
    def test_every_plan_endpoint_returns_them(
        self, client: TestClient, path: str, declared: bool,
    ) -> None:
        body = {"source": "aruba_aoss", "target": "aruba_aoss", "raw_text": _AOSS_WITH_A_LAG}
        if declared:
            body |= {"source_deployment": SOURCE_2930F, "target_deployment": TARGET_2930M}
        job = client.post(f"/api/v1/migration{path}", json=body).json()
        assert job["source_other_names"] == ["trk1"], path
        assert "trk1" not in job["source_ports"] and len(job["source_ports"]) == 52, path
        assert "trk1" not in job["port_renames"], path

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_an_entry_keyed_by_one_renames_it(self, client: TestClient, path: str) -> None:
        """What a client lists the names for -- on every plan
        endpoint: none sets a posted port map aside."""
        job = client.post(f"/api/v1/migration{path}", json={
            "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": _AOSS_WITH_A_LAG,
            "port_rename_map": {"trk1": "trk7"},
        }).json()
        assert job["port_renames"] == {"trk1": "trk7"}, path
        assert "trunk 51-52 trk7 lacp" in job["rendered"], path
        assert job["source_other_names"] == ["trk1"], path


class TestAUnitThatMovedWithNoTag:
    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_it_is_on_the_plan_on_every_endpoint(
        self, client: TestClient, path: str,
    ) -> None:
        resp = client.post(f"/api/v1/migration{path}", json={
            "source": "aruba_aoscx", "target": "arista_eos", "raw_text": _AOSCX_UNIT,
            "source_profile": "aruba_aoscx/6300M-48G-PoE4-SFP56",
            "target_profile": "arista_eos/DCS-7050SX-64",
        })
        job = resp.json()
        plan = job["port_mapping_plan"]
        assert plan["untagged_units"] == {"1/1/1.54": "Ethernet1.54"}, path
        assert plan["sub_interfaces"] == {} and plan["unresolved_ports"] == ["1/1/1.54"], path
        assert resp.headers["X-Netcanon-Job-Status"] == "partial", path
        assert [w for w in job["warnings"] if "moved with their port" in w], path

    def test_without_devices_one_warning_says_it(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json={
            "source": "aruba_aoscx", "target": "arista_eos", "raw_text": _AOSCX_UNIT,
        }).json()
        assert job["port_mapping_plan"] is None
        (line,) = [w for w in job["warnings"] if "802.1Q" in w]
        assert line.startswith("port_rename: '1/1/1.54' went with its port to 'Ethernet1.54'")


#: An IOS-XE unit typed in another letter case than its port.
_IOS_UNIT_IN_ANOTHER_CASE = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "interface GigabitEthernet1/0/1", " description PARENT", "!",
    "interface gigabitethernet1/0/1.54", " encapsulation dot1Q 54",
    " ip address 10.54.0.1 255.255.255.0", "!", "end", "",
])


class TestAUnitThePlanDoesNotVouchFor:
    """It moved with its port, and the plan says so in a field and
    in a line -- on every endpoint that runs a job."""

    _BODY = {
        "source": "cisco_iosxe_cli", "target": "arista_eos",
        "raw_text": _IOS_UNIT_IN_ANOTHER_CASE,
        "source_profile": "cisco_iosxe/C9300-24P",
        "target_profile": "arista_eos/DCS-7050SX-64",
    }

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_it_is_on_the_plan_on_every_endpoint(
        self, client: TestClient, path: str,
    ) -> None:
        resp = client.post(f"/api/v1/migration{path}", json=self._BODY)
        job = resp.json()
        plan = job["port_mapping_plan"]
        unit = "gigabitethernet1/0/1.54"
        assert plan["unvouched_units"] == {unit: "Ethernet1.54"}, path
        assert plan["untagged_units"] == {} and plan["sub_interfaces"] == {}, path
        assert plan["unresolved_ports"] == [unit], path
        assert resp.headers["X-Netcanon-Job-Status"] == "partial", path
        (line,) = [w for w in job["warnings"] if "moved with their port" in w]
        assert "the plan does not vouch for where they went" in line, path

    def test_naming_it_ends_it(self, client: TestClient) -> None:
        """The line says to name the unit in the port map.  Doing so
        leaves nothing to decide and raises no other line."""
        resp = client.post("/api/v1/migration/plan", json={
            **self._BODY,
            "port_rename_map": {"gigabitethernet1/0/1.54": "Ethernet1.54"},
        })
        plan = resp.json()["port_mapping_plan"]
        assert plan["unvouched_units"] == {} and plan["unresolved_ports"] == []
        assert plan["off_target"] == []
        assert resp.headers["X-Netcanon-Job-Status"] == "completed"


# ---------------------------------------------------------------------------
# Port names that are not settled, with no devices declared
# ---------------------------------------------------------------------------

#: A Junos router: a port, the loopback, an ``irb`` and a ``vlan``
#: unit of one VLAN (the two Junos grammars' names for a VLAN
#: interface), and the management port.  Onto IOS-XE both VLAN
#: interfaces are written ``Vlan100``, and the management port has no
#: name there.
_JUNOS_NOT_SETTLED = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24",
    "set interfaces lo0 unit 0 family inet address 192.0.2.1/32",
    "set interfaces irb unit 100 family inet address 192.0.2.65/26",
    "set interfaces vlan unit 100 family inet address 192.0.2.2/32",
    "set interfaces fxp0 unit 0 family inet address 198.51.100.9/24",
    "",
])


#: A Catalyst port, and the port of a virtual router: ``GigabitEthernet1``
#: has no slot, and the IOS-XE classifier does not read it.
_IOS_UNREAD = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "interface GigabitEthernet1/0/1", " ip address 10.1.0.1 255.255.255.0", "!",
    "interface GigabitEthernet1", " ip address 10.2.0.1 255.255.255.0", "!",
    "end", "",
])

#: A FortiGate whose LAN address is on its hardware switch.
_FORTIOS_HARD_SWITCH = "\n".join([
    "#config-version=FGT60F-7.2.5-FW-build1517-230606:opmode=0:vdom=0",
    "config system interface",
    '    edit "wan1"', "        set ip 198.51.100.2 255.255.255.252", "    next",
    '    edit "internal"', "        set ip 192.168.1.99 255.255.255.0",
    "        set type hard-switch", "    next",
    "end", "",
])

#: An NX-OS switch with its management port, which IOS-XE has no name for.
_NXOS_WITH_MGMT = "\n".join([
    "!Command: show running-config", "version 9.3(11) Bios:version", "hostname r1", "",
    "interface Ethernet1/1", "  no switchport", "  ip address 10.1.0.1/24", "",
    "interface mgmt0", "  vrf member management", "  ip address 192.0.2.9/24", "",
])


def _not_settled_body(**extra) -> dict:
    return {
        "source": "juniper_junos", "target": "cisco_iosxe_cli",
        "raw_text": _JUNOS_NOT_SETTLED, **extra,
    }


class TestPortNamesWithNoDevices:
    """A warning is not a status.  Two source names on one name of the
    output, and a hardware port dropped because the target has no name
    for it, were said in warning lines by a job that was ``completed``.
    Such a job is ``partial`` now, says which names as data, and is
    settled by entries of ``port_rename_map`` -- the same way on every
    plan endpoint."""

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_names_not_settled_on_every_endpoint(
        self, client: TestClient, path: str,
    ) -> None:
        resp = client.post(f"/api/v1/migration{path}", json=_not_settled_body())
        assert resp.status_code == 200
        assert resp.headers["X-Netcanon-Job-Status"] == "partial", path
        job = resp.json()
        assert job["status"] == "partial", path
        assert job["fused_ports"] == {"Vlan100": ["irb.100", "vlan.100"]}, path
        assert job["unresolved_ports"] == ["fxp0"], path
        assert job["untranslated_ports"] == [], path
        assert job["error"] == (
            "Port names are not settled: 1 name(s) in the output received "
            "more than one source name, so the config of two interfaces is "
            "written as one. 1 port(s) the target has no name for were "
            "dropped from the output. An entry in port_rename_map settles "
            "each: a name of its own, or null, for all but one of the names "
            "that share one; a target name for a dropped name, or null to "
            "say it is to go. Declaring both devices pairs the hardware "
            "ports among these by position; the other names need an entry "
            "either way."
        ), path
        assert job["port_mapping_plan"] is None, path
        # The output is as it was: nothing is renamed or dropped for it.
        assert job["rendered"].count("interface Vlan100\n") == 2, path
        assert "198.51.100.9" not in job["rendered"], path

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_no_device_is_offered_where_none_is_described(
        self, client: TestClient, path: str,
    ) -> None:
        """No model family and no target profile is of IOS XR's
        vendor: two of its ports on one AOS-S name are settled by an
        entry and by nothing else.  The sentence offered both
        devices all the same -- advice nobody could take, which the
        migrate page did not give."""
        text = (REPO_ROOT / "tests/fixtures/real/cisco_iosxr/xrdtools_isis_r1.cfg").read_text(
            encoding="utf-8",
        )
        resp = client.post(
            f"/api/v1/migration{path}",
            json={"source": "cisco_iosxr", "target": "aruba_aoss", "raw_text": text},
        )
        job = resp.json()
        assert job["status"] == "partial" and job["fused_ports"], path
        assert job["error"].endswith(
            "An entry in port_rename_map settles each: a name of its own, "
            "or null, for all but one of the names that share one."
        ), path
        assert "devices" not in job["error"], path

    def test_which_vendors_have_a_device_to_declare(self, client: TestClient) -> None:
        """Typed by hand from the shipped registries, as the migrate
        page's device pickers show them."""
        from types import SimpleNamespace

        from netcanon.api.routes._migration_helpers import a_device_is_described
        from netcanon.migration.codecs.registry import get_codec, list_public_codecs

        request = SimpleNamespace(app=client.app)
        none = {
            name for name in list_public_codecs()
            if not a_device_is_described(request, get_codec(name))
        }
        assert none == {"cisco_iosxr", "cisco_nxos", "dell_os10", "vyos"}

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_entries_settle_it_on_every_endpoint(
        self, client: TestClient, path: str,
    ) -> None:
        """A name of its own for one of the two VLAN interfaces, and
        ``null`` for the port that went: the operator has decided
        each, and must not be asked again because of the URL."""
        resp = client.post(f"/api/v1/migration{path}", json=_not_settled_body(
            port_rename_map={"vlan.100": "Loopback2", "fxp0": None},
        ))
        assert resp.headers["X-Netcanon-Job-Status"] == "completed", path
        job = resp.json()
        assert (job["fused_ports"], job["unresolved_ports"]) == ({}, []), path
        assert job["error"] is None, path
        assert job["port_drops"] == ["fxp0"], path
        assert "interface Loopback2\n ip address 192.0.2.2 255.255.255.255" in job["rendered"]

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_one_entry_settles_one_name(self, client: TestClient, path: str) -> None:
        resp = client.post(f"/api/v1/migration{path}", json=_not_settled_body(
            port_rename_map={"fxp0": "GigabitEthernet0/0"},
        ))
        job = resp.json()
        assert job["unresolved_ports"] == [], path
        assert job["fused_ports"] == {"Vlan100": ["irb.100", "vlan.100"]}, path
        assert resp.headers["X-Netcanon-Job-Status"] == "partial", path
        assert "198.51.100.9" in job["rendered"], path

    def test_two_entries_on_one_name_are_said(self, client: TestClient) -> None:
        """Whoever decided it, two interfaces are one."""
        job = client.post("/api/v1/migration/plan", json=_not_settled_body(
            port_rename_map={"vlan.100": "Loopback7", "fxp0": "Loopback7"},
        )).json()
        assert job["fused_ports"] == {"Loopback7": ["fxp0", "vlan.100"]}
        assert job["status"] == "partial"

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_a_name_left_as_it_was_everywhere(
        self, client: TestClient, path: str,
    ) -> None:
        """An IOS name the translator cannot read, written into an
        EOS config as it stands.  Listed apart from what was dropped:
        the name IS in the output, and what settles it is a name --
        its own, if that is right on the target."""
        body = {
            "source": "cisco_iosxe_cli", "target": "arista_eos", "raw_text": _IOS_UNREAD,
        }
        resp = client.post(f"/api/v1/migration{path}", json=body)
        assert resp.headers["X-Netcanon-Job-Status"] == "partial", path
        job = resp.json()
        assert job["untranslated_ports"] == ["GigabitEthernet1"], path
        assert (job["fused_ports"], job["unresolved_ports"], job["port_drops"]) == ({}, [], [])
        assert "interface GigabitEthernet1\n" in job["rendered"], path
        assert job["error"].startswith(
            "Port names are not settled: 1 name(s) could not be read as any "
            "kind of port: whatever the output has of them is under the name "
            "the source config has for them"
        ), path
        for entry, shown in (
            ("GigabitEthernet1", "interface GigabitEthernet1\n"),
            ("Ethernet7", "interface Ethernet7\n"),
            (None, "interface Ethernet1\n"),
        ):
            resp = client.post(
                f"/api/v1/migration{path}",
                json={**body, "port_rename_map": {"GigabitEthernet1": entry}},
            )
            assert resp.headers["X-Netcanon-Job-Status"] == "completed", (path, entry)
            job = resp.json()
            assert (job["untranslated_ports"], job["error"]) == ([], None), (path, entry)
            assert shown in job["rendered"], (path, entry)
            assert ("10.2.0.1" in job["rendered"]) is (entry is not None), (path, entry)

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_a_logical_name_dropped_everywhere(
        self, client: TestClient, path: str,
    ) -> None:
        """A FortiGate hardware switch that holds the LAN address is
        no port of any other vendor: dropped, the address with it,
        and listed as a dropped port is."""
        body = {
            "source": "fortigate_cli", "target": "cisco_iosxe_cli",
            "raw_text": _FORTIOS_HARD_SWITCH,
        }
        resp = client.post(f"/api/v1/migration{path}", json=body)
        assert resp.headers["X-Netcanon-Job-Status"] == "partial", path
        job = resp.json()
        assert job["source_other_names"] == ["internal"], path
        assert job["unresolved_ports"] == ["internal"], path
        assert "192.168.1.99" not in job["rendered"], path
        assert "devices" not in job["error"], path
        for entry in ("Vlan1", None):
            resp = client.post(f"/api/v1/migration{path}", json={
                **body, "port_rename_map": {"internal": entry},
            })
            assert resp.headers["X-Netcanon-Job-Status"] == "completed", (path, entry)
            assert ("192.168.1.99" in resp.json()["rendered"]) is (entry is not None), path

    def test_a_target_alone_is_checked_too(self, client: TestClient) -> None:
        """What the page sends once a target is chosen and no source:
        advice, which pairs nothing.  The run is still one made by
        name shape, and says what it left unsettled."""
        resp = client.post("/api/v1/migration/plan", json=_not_settled_body(
            target_profile="cisco_iosxe/C9300-24P",
        ))
        assert resp.status_code == 200
        job = resp.json()
        assert job["port_mapping_plan"] is None
        assert job["status"] == "partial"
        assert job["fused_ports"] == {"Vlan100": ["irb.100", "vlan.100"]}
        assert job["unresolved_ports"] == ["fxp0"]

    def test_devices_are_not_offered_for_these(
        self, client: TestClient,
    ) -> None:
        """Two VLAN interfaces on one.  With both devices declared
        the same output is ``completed`` -- the pairing is of
        hardware ports and asks nothing of these -- so the sentence
        of the job with none declared does not offer it."""
        body = {
            "source": "juniper_junos", "target": "arista_eos",
            "raw_text": _JUNOS_NOT_SETTLED.replace(
                "set interfaces fxp0 unit 0 family inet address 198.51.100.9/24\n", "",
            ),
        }
        job = client.post("/api/v1/migration/plan", json=body).json()
        assert job["status"] == "partial"
        assert job["fused_ports"] == {"Vlan100": ["irb.100", "vlan.100"]}
        assert job["error"] == (
            "Port names are not settled: 1 name(s) in the output received "
            "more than one source name, so the config of two interfaces is "
            "written as one. An entry in port_rename_map settles each: a "
            "name of its own, or null, for all but one of the names that "
            "share one."
        )
        paired = client.post("/api/v1/migration/plan", json={
            **body, "source_profile": "juniper_junos/EX4300-48T",
            "target_profile": "arista_eos/DCS-7050SX-64",
        }).json()
        # What the sentence must not send an operator to: the same
        # two stanzas, and a status that says nothing of them.
        assert paired["rendered"].count("interface Vlan100\n") == 2
        assert (paired["status"], paired["port_mapping_plan"]["fused"]) == ("completed", {})

    def test_with_devices_the_plan_says_it(self, client: TestClient) -> None:
        """One account of one fact.  With both devices declared the
        plan carries the names, by that path's own rule, and the
        job's three fields stay empty."""
        fused = client.post("/api/v1/migration/plan", json=_models_body(
            port_rename_map={"50": "1/a1"},
        )).json()
        assert fused["port_mapping_plan"]["fused"] == {"1/A1": ["49", "50"]}
        assert (fused["fused_ports"], fused["unresolved_ports"]) == ({}, [])
        assert fused["untranslated_ports"] == []
        # A name the translator cannot read, with both devices
        # declared: the plan lists it as a name that is no port of
        # the declared source, and the job's own list stays empty.
        unread = client.post("/api/v1/migration/plan", json={
            "source": "cisco_iosxe_cli", "target": "arista_eos", "raw_text": _IOS_UNREAD,
            "source_profile": "cisco_iosxe/C9300-24P",
            "target_profile": "arista_eos/DCS-7050SX-64",
        }).json()
        assert unread["untranslated_ports"] == []
        assert unread["port_mapping_plan"]["unresolved_ports"] == ["GigabitEthernet1"]
        assert unread["status"] == "partial"
        body = _models_body()
        body["target_deployment"] = {
            "mode": "stacked",
            "members": [{"model": "JL320A", "modules": {"A": "JL083A"}}],
        }
        short = client.post("/api/v1/migration/plan", json=body).json()
        assert len(short["port_mapping_plan"]["unresolved_ports"]) == 24
        assert (short["fused_ports"], short["unresolved_ports"]) == ({}, [])
        assert short["error"].startswith("Port mapping is incomplete: ")
        assert "Port names are not settled" not in short["error"]

    def test_the_api_document_describes_each(self, client: TestClient) -> None:
        """A client is told what each field holds and how to settle
        it, where it reads the response schema."""
        schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]
        fields = schemas["MigrationJob"]["properties"]
        # The model's own description lists them too.
        for name in ("fused_ports", "unresolved_ports", "untranslated_ports"):
            assert f"{name}:" in schemas["MigrationJob"]["description"]
        for name, how in (
            ("fused_ports", "a name of their own in port_rename_map"),
            ("unresolved_ports", "a target name, or null to say it is to be dropped"),
            ("untranslated_ports", "its own name, if that is right there -- or null to drop it"),
        ):
            said = " ".join(fields[name]["description"].split())
            assert "the job is partial while it is not empty" in said, name
            assert how in said, name
            assert "Empty when both devices were declared" in said, name
        # Which of the names a pair of devices would decide.
        assert "only where a hardware port (source_ports) is among" in " ".join(
            fields["fused_ports"]["description"].split()
        )
        assert "a hardware port, or a logical name" in " ".join(
            fields["unresolved_ports"]["description"].split()
        )
        # Which names the translator left are no foreign name, and
        # so are not listed.
        left = " ".join(fields["untranslated_ports"]["description"].split())
        assert "between two codecs of one platform" in left
        assert "where the target itself writes that very name" in left
        assert "A hardware port is always listed" in left
        assert fields["fused_ports"]["type"] == "object"
        for name in ("unresolved_ports", "untranslated_ports"):
            assert (fields[name]["type"], fields[name]["items"]) == (
                "array", {"type": "string"},
            ), name
            assert "anyOf" not in fields[name], name
        # What the pipeline hands the translator's own list on by is
        # not a field of the job.
        assert not [name for name in fields if name.startswith("_")]


class TestForceOnEveryPlanEndpoint:
    """``force`` skips the guard that refuses a pair of codecs with no
    device class in common.  Every public codec has one in common
    with every other, so no request through the API shows the guard:
    what is held here is that each handler hands the flag on."""

    @pytest.mark.parametrize("force", [True, False])
    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_each_handler_hands_it_on(
        self, client: TestClient, monkeypatch, path: str, force: bool,
    ) -> None:
        from netcanon.api.routes import migration as routes

        seen: list[object] = []
        real = routes.run_translation

        def watched(request, body, source, target, raw_text, **overrides):
            seen.append(overrides.get("force", "not passed"))
            return real(request, body, source, target, raw_text, **overrides)

        monkeypatch.setattr(routes, "run_translation", watched)
        resp = client.post(f"/api/v1/migration{path}", json=_not_settled_body(force=force))
        assert resp.status_code == 200
        assert seen == [force], path


class TestABlankTarget:
    """A value of ``port_rename_map`` is a name or ``null``.  ``""``
    was written into the output as an interface with no name, and --
    being an entry -- cleared the ``partial`` a dropped port holds a
    job in.  So was a target that draws nothing: a zero-width
    space is not white space, and ``interface`` followed by one is
    an interface nobody can see the name of."""

    @pytest.mark.parametrize("declared", [False, True], ids=["no-devices", "devices"])
    @pytest.mark.parametrize(
        "blank",
        ["", "   ", "\t", "\u200b", "\u0000", "\ufeff\u2060", " \u200b\t\u00ad"],
        ids=[
            "empty", "spaces", "tab", "zero-width space", "nul",
            "byte-order mark and word joiner", "mixed",
        ],
    )
    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_it_is_a_422_on_every_plan_endpoint(
        self, client: TestClient, path: str, blank: str, declared: bool,
    ) -> None:
        body = _models_body() if declared else {
            "source": "cisco_nxos", "target": "cisco_iosxe_cli", "raw_text": _NXOS_WITH_MGMT,
        }
        body["port_rename_map"] = {"mgmt0": blank, "Ethernet1/1": "GigabitEthernet1/0/9"}
        resp = client.post(f"/api/v1/migration{path}", json=body)
        assert resp.status_code == 422, path
        (error,) = resp.json()["detail"]
        assert error["loc"] == ["body", "port_rename_map"], path
        assert error["msg"] == (
            "Value error, a target name in port_rename_map must not be blank "
            "('mgmt0'): give the port a name, or null to drop it"
        ), path
        # The refusal echoes the map, never the pasted config.
        assert "hostname" not in resp.text, path

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_null_and_a_name_are_what_it_takes(self, client: TestClient, path: str) -> None:
        body = {"source": "cisco_nxos", "target": "cisco_iosxe_cli", "raw_text": _NXOS_WITH_MGMT}
        plain = client.post(f"/api/v1/migration{path}", json=body).json()
        assert (plain["status"], plain["unresolved_ports"]) == ("partial", ["mgmt0"]), path
        for entry in (None, "GigabitEthernet0/0"):
            resp = client.post(
                f"/api/v1/migration{path}", json={**body, "port_rename_map": {"mgmt0": entry}},
            )
            assert resp.status_code == 200, (path, entry)
            job = resp.json()
            assert (job["status"], job["unresolved_ports"]) == ("completed", []), (path, entry)
            assert "interface \n" not in job["rendered"], (path, entry)

    def test_several_are_named_a_few_at_a_time(self, client: TestClient) -> None:
        body = {
            "source": "cisco_nxos", "target": "cisco_iosxe_cli", "raw_text": _NXOS_WITH_MGMT,
            "port_rename_map": {f"p{n}": "" for n in range(8)} | {"x" * 90: " "},
        }
        (error,) = client.post("/api/v1/migration/plan", json=body).json()["detail"]
        assert error["msg"] == (
            "Value error, a target name in port_rename_map must not be blank "
            "('p0', 'p1', 'p2', 'p3', 'p4' and 4 more): give the port a name, "
            "or null to drop it"
        )

    def test_a_long_key_is_cut_short(self, client: TestClient) -> None:
        """The message is not to grow with what was sent: a key is
        named by its first characters."""
        body = {
            "source": "cisco_nxos", "target": "cisco_iosxe_cli", "raw_text": _NXOS_WITH_MGMT,
            "port_rename_map": {"k" * 5000: "", "m" * 61: " ", "n" * 60: ""},
        }
        (error,) = client.post("/api/v1/migration/plan", json=body).json()["detail"]
        assert error["msg"] == (
            "Value error, a target name in port_rename_map must not be blank "
            f"('{'k' * 57}...', '{'m' * 57}...', '{'n' * 60}'): give the port a "
            "name, or null to drop it"
        )

    @pytest.mark.parametrize("path", _PLAN_PATHS)
    def test_one_such_character_in_a_name(
        self, client: TestClient, path: str,
    ) -> None:
        """Only a target with NOTHING drawn is refused.  What else a
        name may hold is the target platform's business."""
        body = {
            "source": "cisco_nxos", "target": "cisco_iosxe_cli", "raw_text": _NXOS_WITH_MGMT,
            "port_rename_map": {"mgmt0": "\u200bGigabitEthernet0/0"},
        }
        resp = client.post(f"/api/v1/migration{path}", json=body)
        assert resp.status_code == 200, path
        assert resp.json()["unresolved_ports"] == [], path

    def test_the_other_maps_are_not_asked_this(self, client: TestClient) -> None:
        """The check is the port map's: a blank target there named an
        interface.  What a blank user name or community does is each
        of those panes' own business, as it was."""
        body = {
            "source": "cisco_nxos", "target": "cisco_iosxe_cli", "raw_text": _NXOS_WITH_MGMT,
            "local_user_rename_map": {"admin": ""}, "port_rename_map": {"mgmt0": None},
        }
        assert client.post("/api/v1/migration/plan", json=body).status_code == 200


# ---------------------------------------------------------------------------
# A stack on both sides
# ---------------------------------------------------------------------------

#: A two-member VSF fabric of 2930F-48G-4SFP.  Not a capture: no
#: committed capture names a port of a second member.  The names are
#: the ones the family's VSF mode gives.  The two members carry
#: different VLANs, so that one written under the other's names shows.
_VSF_FABRIC = """; hpStack_WC Configuration Editor; Created on release #WC.16.07.0002
hostname "fabric"
trunk 1/49,2/49 trk1 lacp
interface 2/1
   name "desk-b"
   exit
vlan 1
   name "DEFAULT_VLAN"
   no untagged 1/1-1/10,2/1-2/30
   untagged 1/11-1/48,1/50,2/31-2/48,2/50
   tagged Trk1
   exit
vlan 10
   name "users"
   untagged 1/1-1/10,2/1-2/4
   tagged Trk1,2/50
   exit
vlan 20
   name "voice"
   untagged 2/5-2/30
   tagged Trk1,1/50
   exit
"""


def _fabric(*ids: int) -> dict:
    return {"mode": "vsf", "members": [{"model": "JL260A", "id": n} for n in ids]}


def _stack(*ids: int) -> dict:
    return {
        "mode": "stacked",
        "members": [{"model": "JL322A", "id": n, "modules": {"A": "JL083A"}} for n in ids],
    }


def _stack_body(source: dict, target: dict, raw_text: str = _VSF_FABRIC, **extra) -> dict:
    return {
        "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": raw_text,
        "source_deployment": source, "target_deployment": target, **extra,
    }


class TestAStackOnBothSides:
    """More than one member in ``source_deployment`` AND in
    ``target_deployment``: the members pair in the order the two lists
    give them."""

    def test_each_member_lands_on_the_member_in_its_position(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/migration/plan", json=_stack_body(_fabric(1, 2), _stack(1, 2)),
        )
        assert resp.status_code == 200
        assert resp.headers["X-Netcanon-Job-Status"] == "completed"
        job = resp.json()
        plan = job["port_mapping_plan"]
        assert {k: v for k, v in job["port_renames"].items() if "/" in k} == {
            "1/49": "1/A1", "1/50": "1/A2", "2/49": "2/A1", "2/50": "2/A2",
        }
        assert "trunk 1/A1,2/A1 trk1 lacp" in job["rendered"]
        assert [(m["rank"], m["member_id"]) for m in plan["source"]["members"]] == [(0, 1), (1, 2)]
        assert [(m["rank"], m["member_id"]) for m in plan["target"]["members"]] == [(0, 1), (1, 2)]
        assert (plan["source"]["port_count"], plan["target"]["port_count"]) == (104, 104)
        second = next(p for p in plan["pairings"] if p["source"] == "2/49")
        assert (second["target"], second["role"], second["member_rank"], second["position"]) == (
            "2/A1", "uplink", 1, 0,
        )
        assert plan["unplaced"] == [] and plan["unresolved_ports"] == []
        assert not [w for w in job["warnings"] if w.startswith("port mapping:")]

    def test_a_member_with_another_number_is_said(self, client: TestClient) -> None:
        """Members 1 and 3 of the fabric onto members 1 and 2 of the
        stack: the second listed goes to the second listed."""
        raw = _VSF_FABRIC.replace("2/", "3/")
        job = client.post(
            "/api/v1/migration/plan", json=_stack_body(_fabric(1, 3), _stack(1, 2), raw),
        ).json()
        assert job["status"] == "completed"
        assert job["port_renames"]["3/1"] == "2/1"
        assert job["port_renames"]["3/49"] == "2/A1"
        assert "1/1" not in job["port_renames"]
        assert "interface 2/1" in job["rendered"] and "3/" not in job["rendered"]
        (line,) = [w for w in job["warnings"] if w.startswith("port mapping:")]
        assert line.endswith("source member 3 with target member 2")

    def test_the_order_of_the_list_is_the_order_of_the_pairing(self, client: TestClient) -> None:
        job = client.post(
            "/api/v1/migration/plan", json=_stack_body(_fabric(2, 1), _stack(1, 2)),
        ).json()
        assert job["status"] == "completed"
        assert (job["port_renames"]["2/1"], job["port_renames"]["1/1"]) == ("1/1", "2/1")
        lines = [line.strip() for line in job["rendered"].splitlines()]
        assert lines[lines.index("interface 1/1") + 1] == 'name "desk-b"'
        # Each member's number is declared on the other side too: that
        # is a crossing, said with what to do about it, and it holds
        # no job.
        (line,) = [w for w in job["warnings"] if w.startswith("port mapping:")]
        assert "2 stack member(s) are paired with a member of ANOTHER number" in line
        assert (
            "(source member 2 with target member 1; source member 1 with target member 2)" in line
        )
        assert line.endswith("give them the same place in both lists")

    def test_a_member_the_target_does_not_have_is_dropped_and_said(
        self, client: TestClient,
    ) -> None:
        resp = client.post(
            "/api/v1/migration/plan", json=_stack_body(_fabric(1, 2), _stack(1)),
        )
        assert resp.headers["X-Netcanon-Job-Status"] == "partial"
        job = resp.json()
        plan = job["port_mapping_plan"]
        assert len(job["port_drops"]) == 50
        assert {name.partition("/")[0] for name in job["port_drops"]} == {"2"}
        assert {(p["reason"], p["dropped"], p["member_rank"])
                for p in plan["unplaced"] if p["used"]} == {("no-member", True, 1)}
        assert plan["unresolved_ports"] == sorted(job["port_drops"])
        assert [name.lower() for name in plan["shrunk_lags"]] == ["trk1"]
        assert "trunk 1/A1 trk1 lacp" in job["rendered"]
        assert any("no target member in its position" in w for w in job["warnings"])
        assert "Port mapping is incomplete: 50 name(s)" in job["error"]

    @pytest.mark.parametrize(
        "path",
        ["/plan", "/plan/ports", "/plan/vlans", "/plan/local_users",
         "/plan/snmp", "/plan/snmpv3", "/render"],
    )
    def test_on_every_plan_endpoint(self, client: TestClient, path: str) -> None:
        job = client.post(
            f"/api/v1/migration{path}", json=_stack_body(_fabric(1, 3), _stack(1, 2),
                                                         _VSF_FABRIC.replace("2/", "3/")),
        ).json()
        assert job["port_renames"]["3/49"] == "2/A1", path
        assert job["port_mapping_plan"]["applied"] is True, path

    def test_an_inventory_lists_every_member_in_the_order_declared(
        self, client: TestClient,
    ) -> None:
        inventory = client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss", "deployment": _stack(2, 1),
        }).json()
        names = [port["name"] for port in inventory["ports"]]
        assert len(names) == 104
        assert (names[0], names[51], names[52], names[103]) == ("2/1", "2/A4", "1/1", "1/A4")
        assert [(m["rank"], m["member_id"]) for m in inventory["members"]] == [(0, 2), (1, 1)]

    def test_the_api_document_says_how_to_number_and_order_members(
        self, client: TestClient,
    ) -> None:
        """An API client reads the OpenAPI document, not a docstring:
        how a member is given its number, and that the order of the
        list is the order of the pairing, are in it."""
        schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]
        number = schemas["MemberSpec"]["properties"]["id"]["description"]
        assert "member number" in number and "Omitted" in number
        order = schemas["DeploymentSpec"]["properties"]["members"]["description"]
        assert "in list order" in order and "whatever their member numbers" in order
        assert "states its number with ``id``" in schemas["DeploymentSpec"]["description"]

    def test_a_member_number_declared_twice_is_a_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/migration/plan", json=_stack_body(_fabric(1, 2), _stack(2, 2)),
        )
        assert resp.status_code == 422
        assert "member id 2 is declared twice" in json.dumps(resp.json())


# ---------------------------------------------------------------------------
# Reading the source device from the config
# ---------------------------------------------------------------------------

#: A real one-member 2930M stack: JL323A with a JL083A.
CAPTURE_2930M = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg"
).read_text(encoding="utf-8")


class TestDetectDeployment:
    URL = "/api/v1/migration/detect-deployment"

    def test_a_standalone_switch_is_read_from_its_banner(self, client: TestClient) -> None:
        resp = client.post(self.URL, json={"source": "aruba_aoss", "raw_text": CAPTURE_2930F})
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["stated"] is True
        assert proposal["deployment"] == SOURCE_2930F | {
            "members": [{"model": "2930F-48G-4SFP", "id": None, "modules": {}}],
        }
        assert (proposal["family"], proposal["mode"]) == ("aruba_aoss/2930F", "standalone")
        assert proposal["evidence"] == [
            "; JL260A Configuration Editor", "module 1 type jl260a",
        ]
        assert (proposal["consistent"], proposal["missing_ports"]) == (True, [])
        assert proposal["inventory"]["port_count"] == 52

    def test_text_nobody_vouches_for_is_answered_not_refused(self, client: TestClient) -> None:
        """More members than a declaration may list, a part no device
        prints, a member number of thousands of digits: each was a 500.
        Each is a 200 that says no deployment could be proposed."""
        banner = "; hpStack_WC Configuration Editor; Created on release #WC.16.07.0003\n"
        # Each with the note that says what stood in the way: a body
        # that is answered, but by a layer further down than the one
        # meant to answer it, gets a different note.
        bodies = [
            (
                banner + "stacking\n" + "".join(
                    f'   member {n} type "JL322A"\n' for n in range(1, 66)
                ) + "   exit\n",
                "a deployment lists at most 64",
            ),
            (
                banner + 'stacking\n   member 1 type "' + "J" * 200 + '"\n   exit\n',
                "no line in it names a member",
            ),
            (
                banner + "stacking\n   member " + "9" * 5000 + ' type "JL322A"\n   exit\n',
                "no line in it names a member",
            ),
            (
                banner + "stacking\n   member" + " " * 400_000 + '1 type "JL322A"\n   exit\n',
                "names no port",
            ),
        ]
        for raw, said in bodies:
            # Well under a second each; the pattern this replaced took
            # over a minute on the last of them.  One slow reading is
            # the machine; a second, or one several times over, is not.
            for _ in range(2):
                started = time.perf_counter()
                resp = client.post(
                    "/api/v1/migration/detect-deployment", json={"source": "aruba_aoss", "raw_text": raw},
                )
                took = time.perf_counter() - started
                if not 15.0 <= took < 60.0:
                    break
            assert took < 15.0, said
            assert resp.status_code == 200, said
            proposal = resp.json()
            assert proposal["consistent"] is None
            assert [n for n in proposal["notes"] if said in n], (said, proposal["notes"])
            if proposal["deployment"] is None:
                # The first note is the reason.
                assert said in proposal["notes"][0], proposal["notes"]
            assert len(resp.content) < 20_000

    def test_what_comes_back_does_not_grow_with_what_was_sent(self, client: TestClient) -> None:
        """A megabyte of lines that state nothing readable.  Each was
        once answered with most of a megabyte: an id, a part or every
        member number it found, handed back."""
        banner = "; hpStack_WC Configuration Editor; Created on release #WC.16.07.0003\n"
        top = "; JL322A Configuration Editor; Created on release #WC.16.07.0003\nmodule 1 type jl322a\n"
        bodies = [
            ("; hpStack_" + "x" * 100_000 + " Configuration Editor\n", "does not say which device"),
            (
                banner + "vsf\n" + "".join(f"   member {n}\n" for n in range(100_000)) + "   exit\n",
                "no line in it names a member",
            ),
            (
                banner + 'stacking\n   member 1 type "JL322A"\n' + "".join(
                    f"   member {n} flexible-module A type JL083A\n" for n in range(2, 50_002)
                ) + "   exit\n",
                "A member line shows",
            ),
            (top + "flexible-module A type " + "J" * 100_000 + "\n", "could not be read as a module"),
            (top.replace("jl322a", "j" * 100_000), "could not be read as the chassis line"),
        ]
        for raw, first in bodies:
            resp = client.post(self.URL, json={"source": "aruba_aoss", "raw_text": raw})
            assert resp.status_code == 200, first
            assert first in resp.json()["notes"][0], (first, resp.json()["notes"])
            assert len(resp.content) < 8_000, (first, len(resp.content))

    def test_text_the_parser_refuses_is_answered_unchecked(self, client: TestClient) -> None:
        """A paste that begins like JSON and then states a device: the
        AOS-S parser refuses it.  That is the third way ``consistent``
        is ``null``, and it is an answer."""
        raw = (
            '{"a": 1}\n; JL322A Configuration Editor; Created on release #WC.16.07.0003\n'
            "module 1 type jl322a\nvlan 1\n   untagged 1-4\n   exit\n"
        )
        resp = client.post(self.URL, json={"source": "aruba_aoss", "raw_text": raw})
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["deployment"] is not None and proposal["consistent"] is None
        assert proposal["notes"][-1].startswith("The config could not be parsed")

    def test_a_paste_that_names_no_port_is_not_called_consistent(self, client: TestClient) -> None:
        proposal = client.post("/api/v1/migration/detect-deployment", json={
            "source": "aruba_aoss",
            "raw_text": "; JL322A Configuration Editor; Created on release #WC.16.07.0003\n"
                        'hostname "sw"\nmodule 1 type jl322a\n',
        }).json()
        assert proposal["deployment"] is not None
        assert proposal["consistent"] is None and proposal["used_port_count"] == 0
        assert proposal["missing_port_count"] == 0

    def test_a_stack_is_read_from_its_stanza(self, client: TestClient) -> None:
        proposal = client.post(
            self.URL, json={"source": "aruba_aoss", "raw_text": CAPTURE_2930M},
        ).json()
        assert proposal["fabric"] == "stacking"
        assert proposal["deployment"] == {
            "mode": "stacked",
            "members": [
                {"model": "2930M-40G-8SR-PoEP", "id": 1, "modules": {"A": "JL083A"}},
            ],
        }
        # What the lines can and cannot show is part of the answer.
        assert any("provisioned for" in note for note in proposal["notes"])
        # A MAC address identifies one device and is not echoed back.
        assert "mac-address" not in resp_text(proposal)

    def test_the_proposal_is_accepted_as_a_source_deployment(self, client: TestClient) -> None:
        """The point of the endpoint: what it returns goes straight
        back in as ``source_deployment``."""
        proposal = client.post(
            self.URL, json={"source": "aruba_aoss", "raw_text": CAPTURE_2930F},
        ).json()
        job = client.post("/api/v1/migration/plan", json=_plan_body(
            source_deployment=proposal["deployment"], target_deployment=TARGET_2930M,
        )).json()
        assert job["status"] == "completed"
        assert job["port_renames"]["49"] == "1/A1"

    def test_a_device_no_family_describes_is_an_answer_not_an_error(
        self, client: TestClient,
    ) -> None:
        raw = (
            REPO_ROOT / "tests/fixtures/real/aruba_aoss/hpe_community_2920_wb1608_dhcp_snooping.cfg"
        ).read_text(encoding="utf-8")
        resp = client.post(self.URL, json={"source": "aruba_aoss", "raw_text": raw})
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["stated"] is True
        assert proposal["deployment"] is None and proposal["consistent"] is None
        assert proposal["unknown_parts"] == ["J9729A"]

    def test_a_catalyst_is_read_from_its_provision_line(self, client: TestClient) -> None:
        raw = (
            REPO_ROOT / "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
        ).read_text(encoding="utf-8")
        resp = client.post(self.URL, json={"source": "cisco_iosxe_cli", "raw_text": raw})
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["fabric"] == "switch"
        assert proposal["evidence"] == ["switch 1 provision c9300-24ux"]
        assert proposal["deployment"] == {
            "mode": "stack", "members": [{"model": "C9300-24UX", "id": 1, "modules": {}}],
        }
        # The capture names the ports of every module the bay takes,
        # and the config does not say which is fitted.
        assert proposal["consistent"] is False
        assert "TenGigabitEthernet1/1/1" in proposal["missing_ports"]
        assert any("module bay empty" in note for note in proposal["notes"])

    def test_a_vendor_without_a_detector_says_so(self, client: TestClient) -> None:
        resp = client.post(self.URL, json={
            "source": "arista_eos", "raw_text": "hostname sw\n",
        })
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["stated"] is False and proposal["deployment"] is None
        assert "No detector" in proposal["notes"][0]

    def test_a_stored_config_can_be_read_too(self, client: TestClient, test_settings) -> None:
        """``source_filename`` names a config in the backup store, as on
        a plan request.  The stored file is a stacked capture, so the
        answer shows its TEXT was read: a file found and then ignored
        would say the config states no device."""
        filename = "Aruba_192.0.2.9_20260101_000000.cfg"
        (test_settings.configs_dir / filename).write_text(CAPTURE_2930M, encoding="utf-8")
        assert filename in [entry["filename"] for entry in client.get("/api/v1/configs/").json()]
        resp = client.post(self.URL, json={"source": "aruba_aoss", "source_filename": filename})
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["fabric"] == "stacking" and proposal["consistent"] is True
        assert proposal["deployment"]["members"] == [
            {"model": "2930M-40G-8SR-PoEP", "id": 1, "modules": {"A": "JL083A"}},
        ]

    def test_a_stored_config_that_states_no_device(self, client: TestClient) -> None:
        """What the backup route stored, read back: the fake collector's
        Cisco snippet states no AOS-S device."""
        client.post("/api/v1/backups", json={"devices": [{
            "type_key": "Cisco", "host": "10.77.77.77",
            "credentials": {"username": "admin", "password": "x"},
        }]})
        filename = client.get("/api/v1/configs/").json()[0]["filename"]
        resp = client.post(self.URL, json={
            "source": "aruba_aoss", "source_filename": filename,
        })
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["stated"] is False
        assert "does not say which device" in proposal["notes"][0]

    @pytest.mark.parametrize(
        ("body", "status", "needle"),
        [
            ({"source": "aruba_aoss"}, 422, "Exactly one of"),
            ({"source": "aruba_aoss", "raw_text": "x", "source_filename": "y"}, 422,
             "Exactly one of"),
            ({"source": "no-such-codec", "raw_text": "x"}, 422, "unknown source adapter"),
            ({"source": "aruba_aoss", "source_filename": "missing.cfg"}, 404, "not found"),
        ],
    )
    def test_request_errors(
        self, client: TestClient, body: dict, status: int, needle: str,
    ) -> None:
        resp = client.post(self.URL, json=body)
        assert resp.status_code == status
        assert needle in resp.json()["detail"]


def resp_text(payload: object) -> str:
    import json

    return json.dumps(payload)
