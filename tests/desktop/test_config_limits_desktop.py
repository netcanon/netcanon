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
* the refusal that server gives names the Preferences dialog.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.definitions import LIBRARY_DIR
from netcanon.main import create_app
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
