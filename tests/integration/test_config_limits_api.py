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

Every limit is for one request, and requests at once add up.  A server
set to ``small`` therefore works on ONE request that reads config text
at a time (``TestOneAtATimeUnderSmall``): a second waits its turn inside
its own deadline, and one whose deadline passes in the line is refused
like any other -- a ``failed`` job whose ``refusal.limit`` is
``at_once``, 503 with ``Retry-After`` from the sanitiser and from
``detect``, a note from ``detect-deployment`` -- in words that say the
server was busy and to send it again.

Three more things follow from "requests at once add up", each with a
class below:

* a request holds memory before it can ask for a turn -- its body -- so
  it is COUNTED when its headers arrive, and one that finds every place
  taken is answered 503 at once, its body unread
  (``TestAPlaceBeforeTheBodyIsRead``);
* an answer nobody reads is memory for as long as its client keeps the
  connection, so at the request's deadline it is abandoned
  (``TestAnAnswerNobodyReads``, ``TestTheMiddlewareAlone``) -- and the
  connection itself is ended by the system, which a launcher asks for
  on the socket the server listens on
  (``TestTheSystemEndsAConnectionNobodyReads``);
* a request that waited for its turn and then ran out of time is told
  that the server was busy, and not that it was slow
  (``TestOutOfTimeAfterAWaitIsBusy``).

The texts are small on purpose: a few hundred bytes to a few tens of
kilobytes.  What each expands to is the point.

The test client is put in front of a server that takes an answer as
it is sent (``_Served``), as uvicorn does and as the test client no
longer does; the refusals made after a deadline are also read from
uvicorn itself, on a socket.

The mechanism itself is tested in ``tests/unit/migration/test_limits.py``.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import socket
import threading
import time
import types
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

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


def _taken_as_sent(app: Any) -> Any:
    """*app*, behind a server that takes each message of an answer as
    it is sent and hands it to the client as the client reads: a
    buffer with no bound."""

    async def served(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        taken: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def hand_on() -> None:
            while (message := await taken.get()) is not None:
                await send(message)

        async def take(message: dict[str, Any]) -> None:
            taken.put_nowait(message)

        handing = asyncio.ensure_future(hand_on())
        try:
            await app(scope, receive, take)
        except BaseException:
            handing.cancel()
            raise
        taken.put_nowait(None)
        await handing

    return served


class _Served(TestClient):
    """The test client, in front of a server that takes what it is
    handed.

    An answer made after its request's deadline -- the refusal of a
    request that waited for its turn all that time, or ran out of it
    in a parser -- is sent without waiting for the client: a few
    hundred bytes, which a server takes into its buffer at once
    (``_InItsTime``).  Since Starlette 1.9 the test client takes no
    piece of a body until its client reads it, and the client reads
    only once the head has come, so such a refusal was abandoned
    unsent and these tests read an empty body.  uvicorn takes a write
    into its buffer while that is below its high-water mark
    (``TestOneAtATimeUnderSmall.test_and_on_a_socket`` holds that on
    a real socket); this gives the test client a buffer, as it had
    before.  The tests that use it are of what an answer SAYS.  What
    a server does with an answer nobody reads is tested on a socket
    (``TestAnAnswerNobodyReads``) and against a server the test plays
    (``TestTheMiddlewareAlone``).
    """

    def __init__(self, app: FastAPI) -> None:
        super().__init__(_taken_as_sent(app))
        # The application itself, which the tests read routes from and
        # call directly; its lifespan needs no buffer.
        self.app = app


def _client(settings: Settings, limits: str) -> TestClient:
    return _Served(create_app(settings.model_copy(update={"config_limits": limits})))


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
        memberships and more, where the demo's limit is 50,000.  (And
        more: each trunk carries VLAN 1 untagged as well, its native
        VLAN where it states none, which is a VLAN beside the 500.)"""
        body = {"source": "cisco_nxos", "target": "aruba_aoss", "raw_text": trunk_all(240, 500)}
        assert client.post("/api/v1/migration/plan", json=body).json()["refusal"] is None
        job = small_client.post("/api/v1/migration/plan", json=body).json()
        _refused(job, "memberships", "small")
        assert "(at: 240 trunks that allow every VLAN x 501 VLANs + 240 listed)" in job["error"]

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


_METHODS = ("get", "post", "put", "patch", "delete")


def _what_each_takes(app: FastAPI) -> dict[str, set[str]]:
    """Every path the application documents, with the methods by which
    it takes config text: a request body with a ``raw_text`` field, or
    an uploaded file.

    Read from the application's own account of itself, its OpenAPI
    document, and not from its route table: how a framework holds its
    routes is its own business and changes between its releases.  A
    walk of ``app.routes`` for ``APIRoute`` found every handler on one
    release and none on the next, where the table holds one entry a
    router -- and a rule that finds no handler passes.
    """
    document = app.openapi()
    named = document.get("components", {}).get("schemas", {})

    def schema(node: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in node:
            node = named[node["$ref"].rsplit("/", 1)[1]]
        return node

    def is_a_file(node: dict[str, Any]) -> bool:
        node = schema(node)
        if node.get("format") == "binary" or "contentMediaType" in node:
            return True
        return any(is_a_file(part) for part in node.get("anyOf", []))

    def takes(operation: dict[str, Any]) -> bool:
        for kind, content in operation.get("requestBody", {}).get("content", {}).items():
            fields = schema(content.get("schema", {})).get("properties", {})
            if "raw_text" in fields:
                return True
            if kind.startswith("multipart/") and any(is_a_file(field) for field in fields.values()):
                return True
        return False

    return {
        path: {method.upper() for method in _METHODS if method in item and takes(item[method])}
        for path, item in document["paths"].items()
    }


def _config_text_routes(app: FastAPI) -> list[str]:
    """The paths whose handler takes config text, by any method."""
    return sorted(path for path, methods in _what_each_takes(app).items() if methods)


class TestEveryHandlerWorksInsideAScope:
    """Work that opens no scope runs under the standard limits.  That
    is safe everywhere but on the public demo, where it is the wrong
    set: several times what the instance was sized for.  So no
    handler may leave it to the default."""

    def test_each_opens_a_scope_of_the_servers(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes = _config_text_routes(small_client.app)
        assert routes == sorted(TAKES_CONFIG_TEXT), (
            "the handlers that take config text are not the ones this test sends a request to"
        )
        opened: list[str] = []
        turns: list[tuple[str, bool, tuple[int, int]]] = []
        counted: list[tuple[str, L.Answer, int]] = []
        took: list[L.Answer | None] = []
        real = L._Scope.__init__
        real_take = L._Turns.take
        real_admit = L._Turns.admit

        def recording(self, limits, surface):
            opened.append(limits.name)
            real(self, limits, surface)

        def taking(self, limits, deadline, answer=None):
            held = real_take(self, limits, deadline, answer)
            turns.append((limits.name, isinstance(answer, L.Answer), L.in_flight()))
            took.append(answer)
            return held

        def admitting(self, limits, answer):
            real_admit(self, limits, answer)
            # No scope is open yet and no turn is taken: this is before any handler.
            counted.append((limits.name, answer, len(opened) + len(turns)))

        monkeypatch.setattr(L._Scope, "__init__", recording)
        monkeypatch.setattr(L._Turns, "take", taking)
        monkeypatch.setattr(L._Turns, "admit", admitting)
        for path in routes:
            opened.clear()
            turns.clear()
            counted.clear()
            took.clear()
            resp = small_client.post(path, **TAKES_CONFIG_TEXT[path])
            assert resp.status_code == 200, (path, resp.text[:200])
            assert opened == ["small"], f"{path} opened {opened or 'no scope'}"
            # ...and it is the SERVER's scope: the request took its turn,
            # once, for the answer the application keeps for it (so the
            # turn stays until that has gone out), and it is back.
            assert turns == [("small", True, (1, 0))], f"{path} took {turns or 'no turn'}"
            assert L.in_flight() == (0, 0), path
            # ...and the request was COUNTED when it arrived, before its
            # handler ran: once, for that same answer, with a deadline
            # from then, and its place is back.
            assert [(name, before) for name, _, before in counted] == [("small", 0)], (
                f"{path} was counted {len(counted)} time(s) at its arrival"
            )
            assert counted[0][1] is took[0] and counted[0][1].deadline is not None, path
            assert L.places() == 0, f"{path} did not give its place back"

    def test_the_handlers_are_found_by_what_they_take(self, small_client: TestClient) -> None:
        """The inventory endpoint takes a declaration and no text; a
        stored config's views parse nothing."""
        takes = {path: bool(methods) for path, methods in _what_each_takes(small_client.app).items()}
        assert takes["/api/v1/migration/inventory"] is False
        assert takes["/api/v1/migration/adapters"] is False
        assert takes["/api/v1/sanitize"] is True and takes["/api/v1/migration/detect"] is True
        assert sum(takes.values()) == len(TAKES_CONFIG_TEXT)
        # And the walk sees the application at all: a rule that finds
        # no handler passes, which is how this one was once blind.
        assert len(takes) > len(TAKES_CONFIG_TEXT)


# ---------------------------------------------------------------------------
# One request at a time under ``small``
# ---------------------------------------------------------------------------


def _until(condition: Callable[[], bool], what: str, seconds: float = 10.0) -> None:
    """Wait for *condition*, which another thread is on its way to
    making true.  The time is how long a FAILURE takes to be reported;
    a test that passes waits for the condition and no longer."""
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.002)


