"""Phase 4 follow-on regression tests for the Junos codec.

Two related fixes from ``user_smoke_findings.md``:

* **Issue #1b — Cisco type-9 hash leak (security)**.  Junos render
  used to emit ``authentication encrypted-password "9 $9$..."``
  unconditionally, leaking Cisco type-9 (scrypt) hashes that
  Junos cannot consume.  The new policy gates emit through
  ``netconfig.migration._user_secrets.is_migratable("juniper_junos")``
  and falls back to a ``# password manager user-name "X" -- review:``
  comment line when the source hash format isn't one Junos
  accepts.  Native Junos hashes (``junos:`` prefix) and foreign
  ``$1$`` (md5crypt) / ``$6$`` (sha512crypt) hashes pass through.

* **Issue #9 — empty interface stubs**.  Cross-vendor renders into
  Junos used to leak ``set interfaces irb.1`` and ``set interfaces
  ge-0/0/0`` stubs whenever the canonical record had no L3 / L2 /
  LAG / admin state.  The new policy skips emit unless a
  routing-instance binding requires the interface (Junos's commit-
  time validator rejects ``set routing-instances X interface Y.0``
  when ``Y`` isn't defined under ``[edit interfaces]``).
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLocalUser,
    CanonicalRoutingInstance,
    CanonicalVlan,
)
from netconfig.migration.codecs.juniper_junos.render import render_intent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Issue #1b — hash migratability gate
# ---------------------------------------------------------------------------


def test_unmigratable_cisco_type_9_emits_comment_review() -> None:
    """Cisco IOS-XE type-9 (scrypt, leading ``9 $9$..``) is not in
    Junos's accepted-hash set; the renderer must replace the
    encrypted-password line with a ``#`` review comment so the raw
    hash never reaches the rendered config."""
    intent = CanonicalIntent(
        hostname="cross-vendor-target",
        local_users=[
            CanonicalLocalUser(
                name="netadmin",
                privilege_level=15,
                hashed_password="9 $9$fakeSaltAdmin1$fakeHashFromCisco",
            ),
        ],
    )
    out = render_intent(intent)
    # The review-comment line is present, naming the user.
    assert (
        '# password manager user-name "netadmin" -- review: '
        "9 hash from source vendor cannot be re-used on this target"
    ) in out
    # The dangerous payload never appears anywhere in the output.
    assert "$9$" not in out
    # And the encrypted-password line for this user is absent.
    assert "authentication encrypted-password" not in out


def test_arista_sha512_migrates_to_junos_dollar_six() -> None:
    """Arista's canonical store uses ``arista:sha512:$6$..`` for
    sha512crypt hashes.  Junos accepts the raw ``$6$..`` form
    (commit-time validator), so the renderer should strip the
    ``vendor:alg:`` prefix and emit the payload verbatim."""
    intent = CanonicalIntent(
        hostname="from-arista",
        local_users=[
            CanonicalLocalUser(
                name="ops",
                privilege_level=15,
                hashed_password="arista:sha512:$6$saltyMcSalt$fakeHash",
            ),
        ],
    )
    out = render_intent(intent)
    assert (
        'set system login user ops authentication encrypted-password '
        '"$6$saltyMcSalt$fakeHash"'
    ) in out
    # No vendor:alg: prefix leaks.
    assert "arista:sha512:" not in out
    # No review comment for this user (it's migratable).
    assert "review:" not in out


def test_native_junos_hash_passes_through() -> None:
    """Native Junos parses store ``junos:<hash>``; render should
    strip just the prefix.  This is the existing round-trip
    behaviour and must keep working after the security gate
    lands."""
    intent = CanonicalIntent(
        hostname="native-junos",
        local_users=[
            CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="junos:$6$nativeSalt$nativeHash",
            ),
        ],
    )
    out = render_intent(intent)
    assert (
        'set system login user admin authentication encrypted-password '
        '"$6$nativeSalt$nativeHash"'
    ) in out
    assert "junos:" not in out
    assert "review:" not in out


# ---------------------------------------------------------------------------
# Issue #9 — empty interface stub elision
# ---------------------------------------------------------------------------


def test_empty_interface_skipped() -> None:
    """An interface with no IPs, no description, default MTU,
    enabled, no L2 / LAG state, and no routing-instance binding
    is pure noise on Junos — skip emit entirely."""
    intent = CanonicalIntent(
        hostname="lab-sw1",
        interfaces=[CanonicalInterface(name="ge-0/0/0")],
    )
    out = render_intent(intent)
    assert "set interfaces ge-0/0/0" not in out


def test_routing_instance_referenced_interface_emits_cleanly() -> None:
    """``ge-0/0/0`` carries no L3 / L2 / admin attributes but is
    bound to a Mgmt-vrf routing-instance.  Junos's commit-time
    validator requires the interface to be defined under
    ``[edit interfaces]`` before the routing-instance reference
    resolves (KB: "Interface must already be defined under
    [edit interfaces]").  We keep the bare line plus an
    explanatory comment.
    """
    intent = CanonicalIntent(
        hostname="cisco-source",
        interfaces=[CanonicalInterface(name="ge-0/0/0", vrf="Mgmt-vrf")],
        routing_instances=[
            CanonicalRoutingInstance(
                name="Mgmt-vrf", instance_type="vrf",
            ),
        ],
    )
    out = render_intent(intent)
    # Bare placeholder is kept (required by Junos commit-time check).
    assert "set interfaces ge-0/0/0\n" in out
    # Explanatory comment alongside it.
    assert (
        "# set interfaces ge-0/0/0 -- bare stub kept; "
        "required by routing-instance binding below"
    ) in out
    # Routing-instance interface binding is emitted.
    assert (
        "set routing-instances Mgmt-vrf interface ge-0/0/0.0"
    ) in out


def test_irb_with_no_body_skipped() -> None:
    """Cross-vendor renders sometimes synthesise ``irb.<vid>``
    canonical interfaces with no IP / no description / no other
    state — Junos has no use for the bare line and the SVI L3
    emit path handles legitimate irb-with-IPs cases separately."""
    intent = CanonicalIntent(
        hostname="cisco-source-with-irb",
        interfaces=[CanonicalInterface(name="irb.1")],
        # No matching VLAN — so the SVI L3 emission code path
        # doesn't apply.  The interface is pure noise.
    )
    out = render_intent(intent)
    assert "set interfaces irb.1" not in out


def test_irb_with_l3_address_still_emits() -> None:
    """Sanity check: an ``irb.<vid>`` interface that DOES carry an
    IP must still emit normally — only the empty case is skipped."""
    intent = CanonicalIntent(
        hostname="real-svi",
        interfaces=[
            CanonicalInterface(
                name="irb.10",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.10.10.1", prefix_length=24),
                ],
            ),
        ],
        vlans=[CanonicalVlan(id=10, name="USERS")],
    )
    out = render_intent(intent)
    # The SVI L3 binding is emitted via the vlan path (l3-interface)
    # and the explicit irb.10 iface contributes its address line.
    assert "set vlans USERS l3-interface irb.10" in out
