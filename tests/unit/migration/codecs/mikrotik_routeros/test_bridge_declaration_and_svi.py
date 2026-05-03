"""Bridge-parent declaration + SVI interface naming for the
mikrotik_routeros renderer.

User smoke-test issue #4 (`tests/fixtures/real/user_smoke_findings.md`):
when a Cisco IOS-XE c9300 source was rendered to MikroTik, the output
contained `/interface vlan add interface=bridge1 name=vlan11
vlan-id=11` lines but never declared `bridge1` itself, so RouterOS
would refuse to commit the VLAN children (the parent didn't exist).
A separate symptom on the SVI-IP path emitted
`/ip address add address=192.168.11.252/24 interface=bridge.11` —
``bridge.11`` is not a real RouterOS interface (the dotted form
denotes a parent.id sub-interface, but the convention here is the
parent is ``bridge1`` not bare ``bridge``, and the renderer's
/interface vlan block emits ``name=vlanN``, so the SVI's canonical
name should follow that same convention).

These tests pin:

1. A `/interface bridge add name=bridge1` declaration is emitted
   exactly once when ANY VLAN references `bridge1`.
2. The synthetic declaration is suppressed when no VLAN exists.
3. The synthetic declaration is suppressed when the canonical tree
   already carries real bridge interfaces (same-vendor round-trip
   stability — guarded separately by
   `tests/unit/migration/test_real_captures.py`).
4. SVI canonical names with no `mikrotik_parent` hint format as
   ``vlanN`` (matching the /interface vlan emit), so the /ip address
   loop emits ``interface=vlanN`` rather than the broken
   ``interface=bridge.N`` form.

RouterOS reference: VLAN child interfaces are bound to a parent via
the ``interface=`` argument of `/interface vlan add`; the parent
must exist before the child is committed.  See RouterOS VLAN docs:
https://help.mikrotik.com/docs/spaces/ROS/pages/328068/VLAN
"""

from netconfig.migration.canonical.port_names import PortIdentity
from netconfig.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netconfig.migration.codecs.mikrotik_routeros.port_names import (
    format_port_identity,
)
from netconfig.migration.codecs.mikrotik_routeros.render import render_intent


def test_bridge_declaration_emitted_when_vlan_references_it():
    """When a VLAN-bound interface references bridge1, the renderer
    synthesises a `/interface bridge add name=bridge1` declaration."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="vlan11",
                interface_type="ianaift:l3ipvlan",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.168.11.252", prefix_length=24,
                    ),
                ],
            ),
        ],
        vlans=[CanonicalVlan(id=11, name="vlan11")],
    )

    out = render_intent(intent)

    assert "/interface bridge" in out
    assert "add name=bridge1" in out
    # And the /interface vlan section can safely reference the parent.
    assert "interface=bridge1" in out


def test_bridge_declaration_emitted_once_per_name():
    """Multiple VLANs referencing bridge1 must produce exactly one
    `/interface bridge add name=bridge1` line, not one per VLAN."""
    intent = CanonicalIntent(
        vlans=[
            CanonicalVlan(id=10, name="vlan10"),
            CanonicalVlan(id=11, name="vlan11"),
            CanonicalVlan(id=20, name="vlan20"),
            CanonicalVlan(id=100, name="vlan100"),
        ],
    )

    out = render_intent(intent)

    # Exactly one declaration of bridge1, even though four VLANs
    # reference it.
    assert out.count("add name=bridge1") == 1
    # Sanity: the four vlans are still emitted on the /interface vlan
    # side, all bound to bridge1.
    assert out.count("interface=bridge1") == 4


def test_no_bridge_declaration_when_no_vlan_uses_it():
    """A config with no VLANs and no VLAN-shaped interfaces must not
    emit a synthetic /interface bridge declaration."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="ether1", description="phys"),
            CanonicalInterface(name="ether2", description="phys"),
        ],
    )

    out = render_intent(intent)

    # No /interface bridge section at all.
    assert "/interface bridge" not in out
    assert "add name=bridge1" not in out


def test_synthetic_bridge1_skipped_when_real_bridge_present():
    """If the canonical tree already has bridge interfaces (same-
    vendor round-trip — RouterOS ``downstream``, ``upstream``, etc.),
    the synthetic ``bridge1`` declaration must NOT be added.

    Round-trip stability for real RouterOS captures (which DO carry
    bridges of their own) depends on this.  Without the suppression,
    a fixture with bridges named ``downstream`` / ``upstream`` would
    re-render with an extra phantom ``bridge1``, which the parser
    would then surface as a fourth bridge interface on the second
    pass — round-trip diff non-zero."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="downstream", interface_type="ianaift:bridge",
            ),
            CanonicalInterface(
                name="upstream", interface_type="ianaift:bridge",
            ),
        ],
        vlans=[CanonicalVlan(id=99, name="vlan99")],
    )

    out = render_intent(intent)

    assert "add name=downstream" in out
    assert "add name=upstream" in out
    # No synthetic bridge1 — real bridges already exist.
    assert "add name=bridge1" not in out


def test_svi_ip_uses_correct_vlan_interface_name():
    """SVI 192.168.11.252/24 on VLAN 11 must emit `interface=vlan11`
    (matching the /interface vlan section's `name=vlan11` emit), not
    the previous broken `interface=bridge.11` form."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="vlan11",
                interface_type="ianaift:l3ipvlan",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.168.11.252", prefix_length=24,
                    ),
                ],
            ),
        ],
        vlans=[CanonicalVlan(id=11, name="vlan11")],
    )

    out = render_intent(intent)

    # Positive: the /ip address row carries the matching vlan11 name.
    assert (
        "add address=192.168.11.252/24 interface=vlan11" in out
    ), f"expected interface=vlan11, output was:\n{out}"
    # Negative: the broken bridge.11 typo never appears.
    assert "interface=bridge.11" not in out


def test_format_port_identity_svi_falls_back_to_vlan_name():
    """The cross-vendor SVI fallback (no parent hint) yields
    ``vlanN``, not the previous ``bridge.N`` form.

    This is the unit-level pin for the bridge.11 typo: if anything
    upstream calls format_port_identity for an SVI without a
    mikrotik_parent meta hint, we want a real VLAN name out, not a
    sub-interface dotted form against a non-existent parent."""
    identity = PortIdentity(kind="svi", index=11)
    assert format_port_identity(identity) == "vlan11"


def test_format_port_identity_svi_preserves_explicit_parent():
    """When mikrotik_parent meta IS set, the dotted form is preserved
    (this is the same-vendor round-trip path, where the source bridge
    name was actually parsed from a /interface vlan ... interface=X
    line)."""
    identity = PortIdentity(
        kind="svi", index=11, meta={"mikrotik_parent": "bridge1"},
    )
    assert format_port_identity(identity) == "bridge1.11"