class _Work:
    """Stands in front of the pipeline.  The FIRST call says that it
    began and then waits to be let go, so a test can hold one request
    at work for as long as it has things to look at; every call is
    counted, and so is the most that were inside at once."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from netcanon.api.routes import _migration_helpers as helpers

        self.real = helpers.run_plan_with_checked_names
        self.began, self.let_go = threading.Event(), threading.Event()
        self.calls = self.inside = self.most = 0
        self._lock = threading.Lock()
        monkeypatch.setattr(helpers, "run_plan_with_checked_names", self)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            self.calls += 1
            first = self.calls == 1
            self.inside += 1
            self.most = max(self.most, self.inside)
        try:
            if first:
                self.began.set()
                assert self.let_go.wait(30), "the test never let the first request go"
            return self.real(*args, **kwargs)
        finally:
            with self._lock:
                self.inside -= 1


class _Posts:
    """Requests sent from threads of their own, as a browser's are."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.answers: dict[str, Any] = {}
        self.threads: list[threading.Thread] = []

    def send(self, name: str, path: str = "/api/v1/migration/plan", **request: Any) -> threading.Thread:
        def post() -> None:
            self.answers[name] = self.client.post(path, **(request or {"json": _PLAN}))

        thread = threading.Thread(target=post, daemon=True)
        thread.start()
        self.threads.append(thread)
        return thread

    def all_answered(self) -> None:
        for thread in self.threads:
            thread.join(30)
            assert not thread.is_alive(), "a request was never answered"


@contextmanager
def _a_request_at_work() -> Iterator[None]:
    """The place of a ``small`` server, taken by a request on a thread
    of its own (the limit is the process's) until the block ends."""
    held, let_go = threading.Event(), threading.Event()

    def work() -> None:
        with L.server_scope(L.SMALL):
            held.set()
            let_go.wait(30)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    assert held.wait(10)
    try:
        yield
    finally:
        let_go.set()
        thread.join(10)


def _busy(seconds: str = "20") -> str:
    return (
        "the server works on one config at a time, and was busy with another for the "
        f"{seconds} seconds this request may take; this request was not started and its config was not "
        "read.  Send it again.  " + _BUSY_HINT
    )


_BUSY_HINT = (
    "This server runs with the 'small' config size limit, the one the public demo uses.  A Netcanon you "
    "run yourself does not make one request wait for another by default."
)


