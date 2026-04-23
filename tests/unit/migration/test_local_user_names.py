"""
Unit tests for :mod:`netconfig.migration.canonical.local_user_names`.

Layer A tests — transform-level correctness on synthetic
:class:`CanonicalIntent` trees, no I/O, no codec-specific behaviour.
Mirrors the structural shape of test_vlan_names.py, adapted for the
string-keyed local-user domain.

Cross-codec mesh coverage (Layer B) lives in
``test_cross_mesh_overrides.py`` — this file covers the orchestrator
in isolation.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
)
from netconfig.migration.canonical.local_user_names import (
    LocalUserRenameResult,
    build_local_user_rename_transform,
    translate_local_user_names,
)

pytestmark = pytest.mark.unit


def _tree_with_users(*specs: tuple) -> CanonicalIntent:
    """Minimal canonical tree containing the given users.

    Each spec is ``(name, privilege_level, role, password)`` —
    password defaults to empty string for brevity.
    """
    users = []
    for spec in specs:
        name = spec[0]
        priv = spec[1] if len(spec) > 1 else 1
        role = spec[2] if len(spec) > 2 else ""
        pw = spec[3] if len(spec) > 3 else ""
        users.append(CanonicalLocalUser(
            name=name,
            privilege_level=priv,
            role=role,
            hashed_password=pw,
        ))
    return CanonicalIntent(local_users=users)


class TestIdentityAndNoOps:
    def test_empty_map_is_noop(self):
        intent = _tree_with_users(("admin",), ("operator",))
        result = translate_local_user_names(intent, rename_map={})
        assert result.applied == {}
        assert result.dropped == []
        assert [u.name for u in intent.local_users] == ["admin", "operator"]

    def test_none_map_is_noop(self):
        intent = _tree_with_users(("admin",), ("operator",))
        result = translate_local_user_names(intent, rename_map=None)
        assert result.applied == {}

    def test_non_canonical_input_returns_empty_result(self):
        """Mock adapters produce plain dicts; defensive guard prevents
        crashes when the transform is wired into a mock-codec smoke
        test."""
        result = translate_local_user_names(
            {"not": "canonical"},  # type: ignore[arg-type]
            rename_map={"admin": "manager"},
        )
        assert result == LocalUserRenameResult()


class TestSimpleRename:
    def test_single_rename(self):
        intent = _tree_with_users(("admin", 15, "manager"))
        result = translate_local_user_names(
            intent, rename_map={"admin": "netadmin"},
        )
        assert result.applied == {"admin": "netadmin"}
        assert [u.name for u in intent.local_users] == ["netadmin"]
        # Other fields preserved.
        assert intent.local_users[0].privilege_level == 15
        assert intent.local_users[0].role == "manager"

    def test_multiple_renames(self):
        intent = _tree_with_users(("admin",), ("operator",), ("backup",))
        result = translate_local_user_names(
            intent,
            rename_map={"admin": "netadmin", "operator": "readonly"},
        )
        assert result.applied == {
            "admin": "netadmin",
            "operator": "readonly",
        }
        names = [u.name for u in intent.local_users]
        # Unchanged users pass through.
        assert "backup" in names
        assert "netadmin" in names
        assert "readonly" in names

    def test_rename_unchanged_user_not_in_applied(self):
        """Users whose name doesn't change shouldn't clutter the
        applied map — same contract as port_names and vlan_names."""
        intent = _tree_with_users(("admin",), ("stay",))
        result = translate_local_user_names(
            intent, rename_map={"admin": "netadmin"},
        )
        assert "stay" not in result.applied


class TestDropSemantics:
    def test_drop_removes_user(self):
        intent = _tree_with_users(("admin",), ("svc-backup-2019",))
        result = translate_local_user_names(
            intent, rename_map={"svc-backup-2019": None},
        )
        assert result.dropped == ["svc-backup-2019"]
        names = [u.name for u in intent.local_users]
        assert "svc-backup-2019" not in names
        assert "admin" in names

    def test_drop_multiple_users(self):
        intent = _tree_with_users(("admin",), ("old1",), ("old2",))
        result = translate_local_user_names(
            intent, rename_map={"old1": None, "old2": None},
        )
        assert sorted(result.dropped) == ["old1", "old2"]
        assert [u.name for u in intent.local_users] == ["admin"]


class TestCollisionMerge:
    def test_two_sources_same_target_merge(self):
        """Two source users mapped to same target → merge with
        higher privilege level + first-wins role + first-wins hash."""
        intent = _tree_with_users(
            ("admin", 15, "manager", "hash_admin"),
            ("operator", 5, "readonly", "hash_operator"),
        )
        result = translate_local_user_names(
            intent,
            rename_map={"admin": "unified", "operator": "unified"},
        )
        # Two rewrites applied.
        assert result.applied == {"admin": "unified", "operator": "unified"}
        # Merge warning surfaces.
        assert any(
            "multiple source users mapped to 'unified'" in w
            for w in result.warnings
        )
        # One user remains; priv level takes the MAX.
        assert len(intent.local_users) == 1
        u = intent.local_users[0]
        assert u.name == "unified"
        assert u.privilege_level == 15
        # First-processed user's role wins (admin's "manager").
        assert u.role == "manager"
        # First-processed user's hash wins.
        assert u.hashed_password == "hash_admin"

    def test_rename_into_existing_name_merges(self):
        """Mapping a user to a name that already exists in the tree
        is a merge (same semantics as VLAN rename into existing ID)."""
        intent = _tree_with_users(
            ("admin", 15, "manager"),
            ("legacy", 1, "readonly"),
        )
        result = translate_local_user_names(
            intent, rename_map={"legacy": "admin"},
        )
        assert result.applied == {"legacy": "admin"}
        assert any(
            "already exists" in w and "admin" in w for w in result.warnings
        )
        # One user; admin's privilege level is higher so it stays.
        assert len(intent.local_users) == 1
        assert intent.local_users[0].name == "admin"
        assert intent.local_users[0].privilege_level == 15


class TestInputValidation:
    def test_empty_source_name_skipped(self):
        intent = _tree_with_users(("admin",))
        result = translate_local_user_names(
            intent, rename_map={"": "netadmin"},
        )
        assert result.applied == {}
        assert any("empty or not a string" in w for w in result.warnings)

    def test_empty_target_name_skipped(self):
        intent = _tree_with_users(("admin",))
        result = translate_local_user_names(
            intent, rename_map={"admin": ""},
        )
        assert result.applied == {}
        # admin unchanged.
        assert intent.local_users[0].name == "admin"

    def test_rename_nonexistent_user_is_warned_noop(self):
        intent = _tree_with_users(("admin",))
        result = translate_local_user_names(
            intent, rename_map={"ghost": "nobody"},
        )
        # No rewrite happens (ghost isn't in the tree) but the valid
        # map entry still passes validation — the warning flags the
        # no-op so operators notice the typo.
        assert result.applied == {}
        assert any(
            "not found in local_users" in w for w in result.warnings
        )

    def test_whitespace_only_names_skipped(self):
        intent = _tree_with_users(("admin",))
        result = translate_local_user_names(
            intent, rename_map={"   ": "x", "admin": "   "},
        )
        assert result.applied == {}


class TestTransformBuilder:
    def test_builder_returns_pipeline_compatible_transform(self):
        transform, result = build_local_user_rename_transform(
            rename_map={"admin": "netadmin"},
        )
        intent = _tree_with_users(("admin",), ("other",))
        out = transform(intent)
        # Transform returns the same tree (in-place mutation).
        assert out is intent
        # Result accumulator populated.
        assert result.applied == {"admin": "netadmin"}

    def test_builder_with_empty_map_is_noop(self):
        transform, result = build_local_user_rename_transform(rename_map={})
        intent = _tree_with_users(("admin",))
        out = transform(intent)
        assert out is intent
        assert result.applied == {}
        assert result.dropped == []
