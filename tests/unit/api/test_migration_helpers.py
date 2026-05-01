"""Unit tests for :mod:`netconfig.api.routes._migration_helpers`.

Helpers were extracted out of ``migration.py`` during the
``refactor/god-file-cleanup`` branch.  Previously they were exercised
only indirectly through ``tests/integration/test_migration_api.py``
via TestClient.  These tests cover the helpers directly so failures
land closer to the cause and so refactoring inside the helpers
doesn't require spinning up the FastAPI app.

One test class per public helper.  No TestClient — the helpers are
pure functions (or near-pure: ``get_target_profiles`` reads
``request.app.state``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from netconfig.api.routes._migration_helpers import (
    build_codec_info_list,
    get_target_profiles,
    request_has_overrides_or_profile,
    resolve_adapter_or_422,
    resolve_input_text,
)
from netconfig.models.backup import ConfigRecord
from netconfig.models.migration import MigrationPlanRequest
from netconfig.storage.base import BaseConfigStore


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Storage stubs
# ---------------------------------------------------------------------------


class _DictStore(BaseConfigStore):
    """In-memory store mapping filename -> content; rest of API stubbed."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self._files = dict(files or {})

    def save(
        self,
        device_type: str,
        host: str,
        timestamp: datetime,
        extension: str,
        content: str,
        device_profile_id: str | None = None,
    ) -> ConfigRecord:  # pragma: no cover - unused
        raise NotImplementedError

    def list_configs(self) -> list[ConfigRecord]:  # pragma: no cover - unused
        raise NotImplementedError

    def get_content(self, filename: str) -> str:
        try:
            return self._files[filename]
        except KeyError:
            raise FileNotFoundError(filename)

    def delete(self, filename: str) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    def resolve_path(self, filename: str) -> Path:  # pragma: no cover - unused
        raise NotImplementedError


# ---------------------------------------------------------------------------
# resolve_adapter_or_422
# ---------------------------------------------------------------------------