class TestOneAtATimeUnderSmall:
    """Every single request fits a demo instance under ``small``; two
    at once did not, and ended it.  So a server set to ``small`` works
    on one request that reads config text at a time."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0)
        yield
        assert L.in_flight() == (0, 0), "a turn was not given back, or a request is still in the line"

    def test_two_plans_never_work_at_once(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Shown with an event the first request holds, and no sleep:
        while the first is inside the pipeline the second is in the
        line and has not reached it; let go, both are answered, and
        the pipeline never had two inside."""
        work, posts = _Work(monkeypatch), _Posts(small_client)
        first = posts.send("first")
        assert work.began.wait(10)
        assert L.in_flight() == (1, 0)
        posts.send("second")
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        assert work.calls == 1, "the second request reached the pipeline while the first was in it"
        assert first.is_alive() and "second" not in posts.answers
        work.let_go.set()
        posts.all_answered()
        assert (work.calls, work.most) == (2, 1)
        for name in ("first", "second"):
            resp = posts.answers[name]
            assert resp.status_code == 200
            assert (resp.json()["status"], resp.json()["refusal"]) == ("completed", None), name

    def test_health_and_the_pages_never_wait_behind_it(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With one translation at work and the line FULL behind it:
        the probe, the pages and the endpoints that read no config
        text answer at once, and one more request that does read
        config text is turned away at once -- it is not left to hold
        one more thread of the pool the pages are served from."""
        work, posts = _Work(monkeypatch), _Posts(small_client)
        posts.send("at work")
        assert work.began.wait(10)
        for n in range(L.MOST_WAITING):
            posts.send(f"in the line {n}")
            _until(lambda n=n: L.in_flight() == (1, n + 1), f"request {n + 2} standing in the line")
        began = time.monotonic()
        assert small_client.get("/health").json()["status"] == "ok"
        for path in ("/", "/migrate", "/sanitize", "/api/v1/migration/adapters",
                     "/api/v1/migration/target-profiles", "/api/v1/migration/model-families"):
            assert small_client.get(path).status_code == 200, path
        # An endpoint of the translator that takes a declaration and no text.
        inventory = small_client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss", "deployment": SOURCE_2930F,
        })
        assert inventory.status_code == 200 and inventory.json()["ports"]
        turned_away = small_client.post("/api/v1/migration/plan", json=_PLAN)
        took = time.monotonic() - began
        assert took < 5.0, f"they waited: {took:.1f} s, with a request at work that had not been let go"
        assert L.in_flight() == (1, L.MOST_WAITING) and work.calls == 1
        # One at work and two in the line are every place there is: this
        # one was answered by the application when it arrived, and never
        # reached a handler.
        assert L.MOST_WAITING == 2 and L.places() == 1 + L.MOST_WAITING
        assert turned_away.status_code == 503 and turned_away.headers["Retry-After"] == "5"
        assert turned_away.json()["detail"].startswith(
            "Refused: the server works on one config at a time, and 2 more were already waiting their turn; "
            "this request was not started and its config was not read.  Send it again."
        )
        work.let_go.set()
        posts.all_answered()
        assert (work.calls, work.most) == (1 + L.MOST_WAITING, 1)
        assert {resp.json()["status"] for resp in posts.answers.values()} == {"completed"}

    def test_busy_is_a_refusal_in_words_on_every_surface(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """With the place taken for longer than a request may take,
        EVERY handler that takes config text answers that the server
        was busy -- found by what they take, as above, so that a
        handler added tomorrow is asked too.  Each in the shape its
        other refusals have; never an unhandled error (a 500), never
        ``parse failed``."""
        routes = _config_text_routes(small_client.app)
        assert routes == sorted(TAKES_CONFIG_TEXT)
        # A fifth of a second stands for the twenty: only the number in the sentence differs.
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=0.2))
        sentence = _busy("0.2")
        refusal = {
            "limit": "at_once", "what": "requests that read config text, at work at once", "asked": 2,
            "exact": True, "cap": 1, "stage": "", "codec": "", "profile": "small", "how_to_raise": _BUSY_HINT,
        }
        with _a_request_at_work(), caplog.at_level(logging.WARNING):
            for path in routes:
                resp = small_client.post(path, **TAKES_CONFIG_TEXT[path])
                assert resp.status_code in (200, 503), (path, resp.status_code, resp.text[:200])
                assert "parse failed" not in resp.text and "unexpectedly" not in resp.text, path
                if path == "/api/v1/migration/detect-deployment":
                    proposal = resp.json()
                    assert resp.status_code == 200
                    assert proposal["notes"] == ["Nothing was proposed: " + sentence]
                    assert (proposal["deployment"], proposal["consistent"], proposal["stated"]) == (None, None, False)
                elif path in ("/api/v1/sanitize", "/api/v1/migration/detect"):
                    # Not 413: nothing is too large, and the same request can be sent again.
                    assert resp.status_code == 503, (path, resp.text[:200])
                    assert resp.headers["Retry-After"] == "5"
                    assert resp.json() == {"detail": "Refused: " + sentence}
                else:
                    job = resp.json()
                    assert resp.status_code == 200 and resp.headers["X-Netcanon-Job-Status"] == "failed"
                    assert (job["status"], job["rendered"], job["validation"]) == ("failed", None, None)
                    assert job["refusal"] == refusal, path
                    assert job["error"] == "refused: " + sentence
                    assert (job["source_codec"], job["target_codec"]) == ("cisco_iosxe_cli", "juniper_junos")
                    assert job["completed_at"]
                assert L.in_flight() == (1, 0), f"{path}: the request that gave up left something behind"
        lines = [record.getMessage() for record in caplog.records if "before any stage" in record.getMessage()]
        assert len(lines) == len(JOB_ENDPOINTS)
        assert lines[0].endswith(
            "refused cisco_iosxe_cli -> juniper_junos before any stage: at_once limit of the small limits "
            "(asked 2, limit 1)"
        )

    def test_and_on_a_socket(
        self, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Each refusal above is made at its request's deadline and
        sent after it, without waiting for the client.  The test client
        is given a buffer to take it (``_Served``); this is the server
        Netcanon runs, on a socket, where every surface's refusal
        reaches a client that reads it and none is abandoned."""
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=0.2))
        sentence = _busy("0.2")
        with (
            _on_a_socket(test_settings) as port,
            _a_request_at_work(),
            caplog.at_level(logging.WARNING),
            httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as web,
        ):
            for path in sorted(TAKES_CONFIG_TEXT):
                resp = web.post(path, **TAKES_CONFIG_TEXT[path])
                assert resp.content, f"{path}: an empty answer"
                if path == "/api/v1/migration/detect-deployment":
                    assert resp.status_code == 200
                    assert resp.json()["notes"] == ["Nothing was proposed: " + sentence]
                elif path in ("/api/v1/sanitize", "/api/v1/migration/detect"):
                    assert resp.status_code == 503 and resp.headers["Retry-After"] == "5", path
                    assert resp.json() == {"detail": "Refused: " + sentence}, path
                else:
                    assert resp.status_code == 200 and resp.headers["X-Netcanon-Job-Status"] == "failed", path
                    assert resp.json()["error"] == "refused: " + sentence, path
        assert not [record for record in caplog.records if "was abandoned" in record.getMessage()]

    def test_the_sentence_under_the_shipped_limits(self) -> None:
        """The test above shortens the wait; this is the sentence a
        visitor reads, with the number ``small`` ships."""
        exc = L._busy(L.SMALL, 2, L.SMALL.seconds)
        assert str(exc) == _busy() and L.SMALL.seconds == 20

    def test_the_place_is_given_back_whatever_the_work_did(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from netcanon.api.routes import _migration_helpers as helpers

        three = 'hostname "T"\nvlan 10\n   tagged 1-1001,2001-3001,4001-5001\n   exit\n'
        # A refusal for size.
        job = small_client.post("/api/v1/migration/plan", json={
            "source": "aruba_aoss", "target": "cisco_iosxe_cli", "raw_text": three,
        }).json()
        assert job["refusal"]["limit"] == "ports" and L.in_flight() == (0, 0)
        # A text the codec cannot read.
        job = small_client.post("/api/v1/migration/plan", json={
            "source": "opnsense", "target": "juniper_junos", "raw_text": "<opnsense><unclosed>",
        }).json()
        assert job["error"].startswith("parse failed") and L.in_flight() == (0, 0)
        # The sanitiser: a refusal, and a parse failure.
        for vendor, text, status in (("aruba_aoss", three, 413), ("opnsense", "<opnsense><unclosed>", 400)):
            resp = small_client.post(
                "/api/v1/sanitize", data={"source_vendor": vendor},
                files={"config": ("c.cfg", text.encode(), "text/plain")},
            )
            assert resp.status_code == status and L.in_flight() == (0, 0), (vendor, resp.text[:200])
        # A fault nobody expected, from below every handler's own net.
        real = helpers.run_plan_with_checked_names

        def broken(*args: Any, **kwargs: Any) -> Any:
            assert L.in_flight() == (1, 0)
            raise RuntimeError("a fault in the work")

        monkeypatch.setattr(helpers, "run_plan_with_checked_names", broken)
        with pytest.raises(RuntimeError, match="a fault in the work"):
            small_client.post("/api/v1/migration/plan", json=_PLAN)
        assert L.in_flight() == (0, 0)
        monkeypatch.setattr(helpers, "run_plan_with_checked_names", real)
        # The next request has the place, and does not wait for anyone.
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=0.2))
        assert small_client.post("/api/v1/migration/plan", json=_PLAN).json()["status"] == "completed"

    def test_a_client_that_went_away_gives_the_place_back(
        self, test_settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Over a real socket: one client leaves while its request is
        at work, another while its request stands in the line.  A
        turn belongs to the thread that does the work, which runs to
        the end of its block whoever is still listening: both turns
        come back, and the server goes on serving."""
        import uvicorn

        work = _Work(monkeypatch)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        app = create_app(test_settings.model_copy(update={"config_limits": "small"}))
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", ws="none"),
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        body = json.dumps(_PLAN).encode()
        head = (
            f"POST /api/v1/migration/plan HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        ).encode()
        try:
            _until(lambda: server.started, "the server starting")
            working = socket.create_connection(("127.0.0.1", port), timeout=10)
            working.sendall(head + body)
            assert work.began.wait(10)
            waiting = socket.create_connection(("127.0.0.1", port), timeout=10)
            waiting.sendall(head + body)
            _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
            assert L.places() == 2
            working.close()
            waiting.close()
            assert L.in_flight() == (1, 1) and L.places() == 2
            work.let_go.set()
            _until(lambda: L.in_flight() == (0, 0), "both turns given back after the clients left")
            _until(lambda: L.places() == 0, "both places given back after the clients left")
            assert (work.calls, work.most) == (2, 1)
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/v1/migration/plan", data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as resp:
                assert json.loads(resp.read())["status"] == "completed"
        finally:
            work.let_go.set()
            server.should_exit = True
            thread.join(15)

    def test_under_standard_nothing_waits(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The default limits no requests at once: with one request
        held inside the pipeline, a second is translated and answered
        -- and the place of a ``small`` server, taken besides, is
        nothing to either."""
        work, posts = _Work(monkeypatch), _Posts(client)
        with _a_request_at_work():
            first = posts.send("first")
            assert work.began.wait(10)
            second = client.post("/api/v1/migration/plan", json=_PLAN)
            assert second.json()["status"] == "completed" and first.is_alive()
            assert (work.calls, work.most) == (2, 2)
            for path, request in TAKES_CONFIG_TEXT.items():
                assert client.post(path, **request).status_code == 200, path
            assert L.in_flight() == (1, 0), "a request under the standard limits took a turn"
            work.let_go.set()
            posts.all_answered()
        assert posts.answers["first"].json()["status"] == "completed"


class TestTheTurnStaysUntilTheAnswerHasGoneOut:
    """A handler's work ends when it returns, and the answer is still
    to be made into bytes and sent: for a large job, tens of
    megabytes.  The application keeps the request's turn until then
    (``_migration_helpers.AnswerSent``)."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0)
        yield
        assert L.in_flight() == (0, 0), "a turn was not given back"

    def test_it_is_the_outermost_middleware(self, test_settings: Settings) -> None:
        """The other middlewares pass an answer's bytes on.  Only
        outside all of them has the answer left the process."""
        from netcanon.api.routes._migration_helpers import AnswerSent

        app = create_app(test_settings)
        assert len(app.user_middleware) >= 3
        assert app.user_middleware[0].cls is AnswerSent

    def test_the_turn_is_held_while_the_answer_is_being_sent(self) -> None:
        """An application of one route, whose answer is sent in two
        parts with a wait between them that the test ends.  The
        handler has returned -- its block is over -- and the turn is
        still out; it comes back when the last part has gone."""
        from netcanon.api.routes._migration_helpers import AnswerSent, request_answer

        returned, send_the_rest = threading.Event(), threading.Event()
        app = FastAPI()
        app.add_middleware(AnswerSent)

        @app.post("/work")
        def work(request: Request) -> StreamingResponse:
            def parts():
                yield b"the first part, "
                returned.set()
                assert send_the_rest.wait(30)
                yield b"and the rest"

            with L.server_scope("small", answer=request_answer(request)):
                assert L.in_flight() == (1, 0)
            return StreamingResponse(parts(), media_type="text/plain")

        @app.post("/broken")
        def broken(request: Request) -> None:
            with L.server_scope("small", answer=request_answer(request)):
                raise RuntimeError("a fault in the work")

        with TestClient(app) as client:
            posts = _Posts(client)
            posts.send("slow", "/work", json={})
            assert returned.wait(10)
            assert L.in_flight() == (1, 0), "the turn came back with the answer half sent"
            send_the_rest.set()
            posts.all_answered()
            assert posts.answers["slow"].text == "the first part, and the rest"
            assert L.in_flight() == (0, 0)
            # A handler that raises is answered too, and its turn comes back.
            with pytest.raises(RuntimeError):
                client.post("/broken")
            assert L.in_flight() == (0, 0)

    def test_without_the_middleware_the_turn_comes_back_with_the_block(self) -> None:
        """An application assembled without it keeps no answer for a
        request: nobody would say that the answer went out, so the
        turn is not left waiting for that."""
        from netcanon.api.routes._migration_helpers import request_answer

        app = FastAPI()
        seen: list[object] = []

        @app.post("/work")
        def work(request: Request) -> dict[str, bool]:
            seen.append(request_answer(request))
            with L.server_scope("small", answer=request_answer(request)):
                pass
            seen.append(L.in_flight())
            return {"ok": True}

        with TestClient(app) as client:
            assert client.post("/work").json() == {"ok": True}
        assert seen == [None, (0, 0)]

    def test_the_sanitiser_reads_its_upload_with_the_turn(self) -> None:
        """A request that waits holds its body.  The sanitiser's is
        an upload the framework has stored: it is read into memory
        when the request has its turn, and not before -- and the cap
        on its size is held there too."""
        from netcanon.api.routes import sanitize as route

        class Upload(io.BytesIO):
            read_with: list[tuple[int, int]] = []

            def read(self, size: int = -1) -> bytes:
                self.read_with.append(L.in_flight())
                return super().read(size)

        upload = Upload(CAPTURE_2930F.encode())
        result = route._sanitize_within("small", None, upload, 1_000_000, "aruba_aoss", False)
        assert Upload.read_with == [(1, 0)] and result.sanitized_text
        with pytest.raises(route._UploadTooLarge):
            route._sanitize_within("small", None, io.BytesIO(b"x" * 101), 100, "aruba_aoss", False)
        assert L.in_flight() == (0, 0)
        # With the place taken, a request that gives up has read nothing.
        Upload.read_with.clear()
        with _a_request_at_work(), pytest.raises(L.LimitExceeded):
            route._sanitize_within(
                replace(L.SMALL, seconds=0.2), None, Upload(b"hostname x\n"), 100, "aruba_aoss", False,
            )
        assert Upload.read_with == []

    def test_no_more_of_an_upload_is_read_than_shows_it_is_too_large(self) -> None:
        """An upload past the cap is refused on one byte past the
        cap: the rest of what the framework stored is never pulled
        into memory."""
        from netcanon.api.routes import sanitize as route

        class Upload(io.BytesIO):
            def __init__(self, data: bytes) -> None:
                super().__init__(data)
                self.asked: list[int] = []

            def read(self, size: int = -1) -> bytes:
                self.asked.append(size)
                return super().read(size)

        cap = 1_000
        upload = Upload(b"x" * (50 * cap))
        with pytest.raises(route._UploadTooLarge):
            route._sanitize_within("small", None, upload, cap, "aruba_aoss", False)
        assert upload.asked == [cap + 1], "the whole upload was read to find that it was too large"
        assert upload.tell() == cap + 1 and L.in_flight() == (0, 0)

    def test_an_upload_over_the_cap_is_still_413(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """...and is refused before the request asks for a turn: with
        the place taken for longer than a request may wait, it is
        answered at once."""
        from netcanon import config as app_config

        monkeypatch.setattr(app_config, "MAX_SANITIZE_UPLOAD_BYTES", 100)
        with _a_request_at_work():
            began = time.monotonic()
            resp = small_client.post(
                "/api/v1/sanitize", data={"source_vendor": "aruba_aoss"},
                files={"config": ("c.cfg", b"x" * 101, "text/plain")},
            )
            assert time.monotonic() - began < 5.0
        assert resp.status_code == 413
        assert resp.json()["detail"].startswith("Config upload exceeds the 100 byte limit.")


# ---------------------------------------------------------------------------
# The demo's proof by behaviour, run as the document has it
# ---------------------------------------------------------------------------


def _proof(number: int) -> tuple[str, list[str]]:
    """The commands of proof *number* of ``deploy/VERIFY.md``, and
    the lines the document says they print."""
    document = (REPO_ROOT / "deploy" / "VERIFY.md").read_text(encoding="utf-8")
    section = document[document.index(f"### {number}. "):]
    section = section[:min(
        at for at in (section.find("\n### ", 1), section.find("\n---\n")) if at > 0
    )]
    commands = re.search(r"python3 - <<'PY'\n(.*?)\nPY\n", section, re.DOTALL)
    assert commands, f"proof {number} has no commands to run"
    return commands[1], re.findall(r"^#   (\S.*)$", section, re.MULTILINE)


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
        section = section[:section.index("\n### 15. ")]
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

    def test_the_commands_for_requests_at_once_print_as_said(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Proof 15: three of the largest requests ``small`` admits,
        at once, are each answered -- and, which the document cannot
        see from outside and this can, they were worked on one at a
        time."""
        from netcanon.api.routes import _migration_helpers as helpers

        commands, expected = _proof(15)
        assert expected == ["True ['partial', 'partial', 'partial']"]

        real = helpers.run_plan_with_checked_names
        lock = threading.Lock()
        seen = {"inside": 0, "most": 0, "calls": 0}

        def counted(*args: Any, **kwargs: Any) -> Any:
            with lock:
                seen["calls"] += 1
                seen["inside"] += 1
                seen["most"] = max(seen["most"], seen["inside"])
            try:
                return real(*args, **kwargs)
            finally:
                with lock:
                    seen["inside"] -= 1

        def through_the_app(request: urllib.request.Request, timeout: float = 0):
            assert request.full_url == "http://instance:8000/api/v1/migration/plan"
            assert request.get_header("Authorization") == "Bearer the-key"
            answer = small_client.post(
                "/api/v1/migration/plan", content=request.data, headers={"Content-Type": "application/json"},
            )
            assert answer.status_code == 200
            return types.SimpleNamespace(headers=answer.headers, read=lambda: answer.content)

        monkeypatch.setenv("IP", "instance")
        monkeypatch.setenv("KEY", "the-key")
        monkeypatch.setattr(urllib.request, "urlopen", through_the_app)
        monkeypatch.setattr(helpers, "run_plan_with_checked_names", counted)
        exec(compile(commands, "deploy/VERIFY.md proof 15", "exec"), {})
        assert capsys.readouterr().out.splitlines() == expected
        assert (seen["calls"], seen["most"]) == (3, 1), "three at once were not worked on one at a time"
        assert L.in_flight() == (0, 0)

    def test_the_commands_for_a_burst_print_as_said(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Proof 16: twenty of the largest requests at once.  Three
        are translated and seventeen are told the server was busy --
        and, which the document cannot see from outside and this can,
        seventeen never reached a handler, and the three were worked
        on one at a time."""
        from netcanon.api.routes import _migration_helpers as helpers

        commands, expected = _proof(16)
        assert expected == ["3 17 0 True"]
        real = helpers.run_plan_with_checked_names
        lock = threading.Lock()
        seen = {"inside": 0, "most": 0, "calls": 0}

        def counted(*args: Any, **kwargs: Any) -> Any:
            with lock:
                seen["calls"] += 1
                seen["inside"] += 1
                seen["most"] = max(seen["most"], seen["inside"])
            try:
                return real(*args, **kwargs)
            finally:
                with lock:
                    seen["inside"] -= 1

        def through_the_app(request: urllib.request.Request, timeout: float = 0):
            assert request.full_url == "http://instance:8000/api/v1/migration/plan"
            assert request.get_header("Authorization") == "Bearer the-key"
            answer = small_client.post(
                "/api/v1/migration/plan", content=request.data, headers={"Content-Type": "application/json"},
            )
            if answer.status_code != 200:
                raise urllib.error.HTTPError(
                    request.full_url, answer.status_code, answer.reason_phrase, answer.headers,  # type: ignore[arg-type]
                    io.BytesIO(answer.content),
                )
            return types.SimpleNamespace(headers=answer.headers, read=lambda: answer.content)

        monkeypatch.setenv("IP", "instance")
        monkeypatch.setenv("KEY", "the-key")
        monkeypatch.setattr(urllib.request, "urlopen", through_the_app)
        monkeypatch.setattr(helpers, "run_plan_with_checked_names", counted)
        exec(compile(commands, "deploy/VERIFY.md proof 16", "exec"), {})
        assert capsys.readouterr().out.splitlines() == expected
        assert (seen["calls"], seen["most"]) == (3, 1), "twenty at once: three are worked on, one at a time"
        assert L.in_flight() == (0, 0) and L.places() == 0

    def test_the_commands_for_answers_nobody_reads_print_as_said(
        self, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Proof 17, over a real socket, as the document has it but
        for its two numbers, which it reads from the environment: two
        answers where it sends four, and eight seconds standing for
        the twenty a request may take (the gap is scaled with them).
        The line a server's log has for every answer it abandons is
        counted here, and the size it gives for the answer is the
        size the document gives."""
        commands, expected = _proof(17)
        assert expected == ["True completed True"]
        assert 'os.environ.get("N", "4")' in commands and 'os.environ.get("GAP", "19.5")' in commands
        assert L.SMALL.seconds == 20, "the gap in the document is just under a request's seconds"
        seconds, count = 8.0, 2
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=seconds))
        real_urlopen = urllib.request.urlopen
        with _on_a_socket(test_settings) as port, caplog.at_level(logging.WARNING):
            real_socket = socket.socket
            connected: list[Any] = []

            class ToThisServer(real_socket):
                """A socket whose connection to the instance of the
                document goes to this server; any other is its own."""

                def connect(self, address: Any) -> None:
                    if address == ("instance", 8000):
                        connected.append(address)
                        address = ("127.0.0.1", port)
                    super().connect(address)

            def to_this_server(request: urllib.request.Request, timeout: float = 0):
                assert request.get_header("Authorization") == "Bearer the-key"
                assert request.full_url.startswith("http://instance:8000/")
                return real_urlopen(urllib.request.Request(
                    request.full_url.replace("instance:8000", f"127.0.0.1:{port}"), data=request.data,
                    headers=dict(request.header_items()),
                ), timeout=timeout)

            monkeypatch.setenv("IP", "instance")
            monkeypatch.setenv("KEY", "the-key")
            monkeypatch.setenv("N", str(count))
            monkeypatch.setenv("GAP", str(19.5 / 20 * seconds))
            monkeypatch.setattr(socket, "socket", ToThisServer)
            monkeypatch.setattr(urllib.request, "urlopen", to_this_server)
            try:
                exec(compile(commands, "deploy/VERIFY.md proof 17", "exec"), {})
            finally:
                monkeypatch.setattr(socket, "socket", real_socket)
            assert capsys.readouterr().out.splitlines() == expected
            assert len(connected) == count, "the document's commands did not send what the test set"
            _until(lambda: L.in_flight() == (0, 0) and L.places() == 0, "every turn and every place given back")
        abandoned = [record.getMessage() for record in caplog.records if "was abandoned" in record.getMessage()]
        assert len(abandoned) == count, abandoned
        document = " ".join((REPO_ROOT / "deploy" / "VERIFY.md").read_text(encoding="utf-8").split())
        megabytes = re.search(r"### 17\. .*?The answer to the request of proof 15 is (\d+) MB", document)
        assert megabytes, "proof 17 does not say how large the answer is"
        for line in abandoned:
            said = re.search(r"abandoned: (\d+) of ([\d,]+) bytes had been handed to the client", line)
            assert said, line
            whole = int(said[2].replace(",", ""))
            assert int(said[1]) < 10_000_000 < whole, line
            assert round(whole / 1e6) == int(megabytes[1]), (whole, megabytes[1])


