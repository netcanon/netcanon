"""The config size limit on the desktop platform.

The web platform sets it with ``NETCANON_CONFIG_LIMITS``; a desktop
operator has no environment to set, so the twin is a field in
Preferences.  Parity is four things, and each has a test here or beside
the dialog's own (``test_preferences_dialog.py``):

* the preference exists, with the web platform's default, and survives
  the file it is kept in;
* ``desktop_settings()`` hands it to the server's settings;
* the embedded server runs under it -- shown by what the server does
  with a config that one setting translates and another refuses;
* the refusal that server gives names the Preferences dialog;
* the part of the limits that says how many requests work at once
  reaches the embedded server like the rest: by default (``standard``)
  nothing waits -- one user at a desktop has nobody to wait behind --
  and ``small`` in the preferences file makes a second request wait
  its turn there too;
* so does the place a request is given when it arrives: by default
  the embedded server counts nothing and reads every body, and under
  ``small`` a request that finds every place taken is answered 503
  with its body unread;
* and the socket the embedded server is started on is asked for as
  ``netcanon serve`` asks: by default the server binds its own, and
  under ``small``, on a system that has the option, one on which the
  system ends a connection whose client takes nothing.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.definitions import LIBRARY_DIR
from netcanon.main import create_app
from netcanon.migration import limits as L
from netcanon_desktop.preferences import DesktopPreferences
from netcanon_desktop.server import ServerThread
from netcanon_desktop.settings import desktop_settings
from tests.conftest import FakeCollector

pytestmark = pytest.mark.desktop

#: One AOS-S stanza of 40 port ranges: 520 bytes that name 40,040 ports.
AOSS_RANGES = 'hostname "T"\nvlan 10\n   name "V10"\n   tagged ' + ",".join(
    f"{n * 2000 + 1}-{n * 2000 + 1001}" for n in range(40)
) + "\n   exit\n"


def _installed(tmp_path: Path, preferences: dict | None) -> Settings:
    """The settings of an installed desktop application whose
    ``preferences.json`` holds *preferences* (``None``: no file)."""
    install = tmp_path / "install"
    install.mkdir(parents=True)
    shutil.copytree(LIBRARY_DIR, install / "definitions")
    appdata = tmp_path / "AppData" / "Roaming"
    (appdata / "Netcanon").mkdir(parents=True)
    if preferences is not None:
        (appdata / "Netcanon" / "preferences.json").write_text(json.dumps(preferences), encoding="utf-8")
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(install / "netcanon.exe")),
        patch.dict(os.environ, {"APPDATA": str(appdata)}),
    ):
        return desktop_settings()


class TestThePreference:
    def test_the_default_is_the_web_platforms(self) -> None:
        assert DesktopPreferences().config_limits == "standard" == Settings.model_fields["config_limits"].default

    def test_it_takes_the_names_the_web_platform_takes(self) -> None:
        for name in ("small", "standard", "large", "unlimited"):
            assert DesktopPreferences(config_limits=name).config_limits == name
            assert Settings(config_limits=name).config_limits == name
        with pytest.raises(ValueError):
            DesktopPreferences(config_limits="none")

    def test_it_survives_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "preferences.json"
        DesktopPreferences(config_limits="large").save(path)
        assert json.loads(path.read_text(encoding="utf-8"))["config_limits"] == "large"
        assert DesktopPreferences.load(path).config_limits == "large"

    def test_an_older_file_loads_with_the_default(self, tmp_path: Path) -> None:
        path = tmp_path / "preferences.json"
        path.write_text(json.dumps({"port": 9100}), encoding="utf-8")
        prefs = DesktopPreferences.load(path)
        assert (prefs.port, prefs.config_limits) == (9100, "standard")


class TestDesktopSettingsPassItOn:
    def test_from_the_preferences_file(self, tmp_path: Path) -> None:
        assert _installed(tmp_path, {"config_limits": "large"}).config_limits == "large"

    def test_with_no_file_it_is_the_default(self, tmp_path: Path) -> None:
        assert _installed(tmp_path, None).config_limits == "standard"

    def test_the_desktop_takes_it_from_preferences(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One place sets it on each platform.  A variable left in the
        environment of the user's session does not change what the
        dialog shows as in force."""
        monkeypatch.setenv("NETCANON_CONFIG_LIMITS", "unlimited")
        assert _installed(tmp_path, {"config_limits": "large"}).config_limits == "large"
        with patch.object(sys, "frozen", False, create=True):
            assert desktop_settings().config_limits == "standard"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _plan(settings: Settings, text: str) -> dict:
    """Post *text* to the embedded server of a desktop application
    that runs with *settings*; the job."""
    port = _free_port()
    body = json.dumps({"source": "aruba_aoss", "target": "aruba_aoss", "raw_text": text}).encode("utf-8")
    with patch("netcanon.api.routes.backups.get_collector", return_value=FakeCollector(output="! noop\n")):
        server = ServerThread(create_app(settings), port=port, log_level="critical")
        server.start()
        try:
            server.wait_ready(timeout=10.0)
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/v1/migration/plan", data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=60) as resp:
                assert resp.status == 200
                return json.loads(resp.read().decode("utf-8"))
        finally:
            server.stop()
            server.join(timeout=5.0)


