"""VLAN parent identification + user emit policy for the
mikrotik_routeros renderer.

User smoke-test issues #7, #12, #13 (`tests/fixtures/real/
user_smoke_findings.md`):

* #7 — for an OPNsense supergate source where ``ixl0`` carries the
  LAN IP AND all five VLANs, the render previously emitted the LAN
  IP on the renamed parent (``sfp-sfpplus0``) BUT bound the VLANs
  to a synthesised ``bridge1`` — splitting the topology and
  rendering five user networks unreachable.  The bridge synthesis
  was unconditional once a VLAN existed.  The fix makes
  synthesis conditional on whether a single source-side parent
  can be identified; when one CAN be, the VLANs bind to it
  instead.

* #12 — the canonical ``domain`` field has no clean RouterOS
  equivalent (no global ``ip domain name`` analogue; closest is
  the DHCP-client ``search-domain`` injected at runtime, which
  isn't a deterministic render output).  The renderer
  intentionally does NOT emit a domain command; verified here so
  future contributors don't add a half-broken ``/system identity
  set domain=...`` (RouterOS ignores unknown keys silently).

* #13 — the previous user-group mapping was an exact-value
  lookup (``{15: full, 10: write, 1: read}``) with a ``read``
  fallback, so any privilege level not exactly equal to one of
  those three keys fell through to ``read``.  Real captures
  populate the field with intermediate values (Junos
  ``super-user`` = 15, ``operator`` = 10, but custom roles get
  arbitrary ints).  Threshold-based mapping fixes this; safe
  default still ``read``.  Plaintext password emit + foreign-hash
  skip mirrors the wave-2 hash-gate policy from other codecs.

These tests pin:

1. Single-parent identification routes VLANs to that parent and
   skips bridge1 synthesis (positive case).
2. Zero-parent (Cisco-style switching topology with no L3 anchor)
   still synthesises bridge1 (regression guard for the c9300 fix
   from commit ``3f528b7``).
3. Single-parent + LAN IP + VLANs all share the same target name
   (the actual smoke-test bug — IP and VLANs were on disjoint
   interfaces).
4. Privilege thresholds: 15 → ``full``, 10 → ``write``, 1 →
   ``read``, intermediate values resolve via the cutoff rules.
5. Plaintext passwords emit a ``password=`` field; foreign hashes
   (bcrypt, type-9, etc.) skip the field entirely (no leak).
6. ``/system identity set domain=...`` is NOT emitted — RouterOS
   has no global domain command.
"""

import pytest
from netconfig.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalLocalUser,
    CanonicalVlan,
)
from netconfig.migration.codecs.mikrotik_routeros.render import (
    _routeros_group_for_privilege,
    render_intent,
)



pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Finding 7 — bridge synthesis conditional on VLAN parent identification
# ---------------------------------------------------------------------------


def test_vlans_with_explicit_parent_dont_synthesize_bridge():
    """Single non-VLAN/non-bridge/non-LAG interface with an L3 IP =
    the VLAN parent.  Output binds VLANs to that interface and
    emits NO ``/interface bridge add`` line.  Mirrors the OPNsense
    supergate smoke-test shape after rename: ``ixl0`` becomes
    ``sfp-sfpplus0`` carrying the LAN IP, with five VLANs alongside.
    """
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="sfp-sfpplus0",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.168.88.2", prefix_length=24,
                    ),
                ],
            ),
        ],
        vlans=[
            CanonicalVlan(id=10, name="USER VLAN"),
            CanonicalVlan(id=11, name="MGMT VLAN"),
            CanonicalVlan(id=20, name="SERVER VLAN"),
            CanonicalVlan(id=100, name="CLUSTER VLAN"),
            CanonicalVlan(id=150, name="IOT VLAN"),
        ],
    )

    out = render_intent(intent)

    # No /interface bridge section synthesised.
    assert "add name=bridge1" not in out, (
        f"unexpected bridge1 synthesis when ixl0/sfp-sfpplus0 is "
        f"the VLAN parent\n--- output ---\n{out}"
    )
    # VLAN children bind directly to the parent's renamed name.
    for vid in (10, 11, 20, 100, 150):
        assert (
            f"interface=sfp-sfpplus0 name=vlan{vid} vlan-id={vid}" in out
        ), f"VLAN {vid} did not bind to sfp-sfpplus0:\n{out}"
    # No phantom bridge-bound VLANs.
    assert "interface=bridge1" not in out