# ---------------------------------------------------------------------------
# A place, counted before the body is read
# ---------------------------------------------------------------------------


@contextmanager
def _on_a_socket(settings: Settings, limits: str = "small") -> Iterator[int]:
    """The application behind a real server, in this process, with
    this server's limits; the port it listens on."""
    import uvicorn

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_app(settings.model_copy(update={"config_limits": limits}))
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", ws="none"),
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _until(lambda: server.started, "the server starting")
        yield port
    finally:
        server.should_exit = True
        thread.join(15)


def _head(port: int, path: str, length: int, kind: str = "application/json") -> bytes:
    """The head of a POST that says its body is *length* bytes."""
    return (
        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: {kind}\r\n"
        f"Content-Length: {length}\r\n\r\n"
    ).encode()


def _read_answer(sock: socket.socket, timeout: float = 30.0) -> tuple[int, dict[str, str], bytes]:
    """The status, the headers, and the body as far as it comes: to
    its length, or to the end of the connection."""
    sock.settimeout(timeout)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        assert chunk, f"the connection ended before an answer: {data[:200]!r}"
        data += chunk
    top, _, body = data.partition(b"\r\n\r\n")
    first, *rest = top.decode("latin-1").split("\r\n")
    headers = {name.lower(): value for name, value in (line.split(": ", 1) for line in rest)}
    while len(body) < int(headers.get("content-length", 0)):
        chunk = sock.recv(1 << 20)
        if not chunk:
            break
        body += chunk
    return int(first.split()[1]), headers, body


