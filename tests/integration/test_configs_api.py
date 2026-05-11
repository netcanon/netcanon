"""
Integration tests for ``/api/v1/configs/`` endpoints.

Tests cover the full config lifecycle:
list (empty) → backup creates a file → list (populated) → get content → delete.

Also covers ``POST /{filename}/open`` (open-in-editor endpoint).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.storage.file_store import FileConfigStore

pytestmark = pytest.mark.integration


def _seed_config(client, host: str = "192.168.1.1") -> str:
    """Run a backup job and return the saved filename.

    Background tasks run synchronously in TestClient but AFTER the POST
    response body is serialised (so POST always returns ``status: pending``).
    We GET the job immediately after to read the completed state.
    """
    post_resp = client.post(
        "/api/v1/backups",
        json={
            "devices": [
                {
                    "type_key": "Cisco",
                    "host": host,
                    "credentials": {
                        "username": "admin",
                        "password": "testpass",
                    },
                }
            ]
        },
    )
    assert post_resp.status_code == 202
    job_id = post_resp.json()["id"]
    job = client.get(f"/api/v1/backups/{job_id}").json()
    assert job["status"] == "completed", f"Expected completed, got {job['status']}"
    result = job["results"][0]
    assert result["status"] == "success"
    return result["config_record"]["filename"]


class TestListConfigs:
    def test_empty_store_returns_200(self, client):
        resp = client.get("/api/v1/configs/")
        assert resp.status_code == 200

    def test_empty_store_returns_empty_list(self, client):
        resp = client.get("/api/v1/configs/")
        assert resp.json() == []

    def test_after_backup_config_appears(self, client):
        _seed_config(client)
        resp = client.get("/api/v1/configs/")
        assert len(resp.json()) == 1

    def test_config_metadata_fields(self, client):
        _seed_config(client)
        resp = client.get("/api/v1/configs/")
        cfg = resp.json()[0]
        assert cfg["device_type"] == "Cisco"
        assert cfg["host"] == "192.168.1.1"
        assert "filename" in cfg
        assert "size_bytes" in cfg
        assert "timestamp" in cfg

    def test_multiple_backups_all_listed(self, client):
        _seed_config(client, "1.1.1.1")
        _seed_config(client, "2.2.2.2")
        resp = client.get("/api/v1/configs/")
        assert len(resp.json()) == 2

    def test_list_sorted_newest_first(self, client):
        _seed_config(client, "1.1.1.1")
        _seed_config(client, "2.2.2.2")
        resp = client.get("/api/v1/configs/")
        items = resp.json()
        ts = [item["timestamp"] for item in items]
        assert ts == sorted(ts, reverse=True)


class TestGetConfig:
    def test_get_existing_config_returns_200(self, client):
        filename = _seed_config(client)
        resp = client.get(f"/api/v1/configs/{filename}")
        assert resp.status_code == 200

    def test_get_existing_config_returns_text(self, client):
        filename = _seed_config(client)
        resp = client.get(f"/api/v1/configs/{filename}")
        # FakeCollector returns CISCO_FAKE_OUTPUT
        assert "hostname" in resp.text or "version" in resp.text

    def test_get_nonexistent_config_returns_404(self, client):
        resp = client.get("/api/v1/configs/nonexistent.cfg")
        assert resp.status_code == 404

    def test_get_404_detail_mentions_filename(self, client):
        resp = client.get("/api/v1/configs/ghost.cfg")
        assert "ghost.cfg" in resp.json()["detail"]


class TestDeleteConfig:
    def test_delete_returns_204(self, client):
        filename = _seed_config(client)
        resp = client.delete(f"/api/v1/configs/{filename}")
        assert resp.status_code == 204

    def test_delete_removes_from_list(self, client):
        filename = _seed_config(client)
        client.delete(f"/api/v1/configs/{filename}")
        resp = client.get("/api/v1/configs/")
        assert resp.json() == []

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/v1/configs/ghost.cfg")
        assert resp.status_code == 404

    def test_delete_then_get_returns_404(self, client):
        filename = _seed_config(client)
        client.delete(f"/api/v1/configs/{filename}")
        resp = client.get(f"/api/v1/configs/{filename}")
        assert resp.status_code == 404

    def test_delete_only_removes_target(self, client):
        fn1 = _seed_config(client, "1.1.1.1")
        _seed_config(client, "2.2.2.2")
        client.delete(f"/api/v1/configs/{fn1}")
        remaining = client.get("/api/v1/configs/").json()
        assert len(remaining) == 1
        assert remaining[0]["host"] == "2.2.2.2"


class TestOpenConfig:
    """Tests for ``POST /api/v1/configs/{filename}/open``."""

    @pytest.fixture()
    def open_client(self, sample_definitions_dir: Path, tmp_path: Path):
        """TestClient with ``open_in_editor=True`` and SSH mocked out."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from netcanon.main import create_app
        from tests.conftest import CISCO_FAKE_OUTPUT, FakeCollector

        settings = Settings(
            definitions_dir=sample_definitions_dir,
            configs_dir=tmp_path / "configs",
            open_in_editor=True,
        )
        app = create_app(settings)
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netcanon.api.routes.backups.get_collector", return_value=fake
        ):
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c

    def test_open_returns_403_when_disabled(self, client):
        """Default ``test_settings`` has ``open_in_editor=False``."""
        filename = _seed_config(client)
        resp = client.post(f"/api/v1/configs/{filename}/open")
        assert resp.status_code == 403

    def test_open_returns_404_for_missing_file(self, open_client):
        # No patch needed — endpoint returns 404 before any platform-specific
        # open call.  os.startfile is Windows-only and would AttributeError
        # on Linux CI runners if mocked unconditionally.
        resp = open_client.post("/api/v1/configs/ghost.cfg/open")
        assert resp.status_code == 404

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="os.startfile is the Windows-only path; Linux uses xdg-open and "
               "macOS uses 'open' via subprocess.  Cross-platform coverage of "
               "the success path lives in the desktop-tier tests where the "
               "subprocess.run mock pattern is shared.",
    )
    def test_open_returns_204_on_success(self, open_client):
        filename = _seed_config(open_client)
        with patch("os.startfile") as mock_sf:
            resp = open_client.post(f"/api/v1/configs/{filename}/open")
        assert resp.status_code == 204
        mock_sf.assert_called_once()

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Asserts os.startfile call args; Windows-specific path.",
    )
    def test_open_passes_correct_path_to_startfile(self, open_client):
        filename = _seed_config(open_client)
        with patch("os.startfile") as mock_sf:
            open_client.post(f"/api/v1/configs/{filename}/open")
        called_path = mock_sf.call_args[0][0]
        assert filename in called_path

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="Mocks os.startfile to raise; Windows-specific path.",
    )
    def test_open_returns_500_when_startfile_raises(self, open_client):
        """500 response is operator-readable + does NOT leak raw OS error text.

        Pre-Phase-3 the response detail was f"Could not open file: {exc}"
        which echoed the raw OSError string (e.g. "access denied", or
        worse, a Windows path containing the server's filesystem layout)
        to the HTTP client.  The underlying exception is now suppressed
        from the response (still logged server-side with exc_info=True);
        the operator sees a generic "check server log" message naming
        the file that failed.
        """
        filename = _seed_config(open_client)
        with patch("os.startfile", side_effect=OSError("access denied")):
            resp = open_client.post(f"/api/v1/configs/{filename}/open")
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert filename in detail
        assert "server log" in detail.lower()
        # Privacy fix — raw exception text must NOT leak through.
        assert "access denied" not in detail

    def test_open_rejects_disallowed_extension(self, open_client):
        """Executable and other non-config extensions must return 400."""
        # No patch needed — extension whitelist rejects with 400 before
        # any platform-specific open call is made.
        resp = open_client.post("/api/v1/configs/malware.exe/open")
        assert resp.status_code == 400

    def test_open_rejects_zip_extension(self, open_client):
        # Same — 400 returned before reaching the platform branch.
        resp = open_client.post("/api/v1/configs/archive.zip/open")
        assert resp.status_code == 400


