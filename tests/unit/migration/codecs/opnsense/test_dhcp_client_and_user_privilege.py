"""
Unit tests for two OPNsense parser canonical-layer gaps surfaced by
the user smoke wave:

* **Sub-finding 9a** — ``<ipaddr>dhcp</ipaddr>`` (DHCP-client keyword)
  was silently dropped on parse.  The static-IP branch tried to coerce
  ``"dhcp"`` to a CanonicalIPv4Address and either fell through silently
  (most paths) or raised a parse error (one synthetic path).  Either
  way ``CanonicalInterface.dhcp_client`` was never set, so cross-vendor
  renders that consume it (Cisco IOS-XE ``ip address dhcp``, MikroTik
  RouterOS DHCP client config, Junos ``family inet dhcp``) emitted
  nothing for OPNsense WAN-on-DHCP sources.

* **Sub-finding 19** — OPNsense's WebGUI-privilege model (``<scope>
  system</scope>`` for built-in admin accounts; ``<priv>page-all</priv>``
  for explicit "All pages" grants on user-scope accounts) was ignored
  by the parser, which only consulted ``<groupname>``.  Real OPNsense
  exports keep group membership under ``<system>/<group>/<member>UID,
  UID</member>`` rather than per-user ``<groupname>``, so root + api
  users from a real config landed at ``privilege_level=1`` and rendered
  as ``add group=read name=root`` on RouterOS — the opposite of the
  intent.

See also:
- ``tests/fixtures/real/user_smoke_findings.md`` — sub-findings 9a + 19
- ``netconfig/migration/codecs/opnsense/parse.py`` — fix locations
- ``netconfig/migration/codecs/opnsense/render.py`` — symmetric
  privilege-15 emission for round-trip stability
- OPNsense docs: https://docs.opnsense.org/manual/interfaces.html
  (DHCP client) and https://docs.opnsense.org/manual/firewall_users.html
  (User privileges)
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
)
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec
from netconfig.migration.codecs.opnsense.parse import parse_intent
from netconfig.migration.codecs.opnsense.render import render_intent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Sub-finding 9a — ``<ipaddr>dhcp</ipaddr>`` sets dhcp_client
# ---------------------------------------------------------------------------


def test_opnsense_parse_wan_dhcp_sets_dhcp_client() -> None:
    """The canonical bug shape: WAN zone declares
    ``<ipaddr>dhcp</ipaddr>`` for a DHCP-client uplink.  Parser MUST
    set ``CanonicalInterface.dhcp_client = True`` and skip the
    static-IP append (``"dhcp"`` is not a valid IPv4 address)."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <wan>
      <if>igc0</if>
      <enable/>
      <ipaddr>dhcp</ipaddr>
    </wan>
  </interfaces>
</opnsense>
"""
    intent = parse_intent(raw)
    assert len(intent.interfaces) == 1
    iface = intent.interfaces[0]
    assert iface.name == "igc0"
    assert iface.dhcp_client is True
    # No bogus static IPv4 entry should be synthesised from the
    # "dhcp" keyword text.
    assert iface.ipv4_addresses == []


def test_opnsense_parse_lan_static_ip_dhcp_client_false() -> None:
    """Regression guard: a static-IP zone must NOT have
    ``dhcp_client`` set to True (default).  Confirms the new branch
    is keyword-gated rather than always-on."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <lan>
      <if>igc1</if>
      <enable/>
      <ipaddr>192.168.88.2</ipaddr>
      <subnet>24</subnet>
    </lan>
  </interfaces>
</opnsense>
"""
    intent = parse_intent(raw)
    iface = intent.interfaces[0]
    assert iface.dhcp_client is False
    assert len(iface.ipv4_addresses) == 1
    assert iface.ipv4_addresses[0].ip == "192.168.88.2"
    assert iface.ipv4_addresses[0].prefix_length == 24


def test_opnsense_parse_dhcp_uppercase_handled() -> None:
    """Operators occasionally type ``DHCP`` in upper-case.  Match
    must be case-insensitive — the keyword is not address data so
    the casing is purely cosmetic."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <wan>
      <if>igc0</if>
      <ipaddr>DHCP</ipaddr>
    </wan>
  </interfaces>