def _alone(coroutine: Any) -> Any:
    """Run *coroutine* to its end in an event loop of its own, on a
    thread of its own, and give back what it returned or raise what it
    raised.  (``asyncio.run`` refuses in a thread that has a loop
    running already, and a test process can have one: the browser
    tests keep theirs.)"""
    ended: list[tuple[bool, Any]] = []

    def run() -> None:
        try:
            ended.append((True, asyncio.run(coroutine)))
        except BaseException as exc:  # handed to the test, whatever it is
            ended.append((False, exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(60)
    assert ended, "the coroutine did not end"
    went, value = ended[0]
    if not went:
        raise value
    return value


def _plain_scope(path: str, method: str = "POST") -> dict[str, Any]:
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
        "headers": [(b"content-type", b"application/json"), (b"content-length", b"2000000")],
    }


class TestAPlaceBeforeTheBodyIsRead:
    """A body is read before its request can ask for a turn, and a
    body is memory: twelve requests with two-megabyte bodies at once
    ended a demo instance although nine of them were turned away.  So
    a request that would read config text is counted when its HEADERS
    arrive.  There are as many places as may work and wait; one more
    request is answered 503 at once, and its body is never read."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0) and L.places() == 0
        yield
        _until(lambda: L.in_flight() == (0, 0) and L.places() == 0, "every turn and every place given back")

    def test_what_is_counted_is_what_takes_config_text(self, small_client: TestClient) -> None:
        """The handlers are found by what they take; the application
        decides by method and path, when that is all it has.  The two
        have to be the same set -- a handler added tomorrow that is
        not counted has its body read before anything limits it."""
        from netcanon.api.routes import _migration_helpers as helpers

        found = {path: methods for path, methods in _what_each_takes(small_client.app).items() if methods}
        assert set(found) == set(helpers.READS_CONFIG_TEXT) == set(TAKES_CONFIG_TEXT)
        assert all(methods == {"POST"} for methods in found.values()), found
        for path in found:
            assert helpers.reads_config_text({"method": "POST", "path": path})
            assert not helpers.reads_config_text({"method": "GET", "path": path})
            assert not helpers.reads_config_text({"method": "POST", "path": path + "/"})
            # A server told that it is mounted under a prefix hands the whole path over.
            assert helpers.reads_config_text({"method": "POST", "path": "/nc" + path, "root_path": "/nc"})
            assert not helpers.reads_config_text({"method": "POST", "path": "/nc" + path})
        for path in ("/health", "/", "/migrate", "/sanitize", "/api/v1/migration/inventory",
                     "/api/v1/migration/adapters", "/api/v1/backups"):
            assert not helpers.reads_config_text({"method": "POST", "path": path}), path

    def test_with_every_place_taken_each_is_answered_at_once(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """EVERY handler that takes config text, found by what they
        take: 503, ``Retry-After``, the sentence a busy server gives
        -- and no handler ran, so nothing of the request was worked
        on."""
        routes = _config_text_routes(small_client.app)
        assert routes == sorted(TAKES_CONFIG_TEXT)
        opened: list[str] = []
        real = L._Scope.__init__

        def recording(self, limits, surface):
            opened.append(limits.name)
            real(self, limits, surface)

        monkeypatch.setattr(L._Scope, "__init__", recording)
        held = [L.Answer() for _ in range(L.SMALL.at_once + L.MOST_WAITING)]
        for answer in held:
            answer.arrived("small")
        sentence = (
            "Refused: the server works on one config at a time, and 2 more were already waiting their turn; this "
            "request was not started and its config was not read.  Send it again.  " + _BUSY_HINT
        )
        try:
            for path in routes:
                began = time.monotonic()
                resp = small_client.post(path, **TAKES_CONFIG_TEXT[path])
                assert resp.status_code == 503, (path, resp.status_code, resp.text[:200])
                assert time.monotonic() - began < 5.0, path
                assert resp.headers["Retry-After"] == "5" and resp.headers["content-type"] == "application/json"
                assert resp.headers["x-content-type-options"] == "nosniff"
                assert resp.json() == {"detail": sentence}, path
                assert int(resp.headers["content-length"]) == len(resp.content)
            assert opened == [], "a request that was refused a place reached a handler"
            assert L.places() == len(held) == 3
            # What reads no config text is answered as ever, with every place taken.
            assert small_client.get("/health").json()["status"] == "ok"
            for path in ("/", "/migrate", "/sanitize", "/api/v1/migration/adapters"):
                assert small_client.get(path).status_code == 200, path
            assert small_client.post("/api/v1/migration/inventory", json={
                "codec": "aruba_aoss", "deployment": SOURCE_2930F,
            }).status_code == 200
        finally:
            for answer in held:
                answer.sent()
        # ...and with a place free again, the same request is translated.
        assert small_client.post("/api/v1/migration/plan", json=_PLAN).json()["status"] == "completed"

    def test_and_its_body_is_never_asked_for(self, small_client: TestClient) -> None:
        """Spoken to as a server speaks to it: the application
        answers from the headers alone, and does not call for the
        body once."""
        held = [L.Answer() for _ in range(3)]
        for answer in held:
            answer.arrived("small")

        async def asked(path: str) -> list[dict[str, Any]]:
            sent: list[dict[str, Any]] = []

            async def receive() -> dict[str, Any]:
                raise AssertionError(f"{path}: the body of a request that was refused a place was asked for")

            async def send(message: dict[str, Any]) -> None:
                sent.append(message)

            await small_client.app(_plain_scope(path), receive, send)
            return sent

        try:
            for path in _config_text_routes(small_client.app):
                start, body = _alone(asked(path))
                assert (start["type"], start["status"]) == ("http.response.start", 503), path
                assert (b"retry-after", b"5") in start["headers"]
                assert body["type"] == "http.response.body" and not body.get("more_body", False)
                assert json.loads(body["body"])["detail"].startswith("Refused: the server works on one config")
        finally:
            for answer in held:
                answer.sent()

    def test_nothing_else_is_counted(self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """A ``GET``, the probe, the pages, an endpoint that takes a
        declaration and no text: none takes a place."""
        counted: list[object] = []
        real = L._Turns.admit
        monkeypatch.setattr(L._Turns, "admit", lambda self, limits, answer: counted.append(answer) or real(
            self, limits, answer))
        assert small_client.get("/health").status_code == 200
        for path in ("/", "/migrate", "/sanitize", "/api/v1/migration/adapters",
                     "/api/v1/migration/target-profiles", "/api/v1/migration/model-families"):
            assert small_client.get(path).status_code == 200, path
        assert small_client.post("/api/v1/migration/inventory", json={
            "codec": "aruba_aoss", "deployment": SOURCE_2930F,
        }).status_code == 200
        assert small_client.get("/api/v1/migration/plan").status_code == 405
        assert counted == []
        assert small_client.post("/api/v1/migration/plan", json=_PLAN).status_code == 200
        assert len(counted) == 1, "the test would not see a request counted"

    def test_under_standard_nothing_is_counted(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default limits no requests at once: nothing is counted,
        nothing has a deadline from its arrival, and an answer goes to
        the server as the application made it."""
        held = [L.Answer() for _ in range(3)]
        for answer in held:
            answer.arrived("small")  # every place of a `small` server, taken besides
        counted: list[object] = []
        real = L._Turns.admit
        monkeypatch.setattr(L._Turns, "admit", lambda self, limits, answer: counted.append(answer) or real(
            self, limits, answer))
        try:
            for path, request in TAKES_CONFIG_TEXT.items():
                assert client.post(path, **request).status_code == 200, path
            assert counted == [], "a request under the standard limits was counted"
            assert L.places() == 3
        finally:
            for answer in held:
                answer.sent()

    def test_a_place_is_held_from_the_headers(self, test_settings: Settings) -> None:
        """Over a real socket.  Three requests have sent their heads
        and one byte of body: three places are taken, and nobody has
        asked for a turn.  A fourth, whose two megabytes never come,
        is answered at once.  The three then finish sending, are
        translated, and their places come back."""
        body = json.dumps(_PLAN).encode()
        with _on_a_socket(test_settings) as port:
            sending = []
            for _ in range(3):
                sock = socket.create_connection(("127.0.0.1", port), timeout=10)
                sock.sendall(_head(port, "/api/v1/migration/plan", len(body)) + body[:1])
                sending.append(sock)
            _until(lambda: L.places() == 3, "three requests counted, their bodies still to come")
            assert L.in_flight() == (0, 0), "a request with no body yet asked for a turn"
            began = time.monotonic()
            fourth = socket.create_connection(("127.0.0.1", port), timeout=10)
            fourth.sendall(_head(port, "/api/v1/sanitize", 2_000_000, "multipart/form-data; boundary=x") + b"--x\r\n")
            status, headers, answer = _read_answer(fourth)
            assert time.monotonic() - began < 5.0, "it waited, for a body that was not coming"
            assert (status, headers["retry-after"]) == (503, "5")
            assert json.loads(answer)["detail"].startswith(
                "Refused: the server works on one config at a time, and 2 more were already waiting their turn"
            )
            fourth.close()
            probe = socket.create_connection(("127.0.0.1", port), timeout=10)
            probe.sendall(f"GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
            assert _read_answer(probe)[0] == 200
            probe.close()
            assert L.places() == 3
            for sock in sending:
                sock.sendall(body[1:])
            for sock in sending:
                status, _, answer = _read_answer(sock)
                assert status == 200 and json.loads(answer)["status"] == "completed"
                sock.close()
            _until(lambda: L.places() == 0, "the three places given back")

    @pytest.mark.parametrize("path, kind, some", [
        ("/api/v1/migration/plan", "application/json", b'{"raw_text": "hostname NOT-FOR-THE-LOG'),
        ("/api/v1/sanitize", "multipart/form-data; boundary=x",
         b'--x\r\nContent-Disposition: form-data; name="source_vendor"\r\n\r\ncisco_ios'),
    ])
    def test_a_body_that_does_not_come_is_answered_408(
        self, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
        path: str, kind: str, some: bytes,
    ) -> None:
        """A request with no body yet holds a place, and a client
        that sends no more would hold it for as long as it kept the
        connection.  What bounds it is the request's deadline, which
        runs from its arrival (half a second stands for the twenty):
        then it is answered in words, the connection is closed, and
        the place is back.  The log says so in counts."""
        brief = replace(L.SMALL, seconds=0.5)
        monkeypatch.setitem(L.PROFILES, "small", brief)
        with _on_a_socket(test_settings) as port, caplog.at_level(logging.WARNING):
            began = time.monotonic()
            sock = socket.create_connection(("127.0.0.1", port), timeout=10)
            sock.sendall(_head(port, path, 50_000, kind) + some)
            _until(lambda: L.places() == 1, "the request counted, its body still to come")
            status, headers, answer = _read_answer(sock)
            took = time.monotonic() - began
            assert status == 408 and headers["connection"] == "close"
            assert 0.4 < took < 10.0, took
            assert json.loads(answer) == {"detail": (
                "Refused: the request passed the 0.5 seconds it may take while its body was still arriving, and "
                "was stopped.  This server runs with the 'small' config size limit, the one the public demo uses.  "
                "A Netcanon you run yourself allows 120 seconds by default."
            )}
            assert sock.recv(100) == b"", "the connection of a request that was ended was left open"
            sock.close()
            _until(lambda: L.places() == 0, "the place given back")
        lines = [record.getMessage() for record in caplog.records if "had not arrived" in record.getMessage()]
        assert lines == [
            f"the body of a request to {path} had not arrived when its 0.5 seconds (small limits) were up: "
            f"{len(some)} bytes of it had; answered 408, and its place given back"
        ]
        assert "NOT-FOR-THE-LOG" not in caplog.text and "cisco_ios" not in caplog.text

    def test_a_client_that_leaves_while_sending_gives_its_place_back(self, test_settings: Settings) -> None:
        """...at once, and not at the request's deadline twenty
        seconds on."""
        with _on_a_socket(test_settings) as port:
            sock = socket.create_connection(("127.0.0.1", port), timeout=10)
            sock.sendall(_head(port, "/api/v1/migration/plan", 2_000_000) + b"{")
            _until(lambda: L.places() == 1, "the request counted, its body still to come")
            began = time.monotonic()
            sock.close()
            _until(lambda: L.places() == 0, "the place given back when the client left", seconds=8.0)
            assert time.monotonic() - began < 8.0


# ---------------------------------------------------------------------------
# An answer nobody reads
# ---------------------------------------------------------------------------


class TestAnAnswerNobodyReads:
    """A turn that was lent to an answer was taken back at the
    request's deadline, and the answer stayed: megabytes that no
    client was reading, for as long as the connection was kept.  Four
    of the largest, twenty seconds apart, ended a demo instance.  At
    its request's deadline an answer that has not gone out is
    abandoned."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0) and L.places() == 0
        yield
        _until(lambda: L.in_flight() == (0, 0) and L.places() == 0, "every turn and every place given back")

    #: 100 trunks that allow every VLAN and 480 VLANs, to a target that
    #: reports each membership: nine megabytes of answer, which no
    #: socket buffer of a loopback connection takes whole.
    LARGE = json.dumps({"source": "cisco_nxos", "target": "opnsense", "raw_text": trunk_all(100, 480)}).encode()
    #: (9,296,754 since each OPNsense VLAN's name is a lossy path of the
    #: validation report: the rendered config did not change.)
    LENGTH = 9_296_754

    @staticmethod
    def _client_that_does_not_read(port: int) -> socket.socket:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65_536)
        sock.settimeout(30)
        sock.connect(("127.0.0.1", port))
        return sock

    def test_it_is_abandoned_at_its_requests_deadline(
        self, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Over a real socket, four seconds standing for the twenty.
        Until the deadline the answer holds the turn, and a second
        request waits behind it.  At the deadline the turn and the
        place come back, the second request is translated, the log
        says in counts what was let go -- and the client that reads
        at last finds part of an answer and the end of the
        connection."""
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=4.0))
        small = json.dumps(_PLAN).encode()
        with _on_a_socket(test_settings) as port, caplog.at_level(logging.WARNING):
            unread = self._client_that_does_not_read(port)
            began = time.monotonic()
            unread.sendall(_head(port, "/api/v1/migration/plan", len(self.LARGE)) + self.LARGE)
            _until(lambda: bool(L._TURNS._lent), "the work done, and the turn lent to the answer")
            assert (L.in_flight(), L.places()) == ((1, 0), 1)
            second = socket.create_connection(("127.0.0.1", port), timeout=30)
            second.sendall(_head(port, "/api/v1/migration/plan", len(small)) + small)
            _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
            assert time.monotonic() - began < 3.0, "this machine was too slow for the test to see the wait"
            status, _, answer = _read_answer(second)
            waited = time.monotonic() - began
            assert status == 200 and json.loads(answer)["status"] == "completed"
            assert 3.5 < waited < 20.0, f"the second request was answered {waited:.2f} s after the first was sent"
            second.close()
            _until(lambda: L.in_flight() == (0, 0) and L.places() == 0, "the unread answer's turn and place back")
            status, headers, got = _read_answer(unread)
            assert status == 200 and int(headers["content-length"]) == self.LENGTH
            assert len(got) < self.LENGTH - 1_000_000, "the answer nobody was reading was sent whole"
            unread.close()
        lines = [record.getMessage() for record in caplog.records if "was abandoned" in record.getMessage()]
        assert len(lines) == 1, lines
        said = re.fullmatch(
            r"an answer from /api/v1/migration/plan had not gone out when its request's 4 seconds \(small "
            r"limits\) were up, and was abandoned: (\d+) of 9,296,754 bytes had been handed to the client; the "
            r"rest was let go and the connection closed", lines[0],
        )
        assert said, lines[0]
        assert len(got) <= int(said[1]) < self.LENGTH - 1_000_000
        # Counts, a path and the name of the limits: nothing of the config or of the answer.
        assert "Ethernet1/1" not in caplog.text and "hostname" not in caplog.text

    def test_a_reader_inside_the_deadline_gets_all_of_it(
        self, test_settings: Settings, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A client that takes its time is not one that does not
        read: left unread for a second and then read a little at a
        time, well inside the twenty, the answer comes whole."""
        with _on_a_socket(test_settings) as port, caplog.at_level(logging.WARNING):
            reader = self._client_that_does_not_read(port)
            reader.sendall(_head(port, "/api/v1/migration/plan", len(self.LARGE)) + self.LARGE)
            _until(lambda: bool(L._TURNS._lent), "the work done, and the turn lent to the answer")
            time.sleep(1.0)
            assert L.in_flight() == (1, 0), "the turn came back with the answer unread"
            status, headers, got = _read_answer(reader)
            assert status == 200 and len(got) == int(headers["content-length"]) == self.LENGTH
            assert json.loads(got)["status"] == "partial"
            reader.close()
        assert not [record for record in caplog.records if "was abandoned" in record.getMessage()]


class _Wire:
    """A server, as the application sees one: what it was handed,
    and a client that reads only when the test says so.  ``send``
    returns at once until *takes* bytes of body are out, and then
    waits for the client -- as a server's does when its buffer is
    full."""

    def __init__(self, body: list[bytes] | None = None, takes: int | None = None) -> None:
        self.arriving: deque[dict[str, Any]] = deque(
            {"type": "http.request", "body": part, "more_body": n + 1 < len(body or [])}
            for n, part in enumerate(body or [])
        )
        self.takes, self.out = takes, 0
        self.handed: list[dict[str, Any]] = []
        self.reads = asyncio.Event()
        self.asked_for_the_body = 0
        #: Calls of ``send`` that are waiting for the client now -- and
        #: how many still were when the application had returned (read
        #: before the loop ends, which cancels whatever is left).
        self.waiting = 0
        self.left_waiting = -1

    async def receive(self) -> dict[str, Any]:
        self.asked_for_the_body += 1
        if self.arriving:
            return self.arriving.popleft()
        await asyncio.Event().wait()  # the client sends no more, and does not leave
        raise AssertionError("unreachable")

    async def send(self, message: dict[str, Any]) -> None:
        if self.takes is not None and self.out >= self.takes:
            self.waiting += 1
            try:
                await self.reads.wait()
            finally:
                self.waiting -= 1
        self.handed.append(message)
        self.out += len(message.get("body") or b"")

    def body(self) -> bytes:
        return b"".join(m.get("body") or b"" for m in self.handed if m["type"] == "http.response.body")

    def finished(self) -> bool:
        return bool(self.handed) and self.handed[-1]["type"] == "http.response.body" and not self.handed[-1].get(
            "more_body", False)


def _answering(*parts: bytes, after: float = 0.0, pause: float = 0.0, left: list[int] | None = None):
    """An application that reads its request's body and answers with
    *parts*, one message each, from a queue it empties as it sends
    (as a job's answer is), *pause* seconds apart.  *left* is told
    how many were not sent when it returned."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        while (await receive()).get("more_body", False):
            pass
        if after:
            await asyncio.sleep(after)
        pieces = deque(parts)
        try:
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-length", str(sum(map(len, parts))).encode())]})
            while pieces:
                piece = pieces.popleft()
                await send({"type": "http.response.body", "body": piece, "more_body": bool(pieces)})
                if pause:
                    await asyncio.sleep(pause)
        finally:
            if left is not None:
                left.append(len(pieces))

    return app


class TestTheMiddlewareAlone:
    """``AnswerSent`` between a server that this test plays and an
    application of a few lines: what it hands on, what it waits for,
    and until when -- with no socket, so that each case is exact."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0) and L.places() == 0
        yield
        assert L.in_flight() == (0, 0) and L.places() == 0, "a turn or a place was not given back"

    PATH = "/api/v1/migration/plan"

    @staticmethod
    def _run(app: Any, wire_of: Callable[[], _Wire], limits: Any, path: str, meanwhile: Any = None) -> _Wire:
        from netcanon.api.routes._migration_helpers import AnswerSent

        async def go() -> _Wire:
            wire = wire_of()
            call = asyncio.ensure_future(AnswerSent(app, limits=limits)(_plain_scope(path), wire.receive, wire.send))
            if meanwhile is not None:
                await meanwhile(wire)
            await asyncio.wait_for(call, 10)
            for _ in range(3):  # what was cancelled on the way out ends here
                await asyncio.sleep(0)
            wire.left_waiting = wire.waiting
            return wire

        return _alone(go())

    def test_an_answer_is_handed_to_the_server_a_piece_at_a_time(self) -> None:
        """A server takes whatever it is handed into its buffer at
        once.  Handed three megabytes whole, it would hold three
        megabytes that nobody could let go of, and "gone out" would
        mean "in the buffer"."""
        from netcanon.api.routes import _migration_helpers as helpers

        whole = bytes(range(256)) * 12_000
        wire = self._run(_answering(whole), lambda: _Wire([b"{}"]), "small", self.PATH)
        bodies = [m for m in wire.handed if m["type"] == "http.response.body"]
        assert wire.body() == whole and wire.finished()
        assert helpers.WRITE == 65_536 and len(bodies) == -(-len(whole) // helpers.WRITE)
        assert max(len(m["body"]) for m in bodies) == helpers.WRITE
        assert [m.get("more_body", False) for m in bodies] == [True] * (len(bodies) - 1) + [False]
        # A streamed answer, the last piece of which is not the end.
        wire = self._run(_answering(whole, b"tail"), lambda: _Wire([b"{}"]), "small", self.PATH)
        assert wire.body() == whole + b"tail" and wire.finished()
        assert sum(1 for m in wire.handed if not m.get("more_body", True)) == 1

    @pytest.mark.parametrize("limits, path", [
        ("standard", "/api/v1/migration/plan"), (None, "/api/v1/sanitize"), ("small", "/migrate"),
        ("small", "/api/v1/migration/inventory"), ("unlimited", "/api/v1/migration/plan"),
    ])
    def test_everything_else_passes_as_the_application_made_it(self, limits: str | None, path: str) -> None:
        """Under limits that do not say how many work at once, and
        for a request that reads no config text: the same messages,
        the server's own ``receive``, no deadline."""
        whole = b"x" * 300_000
        made: list[dict[str, Any]] = []
        answering = _answering(whole)

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            async def recording(message: dict[str, Any]) -> None:
                made.append(message)
                await send(message)

            await answering(scope, receive, recording)

        wire = self._run(app, lambda: _Wire([b"{}"]), limits, path)
        assert len(wire.handed) == len(made) == 2 and all(a is b for a, b in zip(wire.handed, made, strict=True))

    def test_an_answer_nobody_reads_is_abandoned_at_the_deadline(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The client takes 100,000 bytes and reads no more.  At the
        request's deadline (three tenths of a second) the application
        is told what it is told when a client leaves: it runs to its
        end, and lets go of every piece it had not sent.  Nothing more
        reaches the server, and the answer is left unfinished -- which
        is what makes a server close the connection."""
        parts = [bytes([n]) * 50_000 for n in range(40)]
        left: list[int] = []
        with caplog.at_level(logging.WARNING):
            began = time.monotonic()
            wire = self._run(
                _answering(*parts, left=left), lambda: _Wire([b"{}"], takes=100_000),
                replace(L.SMALL, seconds=0.3), self.PATH,
            )
            took = time.monotonic() - began
        assert 0.25 < took < 5.0, took
        assert left == [0], "the application did not run to its end and let go of what it held"
        assert wire.out == 100_000 and wire.body() == b"".join(parts[:2])
        assert not wire.finished(), "an answer that was abandoned was finished, and the connection left open"
        assert wire.left_waiting == 0, "the send that was given up is still waiting on the server"
        lines = [record.getMessage() for record in caplog.records if "was abandoned" in record.getMessage()]
        assert lines == [
            "an answer from /api/v1/migration/plan had not gone out when its request's 0.3 seconds (small "
            "limits) were up, and was abandoned: 100000 of 2,000,000 bytes had been handed to the client; the "
            "rest was let go and the connection closed"
        ]

    def test_nothing_more_is_sent_of_an_answer_that_was_abandoned(self) -> None:
        """...even when the client begins to read again while the
        application is still going through what was left.  The
        pieces in between were dropped: what would follow is an
        answer with a hole in it, under the length the whole one
        declared."""
        parts = [bytes([n]) * 50_000 for n in range(12)]

        async def reads_again(wire: _Wire) -> None:
            await asyncio.sleep(0.3)  # the deadline was at 0.15
            wire.takes = None
            wire.reads.set()

        wire = self._run(
            _answering(*parts, pause=0.05), lambda: _Wire([b"{}"], takes=100_000),
            replace(L.SMALL, seconds=0.15), self.PATH, reads_again,
        )
        assert wire.out == 100_000 and wire.body() == b"".join(parts[:2])
        assert not wire.finished()

    def test_a_reader_inside_the_deadline_gets_all_of_it(self, caplog: pytest.LogCaptureFixture) -> None:
        parts = [bytes([n]) * 50_000 for n in range(40)]

        async def reads_late(wire: _Wire) -> None:
            await asyncio.sleep(0.15)
            wire.takes = None
            wire.reads.set()

        with caplog.at_level(logging.WARNING):
            wire = self._run(
                _answering(*parts), lambda: _Wire([b"{}"], takes=100_000), replace(L.SMALL, seconds=5.0),
                self.PATH, reads_late,
            )
        assert wire.body() == b"".join(parts) and wire.finished()
        assert not caplog.records

    def test_an_answer_made_after_the_deadline_goes_as_far_as_it_goes_unwaited(self) -> None:
        """Only WAITING is bounded.  The refusal of a request that
        stood in the line for all its time is made at the deadline
        and sent just after it: a few hundred bytes, which a server
        takes at once.  A large answer made that late, to a client
        that does not read, stops where the server stops taking."""
        brief = replace(L.SMALL, seconds=0.2)
        wire = self._run(_answering(b'{"detail":"Refused: ..."}', after=0.4), lambda: _Wire([b"{}"]), brief, self.PATH)
        assert wire.body() == b'{"detail":"Refused: ..."}' and wire.finished()
        left: list[int] = []
        parts = [b"y" * 50_000] * 10
        wire = self._run(
            _answering(*parts, after=0.4, left=left), lambda: _Wire([b"{}"], takes=100_000), brief, self.PATH,
        )
        assert (wire.out, left, wire.finished()) == (100_000, [0], False)

    def test_a_body_that_does_not_come(self, caplog: pytest.LogCaptureFixture) -> None:
        """The application is told its client has gone, and what it
        makes of that is dropped; the answer is the middleware's own
        -- 408, in words, with the connection to be closed."""
        seen: list[str] = []

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            while True:
                message = await receive()
                seen.append(message["type"])
                if message["type"] == "http.disconnect":
                    break
            # What a framework answers to a body it could not read.
            await send({"type": "http.response.start", "status": 400, "headers": []})
            await send({"type": "http.response.body", "body": b"There was an error parsing the body"})

        with caplog.at_level(logging.WARNING):
            began = time.monotonic()
            wire = self._run(app, lambda: _Wire(None), replace(L.SMALL, seconds=0.2), self.PATH)
            took = time.monotonic() - began
        assert 0.15 < took < 3.0, f"the body was waited for {took:.2f} s; its request may take 0.2"
        assert seen == ["http.disconnect"]
        start, body = wire.handed
        assert start["status"] == 408 and (b"connection", b"close") in start["headers"]
        assert json.loads(body["body"])["detail"].startswith(
            "Refused: the request passed the 0.2 seconds it may take while its body was still arriving"
        )
        assert wire.finished()
        assert [record.getMessage() for record in caplog.records] == [
            "the body of a request to /api/v1/migration/plan had not arrived when its 0.2 seconds (small limits) "
            "were up: 0 bytes of it had; answered 408, and its place given back"
        ]

    def test_a_request_refused_a_place_is_answered_unread(self) -> None:
        reached: list[str] = []

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            reached.append(scope["path"])

        held = [L.Answer() for _ in range(3)]
        for answer in held:
            answer.arrived("small")
        try:
            wire = self._run(app, lambda: _Wire([b"{}"]), "small", self.PATH)
        finally:
            for answer in held:
                answer.sent()
        assert reached == [] and wire.asked_for_the_body == 0
        start, body = wire.handed
        assert start["status"] == 503 and (b"retry-after", b"5") in start["headers"]
        assert json.loads(body["body"])["detail"].startswith("Refused: the server works on one config at a time")

    def test_whatever_the_application_does_the_place_comes_back(self) -> None:
        async def raises(scope: dict[str, Any], receive: Any, send: Any) -> None:
            assert L.places() == 1
            raise RuntimeError("a fault in the application")

        with pytest.raises(RuntimeError, match="a fault in the application"):
            self._run(raises, lambda: _Wire([b"{}"]), "small", self.PATH)
        assert L.places() == 0

        async def refuses(scope: dict[str, Any], receive: Any, send: Any) -> None:
            raise L.LimitExceeded("ports", 9, 8, profile="small", hint="(hint)")

        # A refusal that got out of a handler is not swallowed, whatever became of the request.
        with pytest.raises(L.LimitExceeded):
            self._run(refuses, lambda: _Wire(None), replace(L.SMALL, seconds=0.1), self.PATH)
        assert L.places() == 0


# ---------------------------------------------------------------------------
# Out of time after a wait is busy
# ---------------------------------------------------------------------------


class TestOutOfTimeAfterAWaitIsBusy:
    """A request that needs three seconds, sent behind one that works
    for eighteen, got its turn with two and a half left -- and was
    refused as SLOW: ``refusal.limit`` ``seconds``, "a Netcanon you
    run yourself allows 120", 413 from the sanitiser.  Nothing was
    slow but the server.  A refusal for time that follows a wait says
    how long the request waited and is answered as busy, on every
    surface."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0) and L.places() == 0
        yield
        _until(lambda: L.in_flight() == (0, 0) and L.places() == 0, "every turn and every place given back")

    #: The seconds a request may take in these tests, and what its work
    #: is made to take before it reads a line.  The wait is a third of a
    #: second, so the request is out of time whatever the machine does,
    #: and has more than a second in which to be given its turn.
    SECONDS, WORK = 1.5, 1.4

    def _slow_work(self, monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
        """Every surface's work takes *seconds* before it reads a
        line -- as work does that began late on a busy machine."""
        from netcanon.api.routes import _migration_helpers as helpers
        from netcanon.api.routes import migration as migration_route
        from netcanon.api.routes import sanitize as sanitize_route

        def late(real: Callable[..., Any], looks: bool = False) -> Callable[..., Any]:
            def work(*args: Any, **kwargs: Any) -> Any:
                time.sleep(seconds)
                if looks:  # a probe reads a window and makes nothing: it stands for a loop that looks
                    scope = L._SCOPE.get()
                    assert scope is not None
                    scope.check_clock()
                return real(*args, **kwargs)
            return work

        monkeypatch.setattr(helpers, "run_plan_with_checked_names", late(helpers.run_plan_with_checked_names))
        monkeypatch.setattr(sanitize_route, "sanitize_text", late(sanitize_route.sanitize_text))
        monkeypatch.setattr(migration_route, "detect_codec", late(migration_route.detect_codec, looks=True))
        monkeypatch.setattr(migration_route, "propose_deployment", late(migration_route.propose_deployment))

    _WAITED = (
        r"the server works on one config at a time, and this request waited (\d+(?:\.\d)?) seconds for its turn; "
        r"what was left of the 1\.5 seconds it may take was not enough, and it was stopped"
    )

    @pytest.mark.parametrize("path", sorted(TAKES_CONFIG_TEXT))
    def test_on_every_surface(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str,
    ) -> None:
        assert path in _config_text_routes(small_client.app)
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=self.SECONDS))
        self._slow_work(monkeypatch, self.WORK)
        posts = _Posts(small_client)
        with _a_request_at_work():
            posts.send("late", path, **TAKES_CONFIG_TEXT[path])
            _until(lambda: L.in_flight() == (1, 1), "the request standing in the line")
            time.sleep(0.3)
        posts.all_answered()
        resp = posts.answers["late"]
        assert "passed the" not in resp.text and "allows 120" not in resp.text, resp.text[:300]
        assert "parse failed" not in resp.text and "unexpectedly" not in resp.text
        if path == "/api/v1/migration/detect-deployment":
            assert resp.status_code == 200
            said = resp.json()["notes"][-1]
            match = re.fullmatch(
                "The proposal was not checked against the port names the config uses: " + self._WAITED
                + r" before reading the config as aruba_aoss began\.  Send it again\.  " + re.escape(_BUSY_HINT), said,
            )
        elif path in ("/api/v1/sanitize", "/api/v1/migration/detect"):
            assert resp.status_code == 503 and resp.headers["Retry-After"] == "5", (resp.status_code, resp.text[:200])
            said = resp.json()["detail"]
            when = "" if path.endswith("/detect") else r" before reading the config as cisco_iosxe_cli began"
            match = re.fullmatch(
                "Refused: " + self._WAITED + when + r"\.  Send it again\.  " + re.escape(_BUSY_HINT), said,
            )
        else:
            job = resp.json()
            assert resp.status_code == 200 and resp.headers["X-Netcanon-Job-Status"] == "failed"
            assert (job["status"], job["rendered"], job["validation"]) == ("failed", None, None)
            refusal = job["refusal"]
            assert (refusal["limit"], refusal["asked"], refusal["cap"], refusal["exact"]) == ("at_once", 2, 1, True)
            assert (refusal["stage"], refusal["codec"], refusal["profile"]) == ("parse", "cisco_iosxe_cli", "small")
            assert refusal["how_to_raise"] == _BUSY_HINT
            said = job["error"]
            match = re.fullmatch(
                "refused: " + self._WAITED + r" before reading the config as cisco_iosxe_cli began\.  Send it "
                r"again\.  " + re.escape(_BUSY_HINT), said,
            )
        assert match, said
        assert 0.3 <= float(match[1]) <= self.SECONDS, said

    @pytest.mark.parametrize("path", sorted(TAKES_CONFIG_TEXT))
    def test_a_request_that_did_not_wait_is_refused_for_time_as_before(
        self, small_client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str,
    ) -> None:
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=self.SECONDS))
        self._slow_work(monkeypatch, self.SECONDS + 0.1)
        resp = small_client.post(path, **TAKES_CONFIG_TEXT[path])
        passed = "the request passed the 1.5 seconds it may take"
        assert "waited" not in resp.text and "Send it again" not in resp.text, resp.text[:300]
        if path == "/api/v1/migration/detect-deployment":
            assert resp.status_code == 200 and passed in resp.json()["notes"][-1]
        elif path in ("/api/v1/sanitize", "/api/v1/migration/detect"):
            assert resp.status_code == 413 and "Retry-After" not in resp.headers
            assert resp.json()["detail"].startswith("Refused: " + passed)
        else:
            job = resp.json()
            assert resp.status_code == 200 and job["refusal"]["limit"] == "seconds"
            assert job["error"].startswith("refused: " + passed + " before reading the config as cisco_iosxe_cli began")