class TestItReachesTheEmbeddedServer:
    """By behaviour: the same config, through the server the desktop
    window talks to, under two values of the preference."""

    def test_the_default_refuses_and_names_the_dialog(self, tmp_path: Path) -> None:
        job = _plan(_installed(tmp_path, None), AOSS_RANGES)
        assert job["status"] == "failed" and job["refusal"]["limit"] == "ports"
        assert (job["refusal"]["profile"], job["refusal"]["cap"]) == ("standard", 8192)
        assert job["error"].startswith("refused: reading the config as aruba_aoss would make 9,009 or more")
        assert "in the desktop application, choose Preferences... -> Config size limit." in job["error"]

    def test_unlimited_translates_the_same_config(self, tmp_path: Path) -> None:
        job = _plan(_installed(tmp_path, {"config_limits": "unlimited"}), AOSS_RANGES)
        assert job["refusal"] is None and job["status"] != "failed", job["error"]
        assert "tagged 1-1001," in job["rendered"]

    def test_small_in_a_file_edited_by_hand_is_honoured(self, tmp_path: Path) -> None:
        """Three ranges are 3,003 ports: under ``standard``, over
        ``small``."""
        text = AOSS_RANGES.replace(",".join(f"{n * 2000 + 1}-{n * 2000 + 1001}" for n in range(40)),
                                   "1-1001,2001-3001,4001-5001")
        assert _plan(_installed(tmp_path / "a", None), text)["refusal"] is None
        job = _plan(_installed(tmp_path / "b", {"config_limits": "small"}), text)
        assert (job["refusal"]["limit"], job["refusal"]["profile"], job["refusal"]["cap"]) == ("ports", "small", 2048)


# ---------------------------------------------------------------------------
# Requests at once
# ---------------------------------------------------------------------------

SMALL_CONFIG = 'hostname "T"\nvlan 10\n   name "V10"\n   tagged 1-4\n   exit\n'


def _until(condition: Callable[[], bool], what: str, seconds: float = 10.0) -> None:
    """Wait for *condition*, which another thread is on its way to
    making true.  The time is how long a FAILURE takes to be reported."""
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.002)


class _Work:
    """Stands in front of the pipeline: the first call says that it
    began and waits to be let go; every call is counted, and so is the
    most that were inside at once."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from netcanon.api.routes import _migration_helpers as helpers

        self.real = helpers.run_plan_with_checked_names
        self.began, self.let_go = threading.Event(), threading.Event()
        self.calls = self.inside = self.most = 0
        self._lock = threading.Lock()
        monkeypatch.setattr(helpers, "run_plan_with_checked_names", self)

    def __call__(self, *args, **kwargs):
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


@contextmanager
def _embedded_port(settings: Settings) -> Iterator[int]:
    """The embedded server of a desktop application that runs with
    *settings*; the port it listens on."""
    port = _free_port()
    with patch("netcanon.api.routes.backups.get_collector", return_value=FakeCollector(output="! noop\n")):
        server = ServerThread(create_app(settings), port=port, log_level="critical")
        server.start()
        try:
            server.wait_ready(timeout=10.0)
            yield port
        finally:
            server.stop()
            server.join(timeout=5.0)


def _half_sent(port: int) -> socket.socket:
    """A translation request whose head and first byte have been
    sent, and nothing more."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    sock.sendall((
        f"POST /api/v1/migration/plan HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        "Content-Type: application/json\r\nContent-Length: 2000000\r\n\r\n{"
    ).encode())
    return sock


@contextmanager
def _embedded(settings: Settings) -> Iterator[Callable[[], dict]]:
    """The embedded server of a desktop application that runs with
    *settings*; what is yielded posts one small translation to it and
    returns the job."""
    port = _free_port()
    body = json.dumps({"source": "aruba_aoss", "target": "aruba_aoss", "raw_text": SMALL_CONFIG}).encode("utf-8")

    def post() -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/migration/plan", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as resp:
            assert resp.status == 200
            return json.loads(resp.read().decode("utf-8"))

    with patch("netcanon.api.routes.backups.get_collector", return_value=FakeCollector(output="! noop\n")):
        server = ServerThread(create_app(settings), port=port, log_level="critical")
        server.start()
        try:
            server.wait_ready(timeout=10.0)
            yield post
        finally:
            server.stop()
            server.join(timeout=5.0)


