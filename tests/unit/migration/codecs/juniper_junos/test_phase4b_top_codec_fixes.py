"""
Phase 4b regression tests for two Junos codec fixes flagged in the
Phase 4b sweep:

* Render-side user-emit edge cases — local-users with empty
  ``hashed_password`` (Junos ``no-password`` form / console-only
  account) and ``$1$`` md5crypt hashes carrying a Cisco-source
  algorithm tag (``5 $1$..`` / ``md5crypt:$1$..``) used to be
  silently dropped on render-into-Junos cross-vendor flows.  The
  underlying ``$1$`` payload IS consumable by Junos's commit-time
  hasher; the codec-local helper :func:`_is_md5crypt_tagged`
  widens the migratable set so those users round-trip with their
  encrypted-password line intact.

* Parser projection post-pass — the existing IRB post-pass folded
  ``set interfaces irb unit <vid> family inet address <ip>`` lines
  onto the matching CanonicalVlan but missed the equivalent
  dotted-name shorthand ``set interfaces irb.<vid> unit 0 ...``
  (the shape produced by block-form -> set-form conversion).  And
  ``vlan members <NAME>`` lines without an explicit
  ``interface-mode`` declaration silently dropped the membership
  info — operators occasionally omit the mode line, treating it
  as defaulting to trunk semantics.  Both gaps now project into
  ``vlans[].ipv4_addresses`` / ``vlans[].tagged_ports``.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
)
from netcanon.migration.codecs.juniper_junos.parse import parse_intent
from netcanon.migration.codecs.juniper_junos.render import render_intent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Issue 1 — render-side user-emit edge cases
# ---------------------------------------------------------------------------


def test_junos_user_with_empty_hashed_password_emits_class_line() -> None:
    """A local user whose ``hashed_password`` is the empty string is
    NOT a security regression to emit on Junos: the bare ``class`` line
    creates a console-only / no-password account that the operator can
    rotate later by attaching ssh-rsa keys or running ``set
    authentication plain-text-password``.  The render path must emit
    just the class line (no encrypted-password line, no review
    comment).
    """
    intent = CanonicalIntent(
        hostname="empty-hash-user",
        local_users=[
            CanonicalLocalUser(
                name="ops",
                privilege_level=15,
                hashed_password="",
            ),
        ],
    )
    out = render_intent(intent)
    # Class line is present — Junos accepts the no-password form.
    assert "set system login user ops class super-user" in out
    # No encrypted-password line for this user (no hash material).
    assert "authentication encrypted-password" not in out
    # And no review comment — empty isn't unmigratable, it's just empty.
    assert "review:" not in out


def test_junos_user_with_md5crypt_hash_emits_auth_line() -> None:
    """A user carrying a ``$1$`` md5crypt hash with the Cisco-source
    canonical tag (``md5crypt:$1$..``) must render through the
    encrypted-password path on Junos — the underlying ``$1$`` payload
    is consumable by Junos's commit-time hasher even though the
    algorithm token isn't in the shared migratability allowlist.
    Without this, cross-vendor render-into-Junos drops the user
    entirely (Finding-#16 fall-through).
    """
    intent = CanonicalIntent(
        hostname="md5crypt-tagged",
        local_users=[
            CanonicalLocalUser(
                name="legacy",
                privilege_level=15,
                hashed_password="md5crypt:$1$saltSalt$fakeHashPayload",
            ),
        ],
    )
    out = render_intent(intent)
    assert "set system login user legacy class super-user" in out
    assert (
        'set system login user legacy authentication encrypted-password '
        '"$1$saltSalt$fakeHashPayload"'
    ) in out
    # Tag is stripped on emit — only the bare $1$.. payload reaches
    # the rendered config.
    assert "md5crypt:" not in out
    # And no review comment for this user.
    assert "review:" not in out


def test_junos_user_with_cisco_type5_bare_digit_form_emits_auth_line() -> None:
    """Cisco IOS bare-digit form ``5 $1$..`` is the other shape a
    Cisco-source canonical may carry for an md5crypt password.
    Same expansion as the tagged form: payload is ``$1$..`` so
    Junos consumes it natively.  Mirrors Arista's ``_ARISTA_SECRET_TYPE``
    table where both ``5`` and ``md5crypt`` route to the same emit
    path.
    """
    intent = CanonicalIntent(
        hostname="cisco-bare-digit",
        local_users=[
            CanonicalLocalUser(
                name="cisco_admin",
                privilege_level=15,
                hashed_password="5 $1$ab$fakeHashFromCisco",
            ),
        ],
    )
    out = render_intent(intent)
    assert "set system login user cisco_admin class super-user" in out
    assert (
        'set system login user cisco_admin authentication '
        'encrypted-password "$1$ab$fakeHashFromCisco"'
    ) in out
    assert "review:" not in out


# ---------------------------------------------------------------------------
# Issue 2 — parser-side IRB l3-interface + vlan-members projection
# ---------------------------------------------------------------------------


def test_junos_parse_projects_irb_ip_to_vlan_ipv4_addresses() -> None:
    """``set vlans <NAME> l3-interface irb.<vid>`` declares the SVI
    binding; the IP on ``set interfaces irb unit <vid> family inet
    address ..`` (the canonical Junos form) must surface on
    ``CanonicalVlan.ipv4_addresses`` so VLAN-centric renderers
    (Aruba, OPNsense) can emit the SVI L3 line.
    """
    cfg = (
        "set vlans VLAN10 vlan-id 10\n"
        "set vlans VLAN10 l3-interface irb.10\n"
        "set interfaces irb unit 10 family inet address "
        "192.168.10.1/24\n"
    )
    intent = parse_intent(cfg)
    assert len(intent.vlans) == 1
    vlan = intent.vlans[0]
    assert vlan.id == 10
    assert len(vlan.ipv4_addresses) == 1
    assert vlan.ipv4_addresses[0].ip == "192.168.10.1"
    assert vlan.ipv4_addresses[0].prefix_length == 24


def test_junos_parse_projects_irb_ip_via_dotted_name_shorthand() -> None:
    """The dotted-name shorthand ``set interfaces irb.<vid> unit 0
    family inet address ..`` is the shape produced by block-form to
    set-form conversion when the source authored ``irb { unit <vid>
    { ... } }``.  These IPs land on the materialised
    ``CanonicalInterface(name="irb.<vid>")`` rather than in the
    ``irb_state`` accumulator (the accumulator branch only fires for
    ``name == "irb"``).  The post-pass must consult the materialised
    interface list as well so the SVI IP reaches the vlan regardless
    of which input shape the operator used.
    """
    cfg = (
        "set vlans VLAN10 vlan-id 10\n"
        "set vlans VLAN10 l3-interface irb.10\n"
        "set interfaces irb.10 unit 0 family inet address "
        "192.168.10.1/24\n"
    )
    intent = parse_intent(cfg)
    assert len(intent.vlans) == 1
    vlan = intent.vlans[0]
    assert len(vlan.ipv4_addresses) == 1
    assert vlan.ipv4_addresses[0].ip == "192.168.10.1"
    assert vlan.ipv4_addresses[0].prefix_length == 24
    # The redundant irb.10 iface gets pruned by the existing fold
    # logic since no load-bearing fields remain.
    assert all(i.name != "irb.10" for i in intent.interfaces)


def test_junos_parse_projects_vlan_members_to_tagged_ports() -> None:
    """``set interfaces <name> unit 0 family ethernet-switching
    vlan members <VNAME>`` without an explicit ``interface-mode``
    declaration must default to trunk semantics — the membership
    info would otherwise be silently dropped.  This complements
    the existing test_parse_projects_trunk_allowed_to_vlan_tagged_ports
    case (which exercises the ``interface-mode trunk`` branch).
    """
    cfg = (
        "set vlans VLAN10 vlan-id 10\n"
        "set interfaces ge-0/0/0 unit 0 family ethernet-switching "
        "vlan members VLAN10\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert "ge-0/0/0" in by_id[10].tagged_ports


def test_junos_round_trip_l3_interface_binding_preserved() -> None:
    """Full round-trip: a Junos config with both the SVI L3 binding
    AND a trunk port on the same VLAN must parse + render + reparse
    without losing either projection.  The rendered config can be
    fed back through parse_intent and produce the same canonical
    state.
    """
    cfg = (
        "set system host-name svi-test\n"
        "set vlans VLAN10 vlan-id 10\n"
        "set vlans VLAN10 l3-interface irb.10\n"
        "set interfaces irb unit 10 family inet address "
        "192.168.10.1/24\n"
        "set interfaces ge-0/0/0 unit 0 family ethernet-switching "
        "interface-mode trunk\n"
        "set interfaces ge-0/0/0 unit 0 family ethernet-switching "
        "vlan members VLAN10\n"
    )
    intent = parse_intent(cfg)
    # First parse: vlan has both the SVI IP and the trunk port.
    by_id = {v.id: v for v in intent.vlans}
    assert by_id[10].ipv4_addresses
    assert by_id[10].ipv4_addresses[0].ip == "192.168.10.1"
    assert "ge-0/0/0" in by_id[10].tagged_ports
    # Second parse (round-trip): same projections survive.
    rendered = render_intent(intent)
    reparsed = parse_intent(rendered)
    by_id2 = {v.id: v for v in reparsed.vlans}
    assert by_id2[10].ipv4_addresses
    assert by_id2[10].ipv4_addresses[0].ip == "192.168.10.1"
    assert "ge-0/0/0" in by_id2[10].tagged_ports