# ---------------------------------------------------------------------------
# The connection of a client that takes nothing
# ---------------------------------------------------------------------------


class _Bound:
    """Stands for the socket a server's config binds: what was set on
    it."""

    def __init__(self, takes_the_option: bool = True) -> None:
        self.set: list[tuple[int, int, int]] = []
        self.takes_the_option = takes_the_option

    def setsockopt(self, level: int, option: int, value: int) -> None:
        if not self.takes_the_option:
            raise OSError("this system names the option and does not take it")
        self.set.append((level, option, value))


class _Binds:
    """Stands for a server's config: how often it was asked to bind."""

    def __init__(self, bound: _Bound | None = None) -> None:
        self.bound, self.binds = bound or _Bound(), 0

    def bind_socket(self) -> _Bound:
        self.binds += 1
        return self.bound


#: What Linux calls the option; set where this test runs on a system
#: that has none, so that the launcher's side is tested everywhere.
_USER_TIMEOUT = getattr(socket, "TCP_USER_TIMEOUT", 18)


class TestTheSystemEndsAConnectionNobodyReads:
    """An abandoned answer's connection is closed by the server only
    when what was already written has been taken, and a client that
    takes nothing keeps it -- with megabytes the system holds for it.
    Twenty-one such connections were the whole memory of a demo
    instance.  The system can end one: a launcher starts a server
    under limits that say how many requests work at once on a socket
    that asks it to (``listening_sockets``)."""

    @pytest.fixture()
    def the_option(self, monkeypatch: pytest.MonkeyPatch) -> int:
        from netcanon.api.routes import _migration_helpers as helpers

        monkeypatch.setattr(helpers.socket, "TCP_USER_TIMEOUT", _USER_TIMEOUT, raising=False)
        return _USER_TIMEOUT

    def test_under_small_the_socket_is_bound_here_and_asks_for_it(self, the_option: int) -> None:
        from netcanon.api.routes._migration_helpers import listening_sockets

        config = _Binds()
        assert listening_sockets(config, "small") == [config.bound] and config.binds == 1
        # The seconds a request may take, in the milliseconds the option is in.
        assert config.bound.set == [(socket.IPPROTO_TCP, the_option, 20_000)] and L.SMALL.seconds == 20
        other = _Binds()
        assert listening_sockets(other, replace(L.SMALL, seconds=7.5)) == [other.bound]
        assert other.bound.set == [(socket.IPPROTO_TCP, the_option, 7_500)]

    @pytest.mark.parametrize("limits", ["standard", "large", "unlimited", None])
    def test_under_any_other_limits_the_server_binds_its_own(self, the_option: int, limits: str | None) -> None:
        from netcanon.api.routes._migration_helpers import listening_sockets

        config = _Binds()
        assert listening_sockets(config, limits) is None
        assert config.binds == 0 and config.bound.set == []

    def test_on_a_system_without_the_option_nothing_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from netcanon.api.routes import _migration_helpers as helpers

        monkeypatch.delattr(helpers.socket, "TCP_USER_TIMEOUT", raising=False)
        config = _Binds()
        assert helpers.listening_sockets(config, "small") is None and config.binds == 0

    def test_a_system_that_refuses_the_option_still_gets_a_server(
        self, the_option: int, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from netcanon.api.routes._migration_helpers import listening_sockets

        config = _Binds(_Bound(takes_the_option=False))
        with caplog.at_level(logging.WARNING):
            assert listening_sockets(config, "small") == [config.bound]
        assert [record.getMessage() for record in caplog.records] == [
            "the listening socket did not take TCP_USER_TIMEOUT (OSError): a connection whose client reads "
            "nothing is kept until the client lets go"
        ]

    @pytest.mark.skipif(not hasattr(socket, "TCP_USER_TIMEOUT"), reason="the option is Linux's")
    def test_a_connection_accepted_from_it_has_the_option_too(self) -> None:
        """On a system that has it, with a real socket: what is set
        on the listening socket is what every connection gets."""
        import uvicorn

        from netcanon.api.routes._migration_helpers import listening_sockets

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = uvicorn.Config(FastAPI(), host="127.0.0.1", port=port, log_level="critical")
        (listening,) = listening_sockets(config, "small") or [None]
        try:
            assert listening.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == 20_000
            listening.listen(1)
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                accepted, _ = listening.accept()
                with accepted:
                    assert accepted.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == 20_000
        finally:
            listening.close()
