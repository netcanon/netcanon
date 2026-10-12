"""A config that asks for more than the server is set to take is REFUSED, in words.

A refusal is a result.  On each surface that takes config text it has
to say what was large, how large, and the limit -- and never read as
"could not be parsed", which is what a wrong vendor gets:

* the seven endpoints that return a job, with the devices declared and
  without: HTTP 200, a ``failed`` job, ``refusal`` set, an ``error``
  that begins ``refused:``;
* the sanitiser: HTTP 413, the status an upload over the byte cap gets;
* ``detect-deployment``: the proposal, and a note that says why it was
  not checked against the port names;
* ``detect``: under the server's limits, like everything that reads
  config text.

And three things about all of them: the server's setting decides
(``small`` refuses what ``standard`` translates, and says whose limit
it is), a config within the limits is untouched by them, and what a
refusal quotes from the config goes to the client and never to a log.

The texts are small on purpose: a few hundred bytes to a few tens of
kilobytes.  What each expands to is the point.

The mechanism itself is tested in ``tests/unit/migration/test_limits.py``.
"""

from __future__ import annotations

import inspect
import io
import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from fastapi import UploadFile
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from netcanon.config import Settings
from netcanon.main import create_app
from netcanon.migration import limits as L

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A real standalone Aruba 2930F-48G-4SFP (JL260A), which states its device.
CAPTURE_2930F = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
).read_text(encoding="utf-8")
SOURCE_2930F = {"mode": "standalone", "members": [{"model": "JL260A"}]}
TARGET_2930M = {"mode": "stacked", "members": [{"model": "JL322A", "modules": {"A": "JL083A"}}]}

#: One AOS-S stanza of 40 ranges of 1,001 ports: 520 bytes that name
#: 40,040 ports.  (The measured text is 800 ranges; 40 is past any
#: device, and a tree that did not refuse it would spend 75 MB on it
#: and not a gigabyte and a half.)
RANGES = "vlan 3999\n   name \"wide\"\n   tagged " + ",".join(
    f"{n * 2000 + 1}-{n * 2000 + 1001}" for n in range(40)
) + "\n   exit\n"
AOSS_RANGES = 'hostname "T"\n' + RANGES
#: The last range the parser reads before it refuses, as the config wrote it.
QUOTED = "16001-17001"

JOB_ENDPOINTS = ("/plan", "/plan/ports", "/plan/vlans", "/plan/local_users", "/plan/snmp", "/plan/snmpv3", "/render")


def trunk_all(ports: int, vlans: int) -> str:
    """NX-OS: *ports* trunks that allow every VLAN, *vlans* declared VLANs."""
    out = ["hostname T", ""]
    for vid in range(2, 2 + vlans):
        out += [f"vlan {vid}", f"  name V{vid}"]
    for port in range(ports):
        out += [f"interface Ethernet{port // 48 + 1}/{port % 48 + 1}", "  switchport",
                "  switchport mode trunk", "  switchport trunk allowed vlan all"]
    return "\n".join(out) + "\n"


def _client(settings: Settings, limits: str) -> TestClient:
    return TestClient(create_app(settings.model_copy(update={"config_limits": limits})))


@pytest.fixture()
def client(test_settings: Settings):
    """The server as it runs by default."""
    with _client(test_settings, "standard") as c:
        yield c


@pytest.fixture()
def small_client(test_settings: Settings):
    """The server as the public demo runs it."""
    with _client(test_settings, "small") as c:
        yield c


def _refused(job: dict[str, Any], limit: str, profile: str = "standard") -> None:
    assert job["status"] == "failed", job["status"]
    assert job["rendered"] is None and job["validation"] is None
    refusal = job["refusal"]
    assert refusal is not None, job["error"]
    assert (refusal["limit"], refusal["profile"]) == (limit, profile)
    error = job["error"]
    # Not the beginning the migrate page reads as "the wrong vendor?".
    assert error.startswith("refused: ") and not error.startswith("parse failed")
    # What was large, how large, the limit.
    assert refusal["what"] in error
    assert f"{int(refusal['asked']):,}" in error
    assert f"the limit is {int(refusal['cap']):,}" in error
    assert error.endswith(refusal["how_to_raise"])


# ---------------------------------------------------------------------------
# The endpoints that return a job
# ---------------------------------------------------------------------------