def test_vlans_without_explicit_parent_still_synthesize_bridge():
    """Regression guard for the c9300 bridge-synth case (commit
    ``3f528b7``).  When canonical has VLANs but NO single
    parent candidate, fall back to synthesising ``bridge1`` so
    VLAN children have *some* parent on the wire.  Without this
    guard, a Cisco-style switching topology with many trunk
    ports would re-introduce the original "no bridge declared"
    bug.
    """
    intent = CanonicalIntent(
        vlans=[
            CanonicalVlan(id=10, name="vlan10"),
            CanonicalVlan(id=11, name="vlan11"),
            CanonicalVlan(id=20, name="vlan20"),
        ],
    )

    out = render_intent(intent)

    # Synthetic bridge1 still emitted when no parent identifiable.
    assert "/interface bridge" in out
    assert "add name=bridge1" in out
    # And VLANs bind to it.
    assert out.count("interface=bridge1") == 3


def test_vlans_with_explicit_parent_lan_ip_and_vlans_share_parent():
    """The actual smoke-test bug pin: source has LAN IP on ``ixl0``
    AND five VLANs whose parent is ``ixl0``.  After cross-vendor
    rename, ``ixl0`` is ``sfp-sfpplus0``.  Output must place the
    LAN IP and the VLAN children on the SAME target name (no
    split between sfp-sfpplus0 and a synthetic bridge1).
    """
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="sfp-sfpplus0",
                description="LAN",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.168.88.2", prefix_length=24,
                    ),
                ],
            ),
        ],
        vlans=[
            CanonicalVlan(id=10, name="USER VLAN"),
            CanonicalVlan(id=11, name="MGMT VLAN"),
        ],
    )

    out = render_intent(intent)

    # The LAN IP lands on sfp-sfpplus0.
    assert (
        "add address=192.168.88.2/24 interface=sfp-sfpplus0" in out
    ), f"LAN IP not on sfp-sfpplus0:\n{out}"
    # The VLANs land on sfp-sfpplus0 too.
    assert (
        "interface=sfp-sfpplus0 name=vlan10 vlan-id=10" in out
    ), f"VLAN 10 not on sfp-sfpplus0:\n{out}"
    assert (
        "interface=sfp-sfpplus0 name=vlan11 vlan-id=11" in out
    ), f"VLAN 11 not on sfp-sfpplus0:\n{out}"
    # And the topology stays cohesive — no bridge1 synthesis at all.
    assert "bridge1" not in out


def test_real_bridge_present_skips_synth_and_isnt_picked_as_parent():
    """A canonical tree with an explicit bridge interface (same-vendor
    round-trip case) keeps that bridge as the VLAN parent.  The
    parent-detection loop EXCLUDES bridge-typed interfaces so we
    don't accidentally pick the bridge itself as the
    ``vlan_parent_name`` — the existing same-vendor convention is
    that VLANs reference the bridge by name and the bridge's
    ``add name=...`` line survives.
    """
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="downstream", interface_type="ianaift:bridge",
            ),
        ],
        vlans=[CanonicalVlan(id=99, name="vlan99")],
    )

    out = render_intent(intent)

    # The real bridge survives as a parent.
    assert "add name=downstream" in out
    # No phantom bridge1.
    assert "add name=bridge1" not in out


def test_multiple_l3_candidates_falls_back_to_bridge_synth():
    """When multiple non-VLAN ports carry IPs (multi-WAN /
    multi-tenant), there's no unambiguous single parent.  Fall
    back to synthesising bridge1 — wrong-but-deployable beats
    arbitrarily picking one of the candidates and silently
    routing VLANs to the wrong port.
    """
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="ether1",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.0.1.1", prefix_length=24,
                    ),
                ],
            ),
            CanonicalInterface(
                name="ether2",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.0.2.1", prefix_length=24,
                    ),
                ],
            ),
        ],
        vlans=[CanonicalVlan(id=10, name="vlan10")],
    )

    out = render_intent(intent)

    # Falls back to synthetic bridge1 — exactly one candidate is
    # the rule, two L3 ports = ambiguous.
    assert "add name=bridge1" in out
    assert "interface=bridge1 name=vlan10 vlan-id=10" in out


def test_loopback_excluded_from_parent_candidates():
    """Loopback interfaces with IPs (every L3 router has at least
    one) must NOT count as a VLAN-parent candidate — they have
    no L2 forwarding plane.  The OPNsense supergate fixture has
    ``lo0``; without explicit exclusion, lo0 + ixl0 would be two
    candidates and we'd fall back to bridge1.
    """
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="sfp-sfpplus0",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.168.88.2", prefix_length=24,
                    ),
                ],
            ),
            CanonicalInterface(
                name="lo0",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="127.0.0.1", prefix_length=8,
                    ),
                ],
            ),
        ],
        vlans=[CanonicalVlan(id=10, name="vlan10")],
    )

    out = render_intent(intent)

    # sfp-sfpplus0 is the only non-loopback candidate → it wins.
    assert "interface=sfp-sfpplus0 name=vlan10 vlan-id=10" in out
    assert "add name=bridge1" not in out


