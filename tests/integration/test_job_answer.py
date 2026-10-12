"""A job's answer is written a piece at a time -- and is the answer the framework would send.

The seven endpoints that return a job do not hand the job to the
framework to be made into an answer.  The framework's way is five
passes over it (the model to a dict, the dict validated into a second
model, that model to JSON-ready values, those to a string, the string
to bytes), and a job's validation report has a path for every
membership: the answer to the largest job the ``small`` limits admit
is 38 MB, and made that way it cost more memory than the translation
did.  ``_migration_helpers.job_answer`` writes the job straight to
JSON, a field or a run of a long list at a time.

What must not move is a byte of what a client receives.  So the oracle
here is the framework itself: a route that returns the same job with
``response_model=MigrationJob``, as the handlers used to.  Compared,
job by job:

* every committed capture translated to three targets, and jobs of the
  kinds a capture does not make -- refused, failed, with a port
  pairing, with every list long enough to be written in runs;
* the answer as the real endpoints send it, headers included, small
  (one body) and large (piece by piece, the same ``Content-Length``)
  -- and, since the bytes a client receives are the same either way,
  WHICH way it went, read where a server stands: the messages the
  application hands over.

And one thing about cost, which is what this is for: no piece of a
large answer is more than a run of one list.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, field_serializer

from netcanon.api.routes import _migration_helpers as helpers
from netcanon.config import Settings
from netcanon.main import create_app
from netcanon.migration import limits as L
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import (
    LossyPath,
    MigrationJob,
    MigrationJobStatus,
    Refusal,
    UnsupportedPath,
    ValidationReport,
)
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL = REPO_ROOT / "tests" / "fixtures" / "real"

CAPTURE_2930F = (REAL / "aruba_aoss" / "hpe_community_2930f_wc1607_intervlan.cfg").read_text(encoding="utf-8")
SOURCE_2930F = {"mode": "standalone", "members": [{"model": "JL260A"}]}
TARGET_2930M = {"mode": "stacked", "members": [{"model": "JL322A", "modules": {"A": "JL083A"}}]}


def trunk_all(ports: int, vlans: int) -> str:
    """NX-OS: *ports* trunks that allow every VLAN, *vlans* declared VLANs."""
    out = ["hostname T", ""]
    for vid in range(2, 2 + vlans):
        out += [f"vlan {vid}", f"  name V{vid}"]
    for port in range(ports):
        out += [f"interface Ethernet{port // 48 + 1}/{port % 48 + 1}", "  switchport",
                "  switchport mode trunk", "  switchport trunk allowed vlan all"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# The oracle: the framework, handed the job
# ---------------------------------------------------------------------------


class _Framework:
    """A route that returns whatever job it is holding, the way the
    handlers did: ``response_model=MigrationJob`` and a returned
    model."""

    def __init__(self) -> None:
        app = FastAPI()
        self.job: MigrationJob | None = None

        @app.post("/job", response_model=MigrationJob)
        def job() -> Any:
            return self.job

        self.client = TestClient(app)

    def sends(self, job: MigrationJob) -> bytes:
        self.job = job
        resp = self.client.post("/job")
        assert resp.status_code == 200 and resp.headers["content-type"] == "application/json"
        assert int(resp.headers["content-length"]) == len(resp.content)
        return resp.content


@pytest.fixture(scope="module")
def framework() -> _Framework:
    return _Framework()


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


def _written(job: MigrationJob) -> bytes:
    return b"".join(helpers.json_pieces(job))


def _captures() -> list[tuple[str, str, str]]:
    found = []
    for folder, codec in sorted(DIR_TO_CODEC_NAME.items()):
        for path in sorted((REAL / folder).glob("*")):
            if path.is_file() and path.suffix not in (".md", ".json", ".yaml"):
                found.append((f"{folder}/{path.name}", codec, path.read_text(encoding="utf-8")))
    return found


# ---------------------------------------------------------------------------
# Job by job
# ---------------------------------------------------------------------------


class TestTheBytesAreTheFrameworks:
    def test_every_capture_to_three_targets(self, framework: _Framework) -> None:
        targets = list_public_codecs()
        captures = _captures()
        assert len(captures) > 80 and len(targets) > 10
        compared = 0
        statuses: set[str] = set()
        for n, (label, source, text) in enumerate(captures):
            for k in range(3):
                target = targets[(n + k * 4) % len(targets)]
                with L.limits_scope("standard"):
                    job = run_plan_with_overrides(get_codec(source), get_codec(target), text, port_rename_map={})
                assert _written(job) == framework.sends(job), f"{label} -> {target}"
                statuses.add(job.status.value)
                compared += 1
        assert compared == 3 * len(captures)
        assert {"completed", "partial"} <= statuses

    def test_the_kinds_of_job_a_capture_does_not_make(self, framework: _Framework) -> None:
        refused = L.LimitExceeded("seconds", 20.5, 20.0, exact=True, stage="parse", codec="vyos", profile="small",
                                  hint="(hint)")
        busy = L._busy(L.SMALL, 2, 20.0)
        jobs = {
            "fresh": MigrationJob(source_codec="a", target_codec="b"),
            "failed to parse": run_plan_with_overrides(
                get_codec("opnsense"), get_codec("juniper_junos"), "<opnsense><unclosed>", port_rename_map={}),
            "refused for size": run_plan_with_overrides(
                get_codec("aruba_aoss"), get_codec("cisco_iosxe_cli"),
                'hostname "T"\nvlan 3\n   tagged ' + ",".join(f"{n * 2000 + 1}-{n * 2000 + 1001}" for n in range(40))
                + "\n   exit\n", port_rename_map={}),
            "refused for time, a float": MigrationJob(
                source_codec="vyos", target_codec="vyos", status=MigrationJobStatus.failed,
                error=f"refused: {refused}", refusal=Refusal(**refused.as_dict())),
            "refused as busy": MigrationJob(
                source_codec="a", target_codec="b", status=MigrationJobStatus.failed,
                error=f"refused: {busy}", refusal=Refusal(**busy.as_dict())),
            "not ASCII": MigrationJob(
                source_codec="a", target_codec="b", rendered='hostname "caf\u00e9 \u2014 \u6771\u4eac"\n\t"\\x"\n',
                warnings=["\u00fcber", "line\nbreak", "\x00\x1f"], vlan_renames={10: 20, 4094: 1},
                port_renames={"1/A1": "ge-0/0/0"}),
        }
        assert jobs["refused for size"].refusal is not None and jobs["failed to parse"].error.startswith("parse failed")
        for label, job in jobs.items():
            assert _written(job) == framework.sends(job), label

    def test_a_job_with_a_port_pairing(self, framework: _Framework) -> None:
        """Nested models, lists of models, and optional models that
        are there: the job of a request that declares both devices."""
        with TestClient(create_app(Settings())) as client:
            body = client.post("/api/v1/migration/plan", json={
                "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": CAPTURE_2930F,
                "source_deployment": SOURCE_2930F, "target_deployment": TARGET_2930M,
            }).content
        job = MigrationJob.model_validate_json(body)
        assert job.port_mapping_plan is not None and job.port_mapping_plan.applied and job.port_renames
        assert body == framework.sends(job) == _written(job)

    @pytest.mark.parametrize("run", [1, 2, 3, 7, 2_000])
    def test_a_long_list_is_written_in_runs(
        self, framework: _Framework, monkeypatch: pytest.MonkeyPatch, run: int,
    ) -> None:
        """Lists of every length round the length of a run: empty,
        one entry, a run exactly, a run and one more, several runs --
        of strings and of models."""
        monkeypatch.setattr(helpers, "LIST_RUN", run)
        for length in (0, 1, run - 1, run, run + 1, 2 * run, 2 * run + 1, 5 * run + 3):
            job = MigrationJob(
                source_codec="a", target_codec="b",
                warnings=[f"w{n}" for n in range(length)],
                source_vlans=list(range(length)),
                validation=ValidationReport(
                    compatible=False, severity="block",
                    supported_paths=[f"/interfaces/interface[name={n}]" for n in range(length)],
                    lossy_paths=[LossyPath(path=f"/l/{n}", reason="r", severity="error") for n in range(length)],
                    unsupported_paths=[UnsupportedPath(path=f"/u/{n}", reason=None) for n in range(length)],
                ),
            )
            pieces = list(helpers.json_pieces(job))
            assert b"".join(pieces) == framework.sends(job), (run, length)
            if length > run:
                assert len(pieces) > 5 * (length // run), "the long lists were written whole"

    def test_a_model_with_a_serializer_of_its_own_is_written_whole(self) -> None:
        """Field by field is only right for a model whose JSON is its
        fields' JSON.  One that writes itself another way is handed to
        its own serializer -- here, and when it is nested."""

        class Loud(BaseModel):
            name: str

            @field_serializer("name")
            def shout(self, value: str) -> str:
                return value.upper()

        class Configured(BaseModel):
            model_config = ConfigDict(ser_json_inf_nan="constants")
            ratio: float

        class Outer(BaseModel):
            first: Loud
            second: Configured
            third: list[Loud]

        assert not helpers._is_written_field_by_field(Loud) and not helpers._is_written_field_by_field(Configured)
        assert helpers._is_written_field_by_field(Outer) and helpers._is_written_field_by_field(MigrationJob)
        outer = Outer(first=Loud(name="a"), second=Configured(ratio=float("inf")), third=[Loud(name="b")])
        assert b"".join(helpers.json_pieces(outer)) == outer.model_dump_json().encode() == (
            b'{"first":{"name":"A"},"second":{"ratio":Infinity},"third":[{"name":"B"}]}'
        )


# ---------------------------------------------------------------------------
# As the endpoints send it
# ---------------------------------------------------------------------------

JOB_ENDPOINTS = ("/plan", "/plan/ports", "/plan/vlans", "/plan/local_users", "/plan/snmp", "/plan/snmpv3", "/render")


class _Handed:
    """Stands where a server stands, between the test's client and
    the application: the size of every body the application hands
    over for an answer, in order."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.bodies: list[int] = []
        self.client: TestClient

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def recording(message: Any) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                self.bodies.append(len(message["body"]))
            await send(message)

        await self.app(scope, receive, recording)