class TestEveryJobEndpoint:
    @pytest.mark.parametrize("path", JOB_ENDPOINTS)
    def test_a_line_of_port_ranges_is_refused(self, client: TestClient, path: str) -> None:
        resp = client.post(f"/api/v1/migration{path}", json={
            "source": "aruba_aoss", "target": "cisco_iosxe_cli", "raw_text": AOSS_RANGES,
        })
        assert resp.status_code == 200
        assert resp.headers["X-Netcanon-Job-Status"] == "failed"
        job = resp.json()
        _refused(job, "ports")
        assert (job["refusal"]["asked"], job["refusal"]["cap"], job["refusal"]["exact"]) == (9009, 8192, False)
        assert (job["refusal"]["stage"], job["refusal"]["codec"]) == ("parse", "aruba_aoss")
        assert "NETCANON_CONFIG_LIMITS=large" in job["error"] and "Preferences..." in job["error"]
        assert len(resp.content) < 10_000, "the answer to 'too large' is small"

    @pytest.mark.parametrize("path", JOB_ENDPOINTS)
    def test_and_with_both_devices_declared(self, client: TestClient, path: str) -> None:
        """The path that pairs ports by position parses the source by
        itself before the pipeline does, and reads the output back:
        the refusal has to come out of it as the same job."""
        resp = client.post(f"/api/v1/migration{path}", json={
            "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": CAPTURE_2930F + RANGES,
            "source_deployment": SOURCE_2930F, "target_deployment": TARGET_2930M,
        })
        assert resp.status_code == 200
        assert resp.headers["X-Netcanon-Job-Status"] == "failed"
        job = resp.json()
        _refused(job, "ports")
        assert job["port_mapping_plan"] is None
        assert len(resp.content) < 10_000

    def test_the_capture_itself_is_translated(self, client: TestClient) -> None:
        job = client.post("/api/v1/migration/plan", json={
            "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": CAPTURE_2930F,
            "source_deployment": SOURCE_2930F, "target_deployment": TARGET_2930M,
        }).json()
        assert job["refusal"] is None and job["rendered"] and job["port_mapping_plan"]["applied"] is True

    def test_a_refusal_at_render_drops_the_report(self, small_client: TestClient) -> None:
        """Refused at render, a job has been validated: a path for
        every membership, megabytes about a config that was not
        translated.  The report is not sent."""
        odd = ",".join(str(vid) for vid in range(1, 4094, 2))
        text = "hostname T\n!\n" + "".join(
            f"interface Ethernet{n}\n   switchport mode trunk\n   switchport trunk allowed vlan {odd}\n!\n"
            for n in range(1, 61)
        )
        resp = small_client.post("/api/v1/migration/plan", json={
            "source": "arista_eos", "target": "juniper_junos", "raw_text": text,
        })
        job = resp.json()
        _refused(job, "text", "small")
        assert (job["refusal"]["stage"], job["refusal"]["codec"], job["refusal"]["exact"]) == (
            "render", "juniper_junos", False,
        )
        assert len(resp.content) < 100_000


