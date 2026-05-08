"""Aruba AOS-S render: interface-name collision handling.

User-reported regression — pasting a Cisco c9300 IOS-XE config
targeting Aruba AOS-S produced two ``interface 1/1`` stanzas: one
from ``TenGigabitEthernet1/0/1`` and one from ``AppGigabitEthernet1/0/1``.
Both share the same stack/module/port coordinates and Aruba has no
dedicated app-hosting virtual concept, so the cross-vendor port-rename
collapses them to the same AOS-S name.  AOS-S rejects duplicate
``interface`` stanzas, so the renderer must dedupe and surface a
comment-form review block naming both colliders so the operator can
decide which to keep.

Approach: render-time collision detection (general — handles any
two canonical interfaces sharing a target Aruba name, not just the
AppGig/Te c9300 pair).  Emits the first stanza, suppresses
duplicates, prepends a ``; interface <nm> collides ...`` comment
block listing each collider's ``description`` (or fallback to
``name``) so operators have enough info to disambiguate.

See ``user_smoke_findings.md`` issue 3 for the source bug report.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

pytestmark = pytest.mark.unit


def test_app_gig_and_te_collision_dedups_or_demotes() -> None:
    """Two canonical interfaces sharing the same AOS-S name (after
    cross-vendor port-rename) must not produce two ``interface 1/1``
    stanzas — AOS-S rejects duplicate interface declarations.

    The synthetic setup mirrors the post-rename canonical state: both
    interfaces have ``name="1/1"`` (Aruba's ``format_port_identity``
    returned ``1/1`` for both Cisco source coordinates), distinguished
    only by their preserved ``description`` field.
    """
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="1/1",
                description="TenGigabitEthernet1/0/1",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
                ],
            ),
            CanonicalInterface(
                name="1/1",
                description="AppGigabitEthernet1/0/1",
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    # Exactly one ``interface 1/1`` stanza — duplicate suppressed.
    assert out.count("\ninterface 1/1\n") == 1
    # Collision is surfaced — comment block present.
    assert "interface 1/1 collides" in out


def test_collision_comment_names_both_source_ports() -> None:
    """The collision comment must name BOTH colliding sources so the
    operator can identify what got dropped vs kept.  ``description``
    is the realistic carrier (cross-vendor port-rename rewrites
    ``iface.name`` but preserves ``description``)."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="1/1",
                description="TenGigabitEthernet1/0/1",
            ),
            CanonicalInterface(
                name="1/1",
                description="AppGigabitEthernet1/0/1",
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    # Both colliding source descriptors appear in the comment block.
    assert "TenGigabitEthernet1/0/1" in out
    assert "AppGigabitEthernet1/0/1" in out
    # Comment marker present (lines must start with ``;`` to be
    # treated as comments by AOS-S).
    assert "; interface 1/1 collides" in out
    assert ";   collided source: TenGigabitEthernet1/0/1" in out
    assert ";   collided source: AppGigabitEthernet1/0/1" in out


def test_no_collision_no_comment() -> None:
    """Two interfaces with distinct AOS-S names must NOT trigger any
    collision comment — the dedup logic only fires on actual
    duplicates."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="1/1",
                description="TenGigabitEthernet1/0/1",
            ),
            CanonicalInterface(
                name="1/2",
                description="TenGigabitEthernet1/0/2",
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    # No collision comment leaked into the output.
    assert "collides" not in out
    # Both stanzas present.
    assert "\ninterface 1/1\n" in out
    assert "\ninterface 1/2\n" in out


def test_collision_skips_duplicate_stanza_body() -> None:
    """The duplicate's body (ip address, description, etc.) must NOT
    appear in the rendered output — only the kept first occurrence's
    body emits.  This is the load-bearing assertion: AOS-S rejects
    duplicate interface stanzas, so the duplicate's content has to be
    suppressed entirely."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="1/1",
                description="TenGigabitEthernet1/0/1",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
                ],
            ),
            CanonicalInterface(
                name="1/1",
                description="AppGigabitEthernet1/0/1",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.0.0.2", prefix_length=24),
                ],
            ),
        ],
    )
    out = ArubaAOSSCodec().render(intent)
    # First occurrence's address present.
    assert "10.0.0.1/24" in out
    # Duplicate's address NOT in output (would be an extra stanza).
    assert "10.0.0.2/24" not in out