# ---------------------------------------------------------------------------
# Finding 13 — privilege threshold mapping
# ---------------------------------------------------------------------------


def test_user_with_privilege_15_maps_to_full_group():
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(name="root", privilege_level=15),
        ],
    )
    out = render_intent(intent)
    assert "add group=full name=root" in out, out


def test_user_with_privilege_10_maps_to_write_group():
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(name="ops", privilege_level=10),
        ],
    )
    out = render_intent(intent)
    assert "add group=write name=ops" in out, out


def test_user_with_low_privilege_maps_to_read_group():
    """privilege=1 (the canonical default) → ``read``."""
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(name="guest", privilege_level=1),
        ],
    )
    out = render_intent(intent)
    assert "add group=read name=guest" in out, out


def test_intermediate_privilege_uses_threshold_cutoffs():
    """Privilege levels between thresholds resolve to the lower
    cutoff.  12 falls between write(10) and full(15) → ``write``.
    20 is above full(15) → ``full``.  3 is below write(10) →
    ``read``.
    """
    assert _routeros_group_for_privilege(20) == "full"
    assert _routeros_group_for_privilege(15) == "full"
    assert _routeros_group_for_privilege(12) == "write"
    assert _routeros_group_for_privilege(10) == "write"
    assert _routeros_group_for_privilege(3) == "read"
    assert _routeros_group_for_privilege(0) == "read"


# ---------------------------------------------------------------------------
# Finding 13 — password emit gating
# ---------------------------------------------------------------------------


def test_user_with_plaintext_password_emits_password_field():
    """Plaintext passwords ARE migratable to RouterOS — emit the
    ``password=`` field so the operator doesn't have to set it
    manually post-migration.
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="hunter2",
            ),
        ],
    )
    out = render_intent(intent)
    assert "add group=full name=admin password=hunter2" in out, out


def test_user_with_plaintext_password_quotes_when_needed():
    """A plaintext password with a space gets quoted via the
    standard ``_quote_if_needed`` helper so RouterOS parses it as
    a single value.
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="my secret pass",
            ),
        ],
    )
    out = render_intent(intent)
    assert 'password="my secret pass"' in out, out


def test_user_with_foreign_hash_emits_no_password_field():
    """OPNsense bcrypt hashes (``bcrypt:$2y$11$...``) are NOT
    migratable to RouterOS — RouterOS uses its own internal
    password storage and rejects foreign hash formats.  Skip the
    field entirely so the literal hash string doesn't leak as a
    plaintext-equivalent password (an auth bypass for anyone
    with read access to the original config).
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(
                name="root",
                privilege_level=15,
                hashed_password=(
                    "bcrypt:$2y$11$fakeBcryptHashForRootUserExample"
                    "ValueNotRealOOOOOOOO"
                ),
            ),
            CanonicalLocalUser(
                name="cisco",
                privilege_level=15,
                hashed_password="9 $9$fakeType9Hash$",
            ),
            CanonicalLocalUser(
                name="arista",
                privilege_level=15,
                hashed_password=(
                    "arista:sha512:$6$fakesha512crypthash"
                ),
            ),
        ],
    )
    out = render_intent(intent)

    # All three foreign hashes skip the password field on the
    # user's ``add ... name=<n>`` line.  The review-comment line
    # carries ``user-name "<n>"`` which doesn't match the
    # ``name=<n>`` substring, so we limit the check to add lines.
    for line_user in ("root", "cisco", "arista"):
        for line in out.splitlines():
            if f" name={line_user}" in line:
                assert "password=" not in line, (
                    f"foreign-hash leak on user {line_user!r}: {line!r}"
                )
    # The literal hash payloads must never appear anywhere in the
    # output — neither in the add line nor in the review comment.
    assert "$2y$11$" not in out
    assert "$9$fakeType9Hash" not in out
    assert "$6$fakesha512crypthash" not in out


# ---------------------------------------------------------------------------
# Finding 18 — review-comment line for unmigratable hashes
# ---------------------------------------------------------------------------


def test_mikrotik_unmigratable_hash_emits_review_comment():
    """Foreign bcrypt hash from OPNsense → RouterOS render emits a
    ``# password manager user-name "<n>" -- review: bcrypt hash …``
    line immediately above the ``add group=... name=<n>`` line.
    Without this signal an operator reading the migrated config
    sees a user with no password and no hint that one ever
    existed.  The user is still added (the comment supplements,
    doesn't replace, the ``add`` line).  Surfaced as issue #18 in
    ``tests/fixtures/real/user_smoke_findings.md``.
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(
                name="root",
                privilege_level=15,
                hashed_password=(
                    "bcrypt:$2y$11$fakeBcryptHashForReviewLineTest"
                ),
            ),
        ],
    )
    out = render_intent(intent)

    expected_comment = (
        '# password manager user-name "root" -- review: bcrypt hash '
        "from source vendor cannot be re-used on RouterOS; reset "
        "this user password manually"
    )
    assert expected_comment in out, (
        f"expected review comment not found in render output:\n{out}"
    )
    # The user is still added with the right group / name — the
    # comment supplements rather than replaces the add line.
    assert "add group=full name=root" in out, out

    # The comment line precedes the add line (interleaved shape).
    lines = out.splitlines()
    comment_idx = next(
        i for i, line in enumerate(lines)
        if line == expected_comment
    )
    add_idx = next(
        i for i, line in enumerate(lines)
        if line == "add group=full name=root"
    )
    assert comment_idx < add_idx, (
        f"comment line at {comment_idx} expected before add line at "
        f"{add_idx}\n{out}"
    )