class TestTheServersSettingDecides:
    def test_small_refuses_what_standard_takes(
        self, client: TestClient, small_client: TestClient,
    ) -> None:
        """240 trunks that allow every VLAN and 500 VLANs: 120,000
        memberships, where the demo's limit is 50,000."""
        body = {"source": "cisco_nxos", "target": "aruba_aoss", "raw_text": trunk_all(240, 500)}
        assert client.post("/api/v1/migration/plan", json=body).json()["refusal"] is None
        job = small_client.post("/api/v1/migration/plan", json=body).json()
        _refused(job, "memberships", "small")
        assert "(at: 240 trunks that allow every VLAN x 500 VLANs)" in job["error"]

    def test_the_demo_limit_names_no_setting(self, small_client: TestClient) -> None:
        """A visitor to the public demo cannot set an environment
        variable: on every surface the sentence says whose limit it is
        and what a Netcanon of one's own allows."""
        job = small_client.post("/api/v1/migration/plan", json={
            "source": "aruba_aoss", "target": "cisco_iosxe_cli", "raw_text": AOSS_RANGES,
        }).json()
        sanitised = small_client.post(
            "/api/v1/sanitize", data={"source_vendor": "aruba_aoss"},
            files={"config": ("c.cfg", AOSS_RANGES.encode(), "text/plain")},
        )
        proposed = small_client.post("/api/v1/migration/detect-deployment", json={
            "source": "aruba_aoss", "raw_text": CAPTURE_2930F + RANGES,
        }).json()
        assert sanitised.status_code == 413
        for said in (job["error"], sanitised.json()["detail"], proposed["notes"][-1]):
            assert "the one the public demo uses" in said, said
            assert "A Netcanon you run yourself allows 8,192 by default." in said, said
            for word in ("NETCANON_", "environment", "Preferences", "--limits"):
                assert word not in said, said

    def test_a_config_within_the_limits_is_untouched(
        self, client: TestClient, small_client: TestClient,
    ) -> None:
        body = {"source": "cisco_nxos", "target": "juniper_junos", "raw_text": trunk_all(48, 20)}
        a = client.post("/api/v1/migration/plan", json=body).json()
        b = small_client.post("/api/v1/migration/plan", json=body).json()
        assert a["status"] == b["status"] == "completed"
        assert a["rendered"] == b["rendered"] and "vlan members all" in a["rendered"]
        assert a["refusal"] is None and b["refusal"] is None

    def test_an_unknown_value_stops_the_server(self, test_settings: Settings) -> None:
        """Not read as "no limit", and not as the default either."""
        with pytest.raises(ValueError, match="config_limits"):
            Settings(configs_dir=test_settings.configs_dir, config_limits="unlimitted")

    def test_the_setting_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch, test_settings: Settings,
    ) -> None:
        assert Settings(configs_dir=test_settings.configs_dir).config_limits == "standard"
        monkeypatch.setenv("NETCANON_CONFIG_LIMITS", " Small ")
        assert Settings(configs_dir=test_settings.configs_dir).config_limits == "small"
        monkeypatch.setenv("NETCANON_CONFIG_LIMITS", "none")
        with pytest.raises(ValueError, match="config_limits"):
            Settings(configs_dir=test_settings.configs_dir)

    def test_the_server_logs_the_limits_in_force(
        self, test_settings: Settings, caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="netcanon.main"), _client(test_settings, "small"):
            pass
        (line,) = [record.getMessage() for record in caplog.records if "Config limits in force" in record.getMessage()]
        assert line == "Config limits in force: " + L.describe(L.SMALL)
        assert "memberships 50,000" in line and "seconds 20" in line


# ---------------------------------------------------------------------------
# The sanitiser, and reading the device out of a config
# ---------------------------------------------------------------------------


