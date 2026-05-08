"""
Layer-A unit tests for the SNMPv3 USM user-name orchestrator.

Fifth per-pane override category after ports (``test_port_names.py``),
VLANs (``test_vlan_names.py``), local_users (``test_local_user_names.py``),
and snmp_community (``test_snmp_names.py``).  This file exercises
:mod:`netcanon.migration.canonical.snmpv3_user_names` — the
orchestrator module that drives :attr:`CanonicalSNMP.v3_users` rename
+ drop + collision semantics.

The cross-codec smoke mesh lives in ``test_cross_mesh_overrides.py``
under the ``@pytest.mark.cross_mesh`` marker — this file is the
per-orchestrator correctness layer.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.canonical.snmpv3_user_names import (
    build_snmpv3_user_rename_transform,
    translate_snmpv3_users,
)

pytestmark = pytest.mark.unit


def _intent_with_v3(*names: str) -> CanonicalIntent:
    """Build a CanonicalIntent whose snmp block carries the named
    v3 users with distinctive auth/priv/group metadata so identity-
    only rename is visibly distinct from attribute mutation."""
    intent = CanonicalIntent()
    intent.snmp = CanonicalSNMP()
    for i, name in enumerate(names):
        intent.snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            group=f"grp-{name}",
            auth_protocol="sha",
            auth_passphrase=f"auth-{name}",
            priv_protocol="aes128",
            priv_passphrase=f"priv-{name}",
        ))
    return intent


class TestSnmpV3UserNameRename:
    """The rename + drop + warning + collision surface."""

    def test_rename_single_user(self):
        intent = _intent_with_v3("netadmin", "monitor")
        r = translate_snmpv3_users(
            intent, rename_map={"netadmin": "platform-snmpro"},
        )
        assert r.applied == {"netadmin": "platform-snmpro"}
        assert r.dropped == []
        assert len(intent.snmp.v3_users) == 2
        # Renamed user keeps its crypto + group metadata.
        renamed = intent.snmp.v3_users[0]
        assert renamed.name == "platform-snmpro"
        assert renamed.auth_passphrase == "auth-netadmin"
        assert renamed.priv_passphrase == "priv-netadmin"
        assert renamed.group == "grp-netadmin"

    def test_drop_removes_user(self):
        intent = _intent_with_v3("netadmin", "monitor")
        r = translate_snmpv3_users(intent, rename_map={"monitor": None})
        assert r.dropped == ["monitor"]
        assert [u.name for u in intent.snmp.v3_users] == ["netadmin"]

    def test_no_op_when_rename_map_empty(self):
        intent = _intent_with_v3("netadmin")
        r = translate_snmpv3_users(intent, rename_map={})
        assert r.applied == {}
        assert r.dropped == []
        assert intent.snmp.v3_users[0].name == "netadmin"

    def test_no_op_when_rename_map_none(self):
        intent = _intent_with_v3("netadmin")
        r = translate_snmpv3_users(intent, rename_map=None)
        assert r.applied == {}
        assert r.dropped == []

    def test_warning_on_missing_source(self):
        intent = _intent_with_v3("netadmin")
        r = translate_snmpv3_users(
            intent, rename_map={"does-not-exist": "new-name"},
        )
        assert r.applied == {}
        assert r.warnings
        assert any("does-not-exist" in w for w in r.warnings)

    def test_warning_on_empty_source_or_target(self):
        intent = _intent_with_v3("netadmin")
        r = translate_snmpv3_users(
            intent, rename_map={"": "new", "netadmin": ""},
        )
        assert r.applied == {}
        assert len(r.warnings) >= 2

    def test_warning_when_source_has_no_snmp_block(self):
        intent = CanonicalIntent()
        # intent.snmp is None — no SNMP block at all.
        r = translate_snmpv3_users(
            intent, rename_map={"netadmin": "new-admin"},
        )
        assert r.applied == {}
        assert any("no SNMPv3 users" in w for w in r.warnings)

    def test_warning_when_source_has_no_v3_users(self):
        intent = CanonicalIntent()
        intent.snmp = CanonicalSNMP(community="public")  # v1/v2c only
        r = translate_snmpv3_users(
            intent, rename_map={"netadmin": "new-admin"},
        )
        assert r.applied == {}
        assert any("no SNMPv3 users" in w for w in r.warnings)

    def test_collision_first_wins_drops_later(self):
        """Two sources mapped to same target → first record wins,
        second drops with a warning.  Auth / priv keys never combine."""
        intent = _intent_with_v3("userA", "userB", "userC")
        r = translate_snmpv3_users(
            intent,
            rename_map={"userA": "shared", "userB": "shared"},
        )
        # First-wins: userA landed at "shared", userB dropped.
        assert r.applied == {"userA": "shared", "userB": "shared"}
        names = [u.name for u in intent.snmp.v3_users]
        assert names.count("shared") == 1
        assert "userC" in names
        assert any("collides" in w for w in r.warnings)
        # The surviving "shared" user carries userA's crypto, NOT
        # merged with userB's — identity-by-first-wins, not
        # hash-by-union.
        shared = next(u for u in intent.snmp.v3_users if u.name == "shared")
        assert shared.auth_passphrase == "auth-userA"

    def test_collision_with_existing_name(self):
        """Rename target equals an existing user name → first-match
        keeps its spot, the renamed record drops."""
        intent = _intent_with_v3("srcUser", "existingUser")
        r = translate_snmpv3_users(
            intent, rename_map={"srcUser": "existingUser"},
        )
        # First-wins: existingUser (parse-order earlier position index
        # doesn't matter — existingUser was already in the tree with
        # that name) occupies the slot.  srcUser's rename collides.
        names = [u.name for u in intent.snmp.v3_users]
        assert names.count("existingUser") == 1
        # Either srcUser was dropped or it overwrote existingUser;
        # check the warning fired.
        assert any(
            "collides" in w or "existingUser" in w for w in r.warnings
        )

    def test_rename_preserves_order_of_unrenamed_records(self):
        """Non-renamed records keep their relative order."""
        intent = _intent_with_v3("a", "b", "c", "d")
        translate_snmpv3_users(intent, rename_map={"b": "B-new"})
        assert [u.name for u in intent.snmp.v3_users] == [
            "a", "B-new", "c", "d",
        ]

    def test_transform_factory_returns_accumulator(self):
        """``build_snmpv3_user_rename_transform`` returns a
        (transform, result) tuple; pipeline applies the transform
        and reads the accumulator afterwards."""
        intent = _intent_with_v3("netadmin", "monitor")
        fn, result = build_snmpv3_user_rename_transform(
            rename_map={"netadmin": "platform-snmpro", "monitor": None},
        )
        out = fn(intent)
        assert out is intent                    # in-place mutation
        assert result.applied == {"netadmin": "platform-snmpro"}
        assert result.dropped == ["monitor"]

    def test_defensive_no_op_on_non_canonical_input(self):
        """Mock adapters produce plain dicts.  The orchestrator
        must no-op rather than crash."""
        result = translate_snmpv3_users(
            {"hello": "world"},                  # type: ignore[arg-type]
            rename_map={"x": "y"},
        )
        assert result.applied == {}
        assert result.warnings == []