class TestPathTraversal:
    """GET and DELETE must not expose files outside the storage directory."""

    def test_get_dotdot_returns_404(self, client):
        resp = client.get("/api/v1/configs/../../etc/passwd")
        assert resp.status_code == 404

    def test_get_dotdot_cfg_returns_404(self, client):
        """Even a .cfg suffix on a traversal path must be rejected."""
        resp = client.get("/api/v1/configs/../../etc/shadow.cfg")
        assert resp.status_code == 404

    def test_delete_dotdot_returns_404(self, client):
        resp = client.delete("/api/v1/configs/../../etc/passwd")
        assert resp.status_code == 404

    def test_get_absolute_path_returns_404(self, client):
        resp = client.get("/api/v1/configs//etc/passwd")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/configs/diff  (Tier 1 — textual line diff)
# ---------------------------------------------------------------------------


def _seed_config_of_type(client, type_key: str, host: str) -> str:
    """Same as ``_seed_config`` but parametrised on ``type_key``."""
    post_resp = client.post(
        "/api/v1/backups",
        json={
            "devices": [
                {
                    "type_key": type_key,
                    "host": host,
                    "credentials": {"username": "admin", "password": "pw"},
                }
            ]
        },
    )
    assert post_resp.status_code == 202
    job = client.get(f"/api/v1/backups/{post_resp.json()['id']}").json()
    assert job["status"] == "completed"
    return job["results"][0]["config_record"]["filename"]