def test_mikrotik_user_with_no_hashed_password_no_comment():
    """A user with an empty ``hashed_password`` (canonical default)
    has no hash to review — emit the ``add`` line cleanly without
    a spurious comment.  Regression guard so we don't pollute the
    output when the source genuinely had no password.
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(name="bare", privilege_level=15),
        ],
    )
    out = render_intent(intent)
    assert "add group=full name=bare" in out
    # No review comment at all.
    assert "review:" not in out, out
    assert "password manager" not in out, out


def test_mikrotik_user_with_plaintext_password_no_comment():
    """Plaintext passwords ARE migratable to RouterOS — the
    ``password=`` field emits and NO review comment is needed.
    The comment is only for hashes RouterOS can't consume.
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="hunter2",
            ),
        ],
    )
    out = render_intent(intent)
    assert "add group=full name=admin password=hunter2" in out
    assert "review:" not in out, out
    assert "password manager" not in out, out


def test_mikrotik_review_comment_uses_routeros_label():
    """The ``target_label="RouterOS"`` parameter to
    ``format_review_comment`` is threaded through so the operator
    sees the actual target name rather than the helper's generic
    ``"this target"`` default.  Phase-2 helper extension (commit
    ``0074bda``) added the parameter; this test pins the call shape.
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(
                name="op",
                privilege_level=10,
                hashed_password="9 $9$fakeType9Hash$",
            ),
        ],
    )
    out = render_intent(intent)
    # Generic default must NOT leak through.
    assert "this target" not in out, out
    # RouterOS label appears in the review-line wording.
    assert "cannot be re-used on RouterOS" in out, out


def test_user_with_empty_hash_emits_no_password_field():
    """An empty ``hashed_password`` (canonical default) skips the
    password field — there's nothing to emit.
    """
    intent = CanonicalIntent(
        local_users=[
            CanonicalLocalUser(name="bare", privilege_level=15),
        ],
    )
    out = render_intent(intent)
    assert "add group=full name=bare" in out
    # No password field at all.
    for line in out.splitlines():
        if "name=bare" in line:
            assert "password=" not in line, line


# ---------------------------------------------------------------------------
# Finding 12 — domain emit (deliberately N/A for RouterOS)
# ---------------------------------------------------------------------------


def test_canonical_domain_does_not_emit_routeros_domain_command():
    """RouterOS has no global ``ip domain name`` analogue — the
    closest equivalents are DHCP-client ``search-domain``
    (runtime, not config) and per-record ``/ip dns static`` FQDN
    entries.  The renderer intentionally drops
    :attr:`CanonicalIntent.domain` rather than emitting a
    half-broken ``/system identity set domain=...`` (RouterOS
    silently ignores unknown keys, so the operator wouldn't see
    the failure until they tried to resolve a short hostname).

    This test pins the deliberate omission so a future contributor
    doesn't add domain-emit without re-checking the RouterOS
    grammar.  Document the decision in
    ``tests/fixtures/real/user_smoke_findings.md`` issue #12 if
    behaviour ever changes.
    """
    intent = CanonicalIntent(
        hostname="router",
        domain="example.test",
    )
    out = render_intent(intent)
    # /system identity emits hostname only.
    assert "set name=router" in out
    # Domain MUST NOT appear — neither as a key nor as a value.
    assert "domain=" not in out, out
    assert "example.test" not in out, out
