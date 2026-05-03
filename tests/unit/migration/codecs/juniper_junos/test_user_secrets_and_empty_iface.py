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
        "9 hash from source vendor cannot be re-used on Junos"
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


def test_junos_unmigratable_hash_drops_user_declaration_entirely() -> None:
    """Finding #16 in user_smoke_findings.md.  When the source hash
    is unmigratable to Junos (e.g. OPNsense bcrypt ``$2y$..``), the
    renderer must NOT emit a bare ``set system login user X class Y``
    line — that creates a passwordless account at Junos commit
    time, strictly worse than the source state.  Mirror Cisco
    IOS-XE's full-drop pattern: only the ``# password manager ..
    -- review:`` comment line remains, signalling the operator to
    reset the password manually.
    """
    intent = CanonicalIntent(
        hostname="opnsense-source",
        local_users=[
            CanonicalLocalUser(
                name="root",
                privilege_level=15,
                # Synthetic OPNsense-tagged bcrypt — looks real,
                # isn't.  The ``opnsense:bcrypt:`` prefix is the
                # canonical-store form OPNsense's parser writes.
                hashed_password="opnsense:bcrypt:$2y$11$fakeBcryptSaltAndHash",
            ),
        ],
    )
    out = render_intent(intent)
    # Review comment IS present, naming the user + the source
    # algorithm + the per-codec target label.
    assert (
        '# password manager user-name "root" -- review: '
    ) in out
    assert "cannot be re-used on Junos" in out
    # Crucially, NO ``set system login user root`` declaration
    # anywhere in the output — that would create a passwordless
    # account on Junos.
    assert "set system login user root" not in out
    # And no encrypted-password line either.
    assert "authentication encrypted-password" not in out


def test_junos_migratable_hash_still_emits_user_declaration() -> None:
    """Regression guard: a migratable hash (sha512crypt ``$6$..``,
    which Junos accepts natively at commit time) must continue to
    produce both the ``set system login user X class Y`` line AND
    the ``authentication encrypted-password ...`` line.  The hash-
    gate continue must only fire on unmigratable hashes.
    """
    intent = CanonicalIntent(
        hostname="lab-junos",
        local_users=[
            CanonicalLocalUser(
                name="root",
                privilege_level=15,
                hashed_password="$6$saltyMcSalt$fakeSha512HashPayload",
            ),
        ],
    )
    out = render_intent(intent)
    # User declaration IS present.
    assert "set system login user root class super-user" in out
    # Encrypted-password line IS present, with the raw payload
    # (sha512crypt is consumable by Junos's commit-time hasher).
    assert (
        'set system login user root authentication encrypted-password '
        '"$6$saltyMcSalt$fakeSha512HashPayload"'
    ) in out
    # And no review comment for this user.
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
    """A non-Junos-shaped interface (e.g. cross-vendor source's
    ``Vlan1`` after rename to ``irb.1``) with no IPs, no
    description, default MTU, enabled, no L2 / LAG state, and no
    routing-instance binding is pure noise on Junos — skip emit
    entirely.

    Junos-shaped physical port names (``ge-0/0/0``, ``xe-1/0/24``,
    ``fxp0``) keep the placeholder for parse->render->parse
    stability with Junos sources whose Tier-3 L2 grammar (older
    ``port-mode`` form) doesn't surface in canonical — see
    ``test_render_empty_interface_is_skipped`` for that case.
    """
    intent = CanonicalIntent(
        hostname="lab-sw1",
        interfaces=[CanonicalInterface(name="irb.1")],
    )
    out = render_intent(intent)
    # Pure-leak case (Cisco Vlan1 → irb.1 rename, no L3) is skipped.
    assert "set interfaces irb.1" not in out


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


# ---------------------------------------------------------------------------
# Sub-finding 9b — DHCP client emit (family inet dhcp)
# ---------------------------------------------------------------------------


def test_junos_dhcp_client_emits_family_inet_dhcp() -> None:
    """``CanonicalInterface(dhcp_client=True)`` translates to Junos's
    ``set interfaces <name> unit 0 family inet dhcp`` — a property of
    ``family inet`` that replaces the static ``address`` clause.
    Cisco IOS-XE ``ip address dhcp`` and MikroTik DHCP-client
    interfaces canonicalise to this field; without the emit path
    they were silently dropped on render-into-Junos cross-vendor
    flows."""
    intent = CanonicalIntent(
        hostname="dhcp-client-host",
        interfaces=[
            CanonicalInterface(name="ge-0/0/0", dhcp_client=True),
        ],
    )
    out = render_intent(intent)
    assert "set interfaces ge-0/0/0 unit 0 family inet dhcp" in out


def test_junos_dhcp_client_keeps_interface_through_elision() -> None:
    """Regression guard: an interface whose ONLY content is
    ``dhcp_client=True`` (no static IP, no description, no L2 / LAG /
    VRF state) must still be emitted.  Without the elision-predicate
    update, the empty-stub heuristic would drop it as bodyless and
    the DHCP client config would never make it into the rendered
    output."""
    intent = CanonicalIntent(
        hostname="dhcp-only",
        interfaces=[
            CanonicalInterface(name="ge-0/0/0", dhcp_client=True),
        ],
    )
    out = render_intent(intent)
    # The dhcp emit line is present (proves elision didn't drop it).
    assert "set interfaces ge-0/0/0 unit 0 family inet dhcp" in out


def test_junos_dhcp_client_with_description_emits_both() -> None:
    """When a DHCP-client interface also carries a description, BOTH
    the description line AND the ``family inet dhcp`` line must be
    emitted — neither is suppressed by the other.  Models the common
    WAN-uplink shape on edge routers."""
    intent = CanonicalIntent(
        hostname="edge-router",
        interfaces=[
            CanonicalInterface(
                name="ge-0/0/0",
                description="WAN uplink",
                dhcp_client=True,
            ),
        ],
    )
    out = render_intent(intent)
    assert 'set interfaces ge-0/0/0 description "WAN uplink"' in out
    assert "set interfaces ge-0/0/0 unit 0 family inet dhcp" in out


def test_junos_static_ip_does_not_emit_dhcp() -> None:
    """Regression guard: an interface configured with a static IPv4
    address and no DHCP client (default ``dhcp_client=False``) must
    NOT emit the ``family inet dhcp`` line — only the existing static
    ``family inet address`` path applies.  Junos rejects
    ``family inet dhcp`` alongside a static ``address`` clause at
    commit time, so the two emit paths are mutually exclusive."""
    intent = CanonicalIntent(
        hostname="static-ip-host",
        interfaces=[
            CanonicalInterface(
                name="ge-0/0/0",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.0.2.1", prefix_length=24,
                    ),
                ],
            ),
        ],
    )
    out = render_intent(intent)
    assert (
        "set interfaces ge-0/0/0 unit 0 family inet address "
        "192.0.2.1/24"
    ) in out
    assert "family inet dhcp" not in out


def test_junos_no_dhcp_no_ip_still_elides() -> None:
    """Regression guard: a fully empty foreign-shaped interface name
    (``Vlan1`` after a Cisco→Junos rename, no IP, no description, no
    DHCP, no VRF binding, no sub-units) is STILL elided by the empty-
    stub policy.  The dhcp_client predicate addition must not weaken
    the existing tiered elision behaviour for non-DHCP-client cases."""
    intent = CanonicalIntent(
        hostname="elided-host",
        interfaces=[CanonicalInterface(name="irb.1")],
    )
    out = render_intent(intent)
    # Pure-leak case stays elided; the dhcp_client guard is False.
    assert "set interfaces irb.1" not in out
    assert "family inet dhcp" not in out