</opnsense>
"""
    intent = parse_intent(raw)
    iface = intent.interfaces[0]
    assert iface.dhcp_client is True
    assert iface.ipv4_addresses == []


def test_opnsense_parse_dhcp6_v6_populates_canonical_field() -> None:
    """``<ipaddrv6>dhcp6</ipaddrv6>`` (or ``slaac`` / ``track6`` /
    ``6rd`` / ``6to4``) now wire-throughs to
    :attr:`CanonicalInterface.dhcp_client_v6` — see the validation
    cleanup wave that added the schema field.  Parser must NOT raise
    and must NOT synthesise a bogus static IPv6 record."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <wan>
      <if>igc0</if>
      <ipaddrv6>dhcp6</ipaddrv6>
    </wan>
  </interfaces>
</opnsense>
"""
    intent = parse_intent(raw)
    iface = intent.interfaces[0]
    assert iface.ipv6_addresses == []
    # No spurious dhcp_client (that's the v4 flag).
    assert iface.dhcp_client is False
    # NEW: dhcp_client_v6 surfaces the v6 mode for cross-vendor render.
    assert iface.dhcp_client_v6 == "dhcp6"


def test_opnsense_parse_slaac_v6_populates_canonical_field() -> None:
    """SLAAC variant of the dhcp_client_v6 wire-through."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <wan>
      <if>igc0</if>
      <ipaddrv6>slaac</ipaddrv6>
    </wan>
  </interfaces>
</opnsense>
"""
    intent = parse_intent(raw)
    iface = intent.interfaces[0]
    assert iface.ipv6_addresses == []
    assert iface.dhcp_client_v6 == "slaac"


# ---------------------------------------------------------------------------
# Sub-finding 19 — scope=system / priv=page-all elevate to admin
# ---------------------------------------------------------------------------


def test_opnsense_parse_system_scope_user_gets_privilege_15() -> None:
    """Real-OPNsense root account shape: ``<scope>system</scope>`` with
    NO ``<groupname>`` element (group membership lives under
    ``<system>/<group>/<member>0</member>``).  Parser must treat the
    system scope as admin in the absence of an explicit groupname."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <system>
    <user>
      <name>root</name>
      <uid>0</uid>
      <scope>system</scope>
    </user>
  </system>
</opnsense>
"""
    intent = parse_intent(raw)
    assert len(intent.local_users) == 1
    user = intent.local_users[0]
    assert user.name == "root"
    assert user.privilege_level == 15
    assert user.role == "admin"


def test_opnsense_parse_page_all_priv_gets_privilege_15() -> None:
    """Real-OPNsense API account shape: ``<scope>user</scope>`` with
    explicit ``<priv>page-all</priv>`` (the "WebGUI - All pages"
    privilege).  Parser must elevate to admin even though scope is
    user and groupname is absent."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <system>
    <user>
      <name>api</name>
      <uid>2000</uid>
      <scope>user</scope>
      <priv>page-all</priv>
    </user>
  </system>
</opnsense>
"""
    intent = parse_intent(raw)
    user = intent.local_users[0]
    assert user.name == "api"
    assert user.privilege_level == 15
    assert user.role == "admin"


def test_opnsense_parse_regular_user_keeps_default_privilege() -> None:
    """``<scope>user</scope>`` with no ``<priv>`` and no
    ``<groupname>`` must remain at the default privilege (1) — the
    new heuristic must not over-fire on plain user accounts."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <system>
    <user>
      <name>guest</name>
      <uid>2001</uid>
      <scope>user</scope>
    </user>
  </system>
</opnsense>
"""
    intent = parse_intent(raw)
    user = intent.local_users[0]
    assert user.privilege_level == 1
    assert user.role == "user"


def test_opnsense_parse_groupname_users_overrides_system_scope() -> None:
    """Regression guard for the existing
    ``test_scope_does_not_determine_privilege`` semantic: when
    ``<groupname>`` IS present and explicitly says ``users``, it
    overrides scope=system.  Some legacy / synthetic configs use
    per-user ``<groupname>`` as the privilege carrier; we must not
    silently re-elevate them via scope alone."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <system>
    <user>
      <name>sysuser</name>
      <scope>system</scope>
      <groupname>users</groupname>
    </user>
  </system>