class TestAsTheEndpointsSendIt:
    @pytest.fixture(scope="class")
    def client(self):
        with TestClient(create_app(Settings())) as c:
            yield c

    @pytest.fixture(scope="class")
    def handed(self):
        between = _Handed(create_app(Settings()))
        with TestClient(between) as c:
            between.client = c
            yield between

    @pytest.fixture()
    def written(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """The jobs the piecewise writer was handed, by id.  The bytes
        of an answer cannot say who wrote them -- they are the
        framework's either way -- so a handler that went back to
        returning the job would pass every comparison here."""
        seen: list[str] = []
        real = helpers.json_pieces

        def recording(model: BaseModel):
            if isinstance(model, MigrationJob):
                seen.append(model.id)
            return real(model)

        monkeypatch.setattr(helpers, "json_pieces", recording)
        return seen

    @pytest.mark.parametrize("path", JOB_ENDPOINTS)
    def test_an_ordinary_job_is_one_body(
        self, client: TestClient, framework: _Framework, written: list[str], path: str,
    ) -> None:
        resp = client.post(f"/api/v1/migration{path}", json={
            "source": "aruba_aoss", "target": "juniper_junos", "raw_text": CAPTURE_2930F,
        })
        assert resp.status_code == 200
        job = MigrationJob.model_validate_json(resp.content)
        assert written == [job.id], "the handler did not write its answer with job_answer"
        assert resp.content == framework.sends(job)
        assert len(resp.content) < helpers.WHOLE_ANSWER
        assert resp.headers["content-type"] == "application/json"
        assert int(resp.headers["content-length"]) == len(resp.content)
        assert "transfer-encoding" not in resp.headers
        assert resp.headers["X-Netcanon-Job-Status"] == job.status.value
        # The headers every answer of the application carries are still put on.
        assert resp.headers["X-Content-Type-Options"] == "nosniff" and resp.headers["X-Request-ID"]

    @pytest.mark.parametrize("path", JOB_ENDPOINTS)
    def test_a_large_job_goes_piece_by_piece_and_is_the_same(
        self, client: TestClient, framework: _Framework, written: list[str], path: str,
    ) -> None:
        """48 trunks that allow every VLAN and 500 VLANs, to a target
        that reports each membership: megabytes of answer, in runs."""
        resp = client.post(f"/api/v1/migration{path}", json={
            "source": "cisco_nxos", "target": "opnsense", "raw_text": trunk_all(48, 500),
        })
        assert resp.status_code == 200
        assert len(resp.content) > helpers.WHOLE_ANSWER, "the job was expected to be past one body"
        job = MigrationJob.model_validate_json(resp.content)
        assert written == [job.id], "the handler did not write its answer with job_answer"
        paths = job.validation.supported_paths + job.validation.lossy_paths + job.validation.unsupported_paths
        assert len(paths) > 10 * helpers.LIST_RUN
        assert resp.content == framework.sends(job)
        assert resp.headers["content-type"] == "application/json"
        assert int(resp.headers["content-length"]) == len(resp.content)
        assert "transfer-encoding" not in resp.headers
        assert resp.headers["X-Netcanon-Job-Status"] == job.status.value == "partial"
        assert json.loads(resp.content)["id"] == job.id

    @pytest.mark.parametrize("path", JOB_ENDPOINTS)
    def test_which_of_the_two_is_read_where_a_server_stands(self, handed: _Handed, path: str) -> None:
        """The two tests above compare bytes, and the bytes are the
        same whether an answer went as one body or in pieces.  What
        differs is what the server is handed: for an ordinary job
        ONE body, as ever -- nothing about an ordinary request has
        changed -- and for a large one many, none of them much of
        the whole."""
        ordinary = handed.client.post(f"/api/v1/migration{path}", json={
            "source": "aruba_aoss", "target": "juniper_junos", "raw_text": CAPTURE_2930F,
        })
        assert ordinary.status_code == 200 and len(ordinary.content) < helpers.WHOLE_ANSWER
        assert handed.bodies == [len(ordinary.content)], (
            f"an ordinary job went to the server in {len(handed.bodies)} pieces"
        )
        handed.bodies.clear()
        large = handed.client.post(f"/api/v1/migration{path}", json={
            "source": "cisco_nxos", "target": "opnsense", "raw_text": trunk_all(48, 500),
        })
        assert large.status_code == 200 and len(large.content) > helpers.WHOLE_ANSWER
        assert sum(handed.bodies) == len(large.content)
        assert len(handed.bodies) > 10, "a large job went to the server as one body"
        assert max(handed.bodies) < len(large.content) / 5
        handed.bodies.clear()

    def test_and_by_what_job_answer_returns(self) -> None:
        """The same, one step earlier: a response with its body, or
        one that is sent as it is iterated -- decided by the size of
        the answer, at ``WHOLE_ANSWER`` exactly."""
        job = MigrationJob(source_codec="a", target_codec="b")
        size = len(_written(job))
        one = helpers.job_answer(job, Response())
        assert not isinstance(one, StreamingResponse) and one.body == _written(job)
        job.rendered = "x" * (helpers.WHOLE_ANSWER - size + len("null") - 2)
        assert len(_written(job)) == helpers.WHOLE_ANSWER
        assert not isinstance(helpers.job_answer(job, Response()), StreamingResponse)
        job.rendered += "x"
        pieces = helpers.job_answer(job, Response())
        assert isinstance(pieces, StreamingResponse)
        assert pieces.headers["content-length"] == str(helpers.WHOLE_ANSWER + 1)

    def test_the_schema_still_says_what_is_returned(self, client: TestClient) -> None:
        """The handlers return a response now, and still declare the
        model: a generated client reads the same schema."""
        schema = client.get("/api/v1/openapi.json").json()
        for path in JOB_ENDPOINTS:
            ok = schema["paths"][f"/api/v1/migration{path}"]["post"]["responses"]["200"]
            assert ok["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/MigrationJob"}, path
            assert "X-Netcanon-Job-Status" in ok["headers"]


# ---------------------------------------------------------------------------
# What it is for
# ---------------------------------------------------------------------------


class TestNoPieceIsLarge:
    def test_the_largest_piece_is_a_run(self) -> None:
        """What bounds the memory an answer takes while it is written
        is the size of a piece: the writer's buffer doubles as it
        grows and is then copied out, so a piece costs about three
        times its size for a moment.  Of a job with 60,000 reported
        paths -- megabytes of JSON -- no piece is more than a run of
        one list."""
        job = MigrationJob(
            source_codec="a", target_codec="b",
            validation=ValidationReport(
                compatible=False, severity="block",
                unsupported_paths=[
                    UnsupportedPath(path=f"/vlans/vlan[id={n % 4000}]/tagged-ports/port[name=Ethernet1/{n}]",
                                    reason="the target has no such record") for n in range(60_000)
                ],
            ),
        )
        pieces = list(helpers.json_pieces(job))
        size = sum(map(len, pieces))
        assert size > 6_000_000 and b"".join(pieces) == job.model_dump_json(by_alias=True).encode("utf-8")
        assert helpers.LIST_RUN == 2_000
        assert max(map(len, pieces)) < size / 25, "a list of 60,000 entries was written in one piece"
        assert len(pieces) >= 30

    def test_pieces_that_were_not_sent_are_let_go(self) -> None:
        """An answer whose sending stops before its end -- the client
        left, or the answer was abandoned at its request's deadline
        -- lets go of what it had not sent THEN, and not when
        whatever still holds the response is collected."""
        pieces = deque([b"a" * 10, b"b" * 10, b"c" * 10])

        async def stopped_after_one() -> list[bytes]:
            sending = helpers._sent_and_let_go(pieces)
            got = [await sending.__anext__()]
            assert len(pieces) == 2, "a piece is let go of as it is handed over"
            await sending.aclose()
            return got

        assert _alone(stopped_after_one()) == [b"a" * 10]
        assert not pieces, "the pieces that were never sent were kept"

        async def to_the_end(queue: deque[bytes]) -> list[bytes]:
            return [piece async for piece in helpers._sent_and_let_go(queue)]

        queue = deque([b"x", b"y"])
        assert _alone(to_the_end(queue)) == [b"x", b"y"] and not queue