class TestResolveAdapterOr422:
    def test_returns_codec_when_name_known(self):
        codec = resolve_adapter_or_422("mock", side="source")
        assert codec is not None
        assert codec.capabilities.adapter == "mock"

    def test_raises_422_when_name_unknown(self):
        with pytest.raises(HTTPException) as exc_info:
            resolve_adapter_or_422("does_not_exist", side="source")
        assert exc_info.value.status_code == 422

    def test_error_detail_carries_side_label(self):
        """Source vs target side is the user-visible cue for which field
        in the body needs fixing."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_adapter_or_422("does_not_exist", side="target")
        assert "target" in exc_info.value.detail


# ---------------------------------------------------------------------------
# resolve_input_text
# ---------------------------------------------------------------------------


class TestResolveInputText:
    def test_returns_raw_text_when_set(self):
        body = MigrationPlanRequest(source="mock", target="mock", raw_text="hello")
        store = _DictStore()
        assert resolve_input_text(body, store) == "hello"

    def test_returns_stored_content_when_filename_set(self):
        body = MigrationPlanRequest(
            source="mock", target="mock", source_filename="cfg.txt"
        )
        store = _DictStore({"cfg.txt": "stored content"})
        assert resolve_input_text(body, store) == "stored content"

    def test_raises_422_when_neither_set(self):
        body = MigrationPlanRequest(source="mock", target="mock")
        with pytest.raises(HTTPException) as exc_info:
            resolve_input_text(body, _DictStore())
        assert exc_info.value.status_code == 422

    def test_raises_422_when_both_set(self):
        body = MigrationPlanRequest(
            source="mock",
            target="mock",
            raw_text="x",
            source_filename="y",
        )
        with pytest.raises(HTTPException) as exc_info:
            resolve_input_text(body, _DictStore())
        assert exc_info.value.status_code == 422

    def test_raises_404_when_filename_missing(self):
        body = MigrationPlanRequest(
            source="mock", target="mock", source_filename="missing.txt"
        )
        with pytest.raises(HTTPException) as exc_info:
            resolve_input_text(body, _DictStore())
        assert exc_info.value.status_code == 404
        assert "missing.txt" in exc_info.value.detail

    def test_empty_raw_text_returns_empty_string(self):
        """``raw_text=""`` is a valid (empty) input — distinct from ``None``."""
        body = MigrationPlanRequest(source="mock", target="mock", raw_text="")
        # Pydantic treats empty string as "set" → has_text True, has_file False.
        # The helper returns body.raw_text or "" → "".
        assert resolve_input_text(body, _DictStore()) == ""


# ---------------------------------------------------------------------------
# get_target_profiles
# ---------------------------------------------------------------------------


class TestGetTargetProfiles:
    def test_returns_attribute_when_present(self):
        profile = object()  # opaque sentinel — we only care about identity
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(target_profiles={"k": profile}))
        )
        result = get_target_profiles(request)
        assert result == {"k": profile}

    def test_returns_empty_dict_when_attribute_missing(self):
        """Bare-app fixtures don't run the lifespan loader; helper must
        not raise AttributeError in that case."""
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        assert get_target_profiles(request) == {}


# ---------------------------------------------------------------------------
# build_codec_info_list
# ---------------------------------------------------------------------------


class TestBuildCodecInfoList:
    def test_returns_one_entry_per_registered_codec(self):
        result = build_codec_info_list(vendors={})
        names = [info.name for info in result]
        assert "mock" in names
        # Real codecs registered by the import side-effects:
        assert any(n.startswith("cisco") for n in names)

    def test_vendor_display_name_resolved_when_vendor_present(self):
        """When the vendors map contains the codec's vendor_id, its
        display_name surfaces on the CodecInfo entry."""
        # Build a fake vendor record exposing display_name.
        fake_vendor = SimpleNamespace(display_name="Fake Vendor Inc.")
        # Use any registered codec — find its vendor_id then plumb the fake.
        result_no_vendors = build_codec_info_list(vendors={})
        first = result_no_vendors[0]
        result_with = build_codec_info_list(
            vendors={first.vendor_id: fake_vendor}
        )
        match = next(i for i in result_with if i.name == first.name)
        assert match.vendor_display_name == "Fake Vendor Inc."

    def test_vendor_display_name_blank_when_vendor_missing(self):
        """Missing vendor entry → empty display_name; never KeyError."""
        result = build_codec_info_list(vendors={})
        assert all(info.vendor_display_name == "" for info in result)

    def test_supported_lossy_unsupported_counts_present(self):
        result = build_codec_info_list(vendors={})
        for info in result:
            assert info.supported_count >= 0
            assert info.lossy_count >= 0
            assert info.unsupported_count >= 0


# ---------------------------------------------------------------------------
# request_has_overrides_or_profile
# ---------------------------------------------------------------------------


class TestRequestHasOverridesOrProfile:
    def test_returns_false_for_plain_body(self):
        body = MigrationPlanRequest(source="mock", target="mock", raw_text="x")
        assert request_has_overrides_or_profile(body) is False

    def test_true_when_port_rename_map_set(self):
        body = MigrationPlanRequest(
            source="mock", target="mock", raw_text="x", port_rename_map={}
        )
        assert request_has_overrides_or_profile(body) is True

    def test_true_when_vlan_rename_map_set(self):
        body = MigrationPlanRequest(
            source="mock", target="mock", raw_text="x", vlan_rename_map={}
        )
        assert request_has_overrides_or_profile(body) is True

    def test_true_when_local_user_rename_map_set(self):
        body = MigrationPlanRequest(
            source="mock",
            target="mock",
            raw_text="x",
            local_user_rename_map={},
        )
        assert request_has_overrides_or_profile(body) is True

    def test_true_when_snmp_community_rename_map_set(self):
        body = MigrationPlanRequest(
            source="mock",
            target="mock",
            raw_text="x",
            snmp_community_rename_map={},
        )
        assert request_has_overrides_or_profile(body) is True

    def test_true_when_snmpv3_user_rename_map_set(self):
        body = MigrationPlanRequest(
            source="mock",
            target="mock",
            raw_text="x",
            snmpv3_user_rename_map={},
        )
        assert request_has_overrides_or_profile(body) is True

    def test_true_when_target_profile_set_alone(self):
        """Target-profile alone (no override map) still routes to the
        rename-aware pipeline so the auto-heuristic runs and the UI
        gets back its diagnostics."""
        body = MigrationPlanRequest(
            source="mock",
            target="mock",
            raw_text="x",
            target_profile="aruba_aoss/2930F-48G-PoEP",
        )
        assert request_has_overrides_or_profile(body) is True

    def test_empty_map_still_counts_as_present(self):
        """An empty ``{}`` is distinct from ``None`` — empty means
        "auto-heuristic only, please" and must still engage the
        rename-aware path."""
        body = MigrationPlanRequest(
            source="mock", target="mock", raw_text="x", port_rename_map={}
        )
        assert request_has_overrides_or_profile(body) is True