class TestDiffCompatibility:
    """The API must refuse textually-diffing configs with different type_key
    or file_extension unless the caller explicitly passes ``force=true``."""

    def test_same_type_returns_200(self, client):
        a = _seed_config_of_type(client, "Cisco", "10.1.1.1")
        b = _seed_config_of_type(client, "Cisco", "10.1.1.2")
        resp = client.post(
            "/api/v1/configs/diff", json={"left": a, "right": b}
        )
        assert resp.status_code == 200
        report = resp.json()
        assert report["compatibility"]["severity"] == "ok"
        assert report["compatibility"]["compatible"] is True

    def test_cross_vendor_without_force_returns_422(self, client):
        cisco = _seed_config_of_type(client, "Cisco", "10.2.2.1")
        opn = _seed_config_of_type(client, "OPNsense", "10.2.2.2")
        resp = client.post(
            "/api/v1/configs/diff", json={"left": cisco, "right": opn}
        )
        assert resp.status_code == 422
        body = resp.json()
        # Fastapi nests custom dicts under "detail"; verify the reasons surfaced.
        detail = body["detail"]
        assert isinstance(detail, dict)
        reasons = detail["reasons"]
        assert any("type_key" in r for r in reasons)
        assert any("file_extension" in r for r in reasons)

    def test_cross_vendor_with_force_returns_200_with_block_banner(self, client):
        cisco = _seed_config_of_type(client, "Cisco", "10.3.3.1")
        opn = _seed_config_of_type(client, "OPNsense", "10.3.3.2")
        resp = client.post(
            "/api/v1/configs/diff",
            json={"left": cisco, "right": opn, "force": True},
        )
        assert resp.status_code == 200
        compat = resp.json()["compatibility"]
        assert compat["severity"] == "block"
        assert compat["compatible"] is False
        # Force override is remembered so the UI can show a red banner.
        assert any("force=true" in r for r in compat["reasons"])

    def test_left_missing_returns_404(self, client):
        b = _seed_config_of_type(client, "Cisco", "10.4.4.1")
        resp = client.post(
            "/api/v1/configs/diff",
            json={
                "left": "Cisco_0-0-0-0_20000101_000000.cfg",
                "right": b,
            },
        )
        assert resp.status_code == 404

    def test_right_missing_returns_404(self, client):
        a = _seed_config_of_type(client, "Cisco", "10.4.4.2")
        resp = client.post(
            "/api/v1/configs/diff",
            json={
                "left": a,
                "right": "Cisco_0-0-0-0_20000101_000000.cfg",
            },
        )
        assert resp.status_code == 404


class TestDiffOutput:
    """Structural checks on the diff body — stats, line kinds, numbers."""

    def test_same_file_diff_has_all_equal_lines(self, client):
        a = _seed_config_of_type(client, "Cisco", "10.5.5.1")
        resp = client.post(
            "/api/v1/configs/diff", json={"left": a, "right": a}
        )
        assert resp.status_code == 200
        report = resp.json()
        assert report["stats"]["added"] == 0
        assert report["stats"]["removed"] == 0
        assert report["stats"]["equal"] > 0
        assert all(line["kind"] == "equal" for line in report["lines"])

    def test_equal_lines_have_both_line_numbers(self, client):
        a = _seed_config_of_type(client, "Cisco", "10.5.5.2")
        resp = client.post(
            "/api/v1/configs/diff", json={"left": a, "right": a}
        )
        for line in resp.json()["lines"]:
            assert line["left_no"] is not None
            assert line["right_no"] is not None

    def test_diff_line_numbers_monotonic(self, client):
        """For any add/equal line the right_no strictly increases;
        for any remove/equal line the left_no strictly increases."""
        a = _seed_config_of_type(client, "Cisco", "10.5.5.3")
        resp = client.post(
            "/api/v1/configs/diff", json={"left": a, "right": a}
        )
        lines = resp.json()["lines"]
        lefts = [L["left_no"] for L in lines if L["left_no"] is not None]
        rights = [L["right_no"] for L in lines if L["right_no"] is not None]
        assert lefts == sorted(lefts)
        assert rights == sorted(rights)