</opnsense>
"""
    intent = parse_intent(raw)
    user = intent.local_users[0]
    assert user.privilege_level == 1
    assert user.role == "user"


def test_opnsense_parse_priv_other_than_page_all_does_not_elevate() -> None:
    """Only the ``page-all`` token grants admin; other ``<priv>``
    tokens (``page-system-firmware``, etc.) carry narrower grants
    and must not over-fire admin elevation."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <system>
    <user>
      <name>updater</name>
      <scope>user</scope>
      <priv>page-system-firmware</priv>
    </user>
  </system>
</opnsense>
"""
    intent = parse_intent(raw)
    user = intent.local_users[0]
    assert user.privilege_level == 1


# ---------------------------------------------------------------------------
# End-to-end: OPNsense → MikroTik RouterOS (the actual bug shape from
# user_smoke_findings.md issue 19)
# ---------------------------------------------------------------------------


def test_opnsense_to_routeros_admin_user_maps_to_full_group() -> None:
    """The end-to-end signal that pinned the bug: an OPNsense source
    with a system-scope root user must produce
    ``add group=full name=root`` on the MikroTik RouterOS render
    (not the safe-default ``group=read``).  Pre-fix this rendered
    as read because privilege_level=1 was the parser default."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <system>
    <hostname>fw01</hostname>
    <user>
      <name>root</name>
      <uid>0</uid>
      <scope>system</scope>
      <password>$2y$10$fakeBcryptForTestSyntheticHashPlaceholder000000000000</password>
    </user>
  </system>
</opnsense>
"""
    intent = OPNsenseCodec().parse(raw)
    out = MikroTikRouterOSCodec().render(intent)
    assert "add group=full name=root" in out, out
    # And the read-group safe default must NOT have leaked.
    assert "add group=read name=root" not in out


# ---------------------------------------------------------------------------
# Round-trip: render emits scope=system + priv=page-all symmetrically
# ---------------------------------------------------------------------------


def test_opnsense_render_admin_user_emits_symmetric_scope_and_priv() -> None:
    """A canonical admin user (privilege_level=15) must render with
    ``<scope>system</scope>`` AND ``<priv>page-all</priv>`` so that
    re-parsing the rendered XML re-derives privilege_level=15 even
    when the synthetic input lacked the per-user ``<groupname>``."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="root",
            privilege_level=15,
            hashed_password="bcrypt:$2y$10$fakehashvalue",
        )],
    )
    out = render_intent(intent)
    assert "<scope>system</scope>" in out
    assert "<priv>page-all</priv>" in out
    assert "<groupname>admins</groupname>" in out


def test_opnsense_render_regular_user_emits_user_scope() -> None:
    """A canonical non-admin user (privilege_level=1) must render
    with ``<scope>user</scope>`` so that re-parsing under the new
    parser heuristic doesn't mis-elevate it."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="viewer",
            privilege_level=1,
            hashed_password="bcrypt:$2y$10$fakeotherhash",
        )],
    )
    out = render_intent(intent)
    assert "<scope>user</scope>" in out
    assert "<priv>page-all</priv>" not in out
    assert "<groupname>users</groupname>" in out


def test_opnsense_round_trip_admin_user_via_scope_only() -> None:
    """Parse a real-OPNsense-shaped admin user (scope=system, no
    groupname), render, re-parse — privilege_level must survive
    both passes unchanged."""
    raw = """<?xml version="1.0"?>
<opnsense>
  <system>
    <user>
      <name>root</name>
      <uid>0</uid>
      <scope>system</scope>
      <password>$2y$10$fakehash</password>
    </user>
  </system>
</opnsense>
"""
    codec = OPNsenseCodec()
    first = codec.parse(raw)
    second = codec.parse(codec.render(first))
    assert first.local_users[0].privilege_level == 15
    assert second.local_users[0].privilege_level == 15
    assert first.local_users[0] == second.local_users[0]