class TestTheOtherSurfaces:
    def test_the_sanitiser_answers_413(self, client: TestClient) -> None:
        for dry_run in ("false", "true"):
            resp = client.post(
                "/api/v1/sanitize", data={"source_vendor": "aruba_aoss", "dry_run": dry_run},
                files={"config": ("c.cfg", AOSS_RANGES.encode(), "text/plain")},
            )
            assert resp.status_code == 413
            detail = resp.json()["detail"]
            assert detail.startswith(
                "Refused: reading the config as aruba_aoss would make 9,009 or more different ports named by "
                "port ranges; the limit is 8,192"
            )
            assert "NETCANON_CONFIG_LIMITS=large" in detail
            # Not the net for a crash, and not a failure to parse.
            assert "unexpectedly" not in detail and "Failed to parse" not in detail

    def test_the_sanitiser_still_sanitises(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/sanitize", data={"source_vendor": "aruba_aoss"},
            files={"config": ("c.cfg", CAPTURE_2930F.encode(), "text/plain")},
        )
        assert resp.status_code == 200 and int(resp.headers["X-Netcanon-Substitution-Count"]) > 0

    def test_detect_deployment_says_why_unchecked(self, client: TestClient) -> None:
        """The proposal is read from the hardware lines, by bounded
        patterns: it is still made.  The check of it against the port
        names needs the parse, which is refused -- and the note says
        that, not "could not be parsed"."""
        whole = client.post("/api/v1/migration/detect-deployment", json={
            "source": "aruba_aoss", "raw_text": CAPTURE_2930F,
        }).json()
        assert whole["consistent"] is True and whole["deployment"]["members"][0]["model"]
        resp = client.post("/api/v1/migration/detect-deployment", json={
            "source": "aruba_aoss", "raw_text": CAPTURE_2930F + RANGES,
        })
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["deployment"] == whole["deployment"]
        assert proposal["consistent"] is None and proposal["missing_port_count"] == 0
        assert proposal["notes"][-1].startswith(
            "The proposal was not checked against the port names the config uses: reading the config as "
            "aruba_aoss would make 9,009 or more different ports named by port ranges; the limit is 8,192"
        )
        assert not [note for note in proposal["notes"] if "could not be parsed" in note]

    def test_a_detector_out_of_time_says_so(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reading the hardware lines is a loop over the lines of the
        config, under the request's deadline.  Out of time is said in
        the first note, as the reason nothing is proposed -- and is
        not "could not be read", which is for a text no detector can
        follow."""
        from netcanon.migration import deployment_detect

        def out_of_time(raw_text: str):
            raise L.LimitExceeded("seconds", 121.0, 120.0, exact=True, profile="standard", hint="(hint)")

        monkeypatch.setattr(deployment_detect, "_detectors", lambda: {"aruba_aoss": out_of_time})
        resp = client.post("/api/v1/migration/detect-deployment", json={
            "source": "aruba_aoss", "raw_text": CAPTURE_2930F,
        })
        assert resp.status_code == 200
        proposal = resp.json()
        assert proposal["deployment"] is None and proposal["consistent"] is None
        assert proposal["notes"] == [
            "The hardware lines were not read: the request passed the 120 seconds it may take, and was "
            "stopped.  (hint)  Declare the device yourself."
        ]

    def test_detect_answers_as_it_did(self, client: TestClient) -> None:
        resp = client.post("/api/v1/migration/detect", json={"raw_text": CAPTURE_2930F + RANGES})
        assert resp.status_code == 200
        assert resp.json()[0]["codec"] == "aruba_aoss"

    def test_detect_out_of_time_is_an_answer(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """A probe reads a bounded window and makes nothing, so time
        is the one limit detection can meet.  It is an answer in
        words, and not an empty list -- which would say "no codec
        knows this text"."""
        from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

        def out_of_time(cls, raw_prefix):
            raise L.LimitExceeded("seconds", 121.0, 120.0, exact=True, profile="standard", hint="(hint)")

        monkeypatch.setattr(ArubaAOSSCodec, "probe", classmethod(out_of_time))
        resp = client.post("/api/v1/migration/detect", json={"raw_text": "hostname x\n"})
        assert resp.status_code == 413
        assert resp.json()["detail"].startswith("Refused: the request passed the 120 seconds it may take")


# ---------------------------------------------------------------------------
# What a refusal quotes goes to the client, and never to a log
# ---------------------------------------------------------------------------


class TestNothingOfTheConfigIsLogged:
    def test_the_log_line_of_a_refusal_quotes_nothing(
        self, client: TestClient, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The sentence quotes the config -- the range that passed the
        limit, a port name.  That is for whoever sent it.  A log line
        says which limit, of which limits, and how many."""
        with caplog.at_level(logging.DEBUG):
            job = client.post("/api/v1/migration/plan", json={
                "source": "aruba_aoss", "target": "cisco_iosxe_cli", "raw_text": AOSS_RANGES,
            }).json()
            for path, body in (
                ("/plan", {"source": "aruba_aoss", "target": "aruba_aoss", "raw_text": CAPTURE_2930F + RANGES,
                           "source_deployment": SOURCE_2930F, "target_deployment": TARGET_2930M}),
                ("/detect-deployment", {"source": "aruba_aoss", "raw_text": CAPTURE_2930F + RANGES}),
            ):
                assert client.post(f"/api/v1/migration{path}", json=body).status_code == 200
            assert client.post(
                "/api/v1/sanitize", data={"source_vendor": "aruba_aoss"},
                files={"config": ("c.cfg", AOSS_RANGES.encode(), "text/plain")},
            ).status_code == 413
        assert QUOTED in job["error"], "the client is told what the config wrote"
        logged = "\n".join(
            record.getMessage() + (record.exc_text or "") + str(record.exc_info or "")
            for record in caplog.records
        )
        assert QUOTED not in logged
        assert "16001" not in logged and "would make" not in logged
        refusals = [record for record in caplog.records if "refused" in record.getMessage()]
        assert refusals, "a refusal leaves a line"
        said = refusals[0].getMessage()
        assert refusals[0].levelno == logging.WARNING
        assert "ports limit of the standard limits (asked 9009, limit 8192, counted over 9)" in said
        assert "aruba_aoss -> cisco_iosxe_cli in stage parse" in said


# ---------------------------------------------------------------------------
# Every handler that takes config text works inside a limits scope
# ---------------------------------------------------------------------------

#: A request for each handler that takes config text, by its path.  A
#: handler that is not here fails the test below: give it a line, and
#: open a limits scope in it (``_migration_helpers.request_limits``).
_PLAN = {"source": "cisco_iosxe_cli", "target": "juniper_junos", "raw_text": "hostname A\n"}
TAKES_CONFIG_TEXT: dict[str, dict[str, Any]] = {
    "/api/v1/migration/plan": {"json": _PLAN},
    "/api/v1/migration/plan/ports": {"json": _PLAN},
    "/api/v1/migration/plan/vlans": {"json": _PLAN},
    "/api/v1/migration/plan/local_users": {"json": _PLAN},
    "/api/v1/migration/plan/snmp": {"json": _PLAN},
    "/api/v1/migration/plan/snmpv3": {"json": _PLAN},
    "/api/v1/migration/render": {"json": _PLAN},
    "/api/v1/migration/detect": {"json": {"raw_text": "hostname A\n"}},
    "/api/v1/migration/detect-deployment": {"json": {"source": "aruba_aoss", "raw_text": CAPTURE_2930F}},
    "/api/v1/sanitize": {
        "data": {"source_vendor": "cisco_iosxe_cli"},
        "files": {"config": ("c.cfg", b"hostname A\n", "text/plain")},
    },
}


def _takes_config_text(route: APIRoute) -> bool:
    """A handler takes config text when a parameter of it is an upload,
    or a request body with a ``raw_text`` field."""
    for annotation in get_type_hints(route.endpoint).values():
        if annotation is UploadFile:
            return True
        if inspect.isclass(annotation) and issubclass(annotation, BaseModel) and "raw_text" in annotation.model_fields:
            return True
    return False


class TestEveryHandlerWorksInsideAScope:
    """Work that opens no scope runs under the standard limits.  That
    is safe everywhere but on the public demo, where it is the wrong
    set: several times what the instance was sized for.  So no
    handler may leave it to the default."""

    def test_each_opens_a_scope_of_the_servers(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes = sorted(
            route.path for route in small_client.app.routes
            if isinstance(route, APIRoute) and _takes_config_text(route)
        )
        assert routes == sorted(TAKES_CONFIG_TEXT), (
            "the handlers that take config text are not the ones this test sends a request to"
        )
        opened: list[str] = []
        real = L._Scope.__init__

        def recording(self, limits, surface):
            opened.append(limits.name)
            real(self, limits, surface)

        monkeypatch.setattr(L._Scope, "__init__", recording)
        for path in routes:
            opened.clear()
            resp = small_client.post(path, **TAKES_CONFIG_TEXT[path])
            assert resp.status_code == 200, (path, resp.text[:200])
            assert opened == ["small"], f"{path} opened {opened or 'no scope'}"

    def test_the_handlers_are_found_by_what_they_take(self, small_client: TestClient) -> None:
        """The inventory endpoint takes a declaration and no text; a
        stored config's views parse nothing."""
        takes = {
            route.path: _takes_config_text(route)
            for route in small_client.app.routes if isinstance(route, APIRoute)
        }
        assert takes["/api/v1/migration/inventory"] is False
        assert takes["/api/v1/migration/adapters"] is False
        assert takes["/api/v1/sanitize"] is True and takes["/api/v1/migration/detect"] is True
        assert sum(takes.values()) == len(TAKES_CONFIG_TEXT)


# ---------------------------------------------------------------------------
# The demo's proof by behaviour, run as the document has it
# ---------------------------------------------------------------------------


class TestTheDemosProofByBehaviour:
    """``deploy/VERIFY.md`` proof 14 is how an operator tells that a
    running demo image has the limits at all: one built before them
    ignores the variable and says nothing.  The commands there are
    taken out of the document and run -- against this tree, set as an
    instance is -- and have to print what the document says they
    print."""

    def test_the_documents_commands_print_as_said(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        document = (REPO_ROOT / "deploy" / "VERIFY.md").read_text(encoding="utf-8")
        section = document[document.index("### 14. "):]
        section = section[:section.index("\n---\n")]
        commands = re.search(r"python3 - <<'PY'\n(.*?)\nPY\n", section, re.DOTALL)
        assert commands, "proof 14 has no commands to run"
        expected = re.findall(r"^#   (\S.*)$", section, re.MULTILINE)
        assert len(expected) == 4

        def through_the_app(request: urllib.request.Request, timeout: float = 0):
            assert request.full_url == "http://instance:8000/api/v1/migration/plan"
            assert request.get_header("Authorization") == "Bearer the-key"
            answer = small_client.post("/api/v1/migration/plan", json=json.loads(request.data))
            assert answer.status_code == 200
            return io.BytesIO(answer.content)

        monkeypatch.setenv("IP", "instance")
        monkeypatch.setenv("KEY", "the-key")
        monkeypatch.setattr(urllib.request, "urlopen", through_the_app)
        exec(compile(commands[1], "deploy/VERIFY.md proof 14", "exec"), {})
        assert capsys.readouterr().out.splitlines() == expected == [
            "failed ports", "failed vlan_ids", "failed vlan_ids", "completed None",
        ]