class TestRequestsAtOnceOnTheDesktop:
    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0)
        yield
        _until(lambda: L.in_flight() == (0, 0), "every turn given back")

    def test_by_default_nothing_waits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The desktop's default is ``standard``, which limits no
        requests at once: with one translation held inside the
        pipeline, a second is answered."""
        settings = _installed(tmp_path, None)
        assert settings.config_limits == "standard" and L.PROFILES[settings.config_limits].at_once is None
        work = _Work(monkeypatch)
        with _embedded(settings) as post:
            answers: dict[str, dict] = {}
            first = threading.Thread(target=lambda: answers.update(first=post()), daemon=True)
            first.start()
            assert work.began.wait(10)
            assert post()["status"] == "completed" and first.is_alive()
            assert (work.calls, work.most) == (2, 2) and L.in_flight() == (0, 0)
            work.let_go.set()
            first.join(30)
            assert answers["first"]["status"] == "completed"

    def test_by_default_a_request_is_not_counted_at_its_arrival(self, tmp_path: Path) -> None:
        """Five requests that have sent their heads and no more:
        under the default none takes a place, and a sixth is
        translated."""
        settings = _installed(tmp_path, None)
        with _embedded_port(settings) as port:
            waiting = [_half_sent(port) for _ in range(5)]
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/v1/migration/plan",
                    data=json.dumps({"source": "aruba_aoss", "target": "aruba_aoss",
                                     "raw_text": SMALL_CONFIG}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(request, timeout=30) as resp:
                    assert json.loads(resp.read())["status"] == "completed"
                assert L.places() == 0
            finally:
                for sock in waiting:
                    sock.close()

    def test_small_in_the_preferences_file_counts_it_there_too(self, tmp_path: Path) -> None:
        """Three that have sent their heads hold the three places;
        the fourth is answered 503 at once, before its body."""
        settings = _installed(tmp_path, {"config_limits": "small"})
        with _embedded_port(settings) as port:
            waiting = [_half_sent(port) for _ in range(3)]
            try:
                _until(lambda: L.places() == 3, "three requests counted at their arrival")
                began = time.monotonic()
                fourth = _half_sent(port)
                fourth.settimeout(10)
                answer = ""
                while not answer.endswith("}"):  # the head, and then the body
                    piece = fourth.recv(65536).decode("latin-1")
                    assert piece, f"the connection ended before the answer did: {answer!r}"
                    answer += piece
                fourth.close()
                assert time.monotonic() - began < 5.0
                assert answer.startswith("HTTP/1.1 503 ") and "retry-after: 5" in answer.lower()
                assert "Refused: the server works on one config at a time, and 2 more were already" in answer
            finally:
                for sock in waiting:
                    sock.close()
            _until(lambda: L.places() == 0, "the places given back when the clients left")

    def test_the_embedded_server_is_started_as_netcanon_serve_is(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The desktop hands its config limits to the same helper
        the web platform's launcher uses.  By default that binds
        nothing; under ``small``, with the option the helper looks
        for present, the server is started on a socket bound for
        it -- and serves."""
        from netcanon.api.routes import _migration_helpers as helpers
        from netcanon_desktop import server as embedded

        asked: list[tuple[str | None, bool]] = []
        real = embedded.listening_sockets

        def recording(config, limits):
            sockets = real(config, limits)
            asked.append((limits, sockets is not None))
            return sockets

        monkeypatch.setattr(embedded, "listening_sockets", recording)
        # A number the system this runs on may not know: refused, it is still a server.
        monkeypatch.setattr(helpers.socket, "TCP_USER_TIMEOUT", getattr(socket, "TCP_USER_TIMEOUT", 18),
                            raising=False)
        for preferences, limits, bound in ((None, "standard", False), ({"config_limits": "small"}, "small", True)):
            settings = _installed(tmp_path / limits, preferences)
            port = _free_port()
            with patch("netcanon.api.routes.backups.get_collector", return_value=FakeCollector(output="! noop\n")):
                server = ServerThread(
                    create_app(settings), port=port, log_level="critical", config_limits=settings.config_limits,
                )
                server.start()
                try:
                    server.wait_ready(timeout=10.0)
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as resp:
                        assert json.loads(resp.read())["status"] == "ok"
                finally:
                    server.stop()
                    server.join(timeout=5.0)
            assert asked == [(limits, bound)], asked
            asked.clear()

    def test_small_in_the_preferences_file_limits_it_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A file edited by hand to ``small`` is honoured whole: the
        embedded server works on one request at a time.  The second is
        seen in the line while the first is inside the pipeline, and
        runs when the first has been answered."""
        settings = _installed(tmp_path, {"config_limits": "small"})
        assert settings.config_limits == "small" and L.PROFILES["small"].at_once == 1
        work = _Work(monkeypatch)
        with _embedded(settings) as post:
            answers: dict[str, dict] = {}
            threads = [
                threading.Thread(target=lambda name=name: answers.update({name: post()}), daemon=True)
                for name in ("first", "second")
            ]
            threads[0].start()
            assert work.began.wait(10)
            threads[1].start()
            _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
            assert work.calls == 1
            work.let_go.set()
            for thread in threads:
                thread.join(30)
            assert (work.calls, work.most) == (2, 1)
            assert {job["status"] for job in answers.values()} == {"completed"} and len(answers) == 2
