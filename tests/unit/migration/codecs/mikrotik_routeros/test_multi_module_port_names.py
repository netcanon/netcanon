"""Cross-vendor port-name disambiguation for the mikrotik_routeros
codec.

User smoke-test issue #7 (`tests/fixtures/real/user_smoke_findings.md`):
when a Cisco IOS-XE c9300 source with 41 ports across multiple
modules (`Te1/0/1..24`, `Gi1/1/1..4`, `Te1/1/1..8`, `Fo1/1/1..2`,
`Twe1/1/1..2`, `App1/0/1`, `Gi0/0`) was rendered to MikroTik, every
non-zero-module port collapsed to the same RouterOS name —
`sfp-sfpplus1` was emitted multiple times because the formatter
ignored ``identity.module`` and ``identity.stack`` and used only
``identity.port`` as the suffix.  RouterOS rejects duplicate
``set [ find name=sfp-sfpplus1 ]`` lines.

These tests pin the new flat-index disambiguation scheme:

1. Multi-module 10G ports get UNIQUE RouterOS names (no two
   identities collapse to the same string).
2. Single-module / single-stack identities (the historical
   common case) retain the existing ``sfp-sfpplus1`` /
   ``sfp-sfpplus2`` numbering — the fix is strictly additive.
3. Full integration: a synthetic c9300-shaped ``CanonicalIntent``
   passed through the cross-vendor orchestrator + RouterOS
   renderer produces no duplicate ``set [ find name=...`` lines.

RouterOS reference: ``ether<N>`` / ``sfp<N>`` / ``sfp-sfpplus<N>``
/ ``qsfpplus<N>`` are FLAT-NUMBERED (no per-module slot in the
port name) — see
https://help.mikrotik.com/docs/spaces/ROS/pages/8323191/Ethernet
and
https://help.mikrotik.com/docs/spaces/ROS/pages/220233794/MikroTik+wired+interface+compatibility .
QSFP sub-lanes use the dotted ``qsfpplus<port>-<lane>`` form, but
the per-PORT numbering (the bit before the dash) is still flat.
25G ports use a distinct ``sfp28-<N>`` cage prefix on hardware
that ships SFP28 (CCR2004-1G-12S+2XS).
"""

import pytest
from netconfig.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
)
from netconfig.migration.canonical.port_names import (
    PortIdentity,
    translate_port_names,
)
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.mikrotik_routeros import (
    MikroTikRouterOSCodec,
)
from netconfig.migration.codecs.mikrotik_routeros.port_names import (
    format_port_identity,
)
from netconfig.migration.codecs.mikrotik_routeros.render import (
    render_intent,
)



pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# 1. Multi-module 10G ports must produce distinct names.
# ---------------------------------------------------------------------------


def test_multi_module_10g_ports_get_unique_names():
    """``Te1/0/1..24`` (module 0) plus ``Te1/1/1..8`` (module 1)
    is 32 distinct physical 10G ports in the Cisco source.  The
    target MikroTik formatter must produce 32 distinct strings —
    one per source identity — so the renderer's
    ``set [ find name=...`` loop doesn't emit duplicates.
    """
    identities: list[PortIdentity] = []
    # Module 0: 24 baseboard 10G ports.
    for port in range(1, 25):
        identities.append(
            PortIdentity(
                kind="physical",
                stack=1,
                module=0,
                port=port,
                name_speed_hint="10gig",
            )
        )
    # Module 1: 8 uplink 10G ports.
    for port in range(1, 9):
        identities.append(
            PortIdentity(
                kind="physical",
                stack=1,
                module=1,
                port=port,
                name_speed_hint="10gig",
            )
        )

    rendered = [format_port_identity(i) for i in identities]

    # No None — every physical 10G should map to a real name.
    assert all(name is not None for name in rendered), rendered
    # All distinct.
    assert len(set(rendered)) == len(rendered), (
        f"duplicate names from multi-module 10G input: "
        f"{[n for n in rendered if rendered.count(n) > 1]}"
    )
    # All start with the 10G cage prefix.
    for name in rendered:
        assert name.startswith("sfp-sfpplus"), (
            f"expected sfp-sfpplus prefix for 10G hint, got {name!r}"
        )


def test_multi_module_mixed_speeds_get_unique_names():
    """A c9300 stack mixes 10G baseboard, 1G uplink, 25G uplink, and
    40G uplink in different modules.  The cage-type partitioning
    (10G→sfp-sfpplus, 25G→sfp28-, 40G→qsfpplus, 1G→ether) plus
    the flat-index spread keeps every name distinct even when two
    different speeds occupy the same module.
    """
    sources: list[PortIdentity] = [
        # 24 baseboard 10G ports (Te1/0/1..24).
        *[
            PortIdentity(
                kind="physical", stack=1, module=0, port=p,
                name_speed_hint="10gig",
            )
            for p in range(1, 25)
        ],
        # 4 module-1 1G ports (Gi1/1/1..4).
        *[
            PortIdentity(
                kind="physical", stack=1, module=1, port=p,
                name_speed_hint="gig",
            )
            for p in range(1, 5)
        ],
        # 8 module-1 10G ports (Te1/1/1..8).
        *[
            PortIdentity(
                kind="physical", stack=1, module=1, port=p,
                name_speed_hint="10gig",
            )
            for p in range(1, 9)
        ],
        # 2 module-1 40G ports (Fo1/1/1..2).
        *[
            PortIdentity(
                kind="physical", stack=1, module=1, port=p,
                name_speed_hint="40gig",
            )
            for p in range(1, 3)
        ],
        # 2 module-1 25G ports (Twe1/1/1..2).
        *[
            PortIdentity(
                kind="physical", stack=1, module=1, port=p,
                name_speed_hint="25gig",
            )
            for p in range(1, 3)
        ],
    ]

    rendered = [format_port_identity(i) for i in sources]
    assert len(set(rendered)) == len(rendered), (
        f"collision across multi-module mixed-speed ports: "
        f"counts={ {n: rendered.count(n) for n in rendered if rendered.count(n) > 1} }"
    )


def test_stack_member_2_disjoint_from_member_1():
    """Stack member 2's port 1 must not collide with member 1's
    port 1 — multi-stack switches are common (c9300 stacks of
    4-8 members are typical).
    """
    a = PortIdentity(
        kind="physical", stack=1, module=0, port=1,
        name_speed_hint="10gig",
    )
    b = PortIdentity(
        kind="physical", stack=2, module=0, port=1,
        name_speed_hint="10gig",
    )
    assert format_port_identity(a) != format_port_identity(b), (
        f"stack member 1 vs 2 collision: a={format_port_identity(a)!r} "
        f"b={format_port_identity(b)!r}"
    )


# ---------------------------------------------------------------------------
# 2. Single-module / pre-fix identities preserve historical names.
# ---------------------------------------------------------------------------


def test_module_zero_compatible_with_existing_naming():
    """A pure single-module input (``stack=None`` or ``stack=1`` with
    ``module=None`` or ``module=0``) must continue to produce
    ``sfp-sfpplus1``, ``sfp-sfpplus2``, ... — the fix is strictly
    additive and must not perturb the historical numbering used by
    every same-vendor MikroTik round-trip and every cross-vendor
    test fixture that predates the fix.
    """
    # Native MikroTik shape: just port=N, no stack / module.
    for port in range(1, 25):
        ident = PortIdentity(
            kind="physical", port=port, name_speed_hint="10gig",
            meta={"mikrotik_cage": "sfpplus"},
        )
        assert format_port_identity(ident) == f"sfp-sfpplus{port}"

    # Cisco-shape with explicit stack=1, module=0 (the most common
    # c9300 baseboard case): same numeric outputs.
    for port in range(1, 25):
        ident = PortIdentity(
            kind="physical", stack=1, module=0, port=port,
            name_speed_hint="10gig",
        )
        assert format_port_identity(ident) == f"sfp-sfpplus{port}"

    # 1G ether default also unchanged.
    for port in range(1, 9):
        ident = PortIdentity(
            kind="physical", stack=1, module=0, port=port,
            name_speed_hint="gig",
        )
        assert format_port_identity(ident) == f"ether{port}"


def test_single_module_qsfp_unchanged():
    """40G/100G physical ports on module 0 still emit ``qsfpplus<N>``
    with the bare port number — no module suffix when not needed.
    """
    for port in range(1, 5):
        ident = PortIdentity(
            kind="physical", stack=1, module=0, port=port,
            name_speed_hint="40gig",
        )
        assert format_port_identity(ident) == f"qsfpplus{port}"


def test_breakout_lane_preserves_dash_suffix():
    """Breakout child ports keep the ``-<lane>`` suffix and apply the
    flat-index spread to the parent port number when the source
    sits on a non-zero module.
    """
    # Baseboard breakout: parent port 1, lane 2 → qsfpplus1-2.
    ident = PortIdentity(
        kind="breakout", stack=1, module=0, port=1,
        breakout_lane=2, name_speed_hint="10gig",
    )
    assert format_port_identity(ident) == "qsfpplus1-2"

    # Module-1 breakout: parent port 1, lane 2 → qsfpplus101-2
    # (flat-index disambiguates the parent).
    ident = PortIdentity(
        kind="breakout", stack=1, module=1, port=1,
        breakout_lane=2, name_speed_hint="10gig",
    )
    assert format_port_identity(ident) == "qsfpplus101-2"


# ---------------------------------------------------------------------------
# 3. Full integration: synthetic c9300 → MikroTik render has no dupes.
# ---------------------------------------------------------------------------


def _build_c9300_intent() -> CanonicalIntent:
    """Return a CanonicalIntent shaped like the user smoke-test
    c9300 source (issue #7) — 41 interfaces across multiple modules
    plus a couple of out-of-stack ports.
    """
    interfaces: list[CanonicalInterface] = []
    # Te1/0/1..24 baseboard 10G.
    for p in range(1, 25):
        interfaces.append(
            CanonicalInterface(name=f"TenGigabitEthernet1/0/{p}")
        )
    # Gi1/1/1..4 module-1 1G.
    for p in range(1, 5):
        interfaces.append(
            CanonicalInterface(name=f"GigabitEthernet1/1/{p}")
        )
    # Te1/1/1..8 module-1 10G uplink.
    for p in range(1, 9):
        interfaces.append(
            CanonicalInterface(name=f"TenGigabitEthernet1/1/{p}")
        )
    # Fo1/1/1..2 module-1 40G.
    for p in range(1, 3):
        interfaces.append(
            CanonicalInterface(name=f"FortyGigabitEthernet1/1/{p}")
        )
    # Twe1/1/1..2 module-1 25G.
    for p in range(1, 3):
        interfaces.append(
            CanonicalInterface(name=f"TwentyFiveGigE1/1/{p}")
        )
    # App1/0/1 (Cisco app-hosting) — falls through; not a 10G port.
    interfaces.append(CanonicalInterface(name="AppGigabitEthernet1/0/1"))
    # Gi0/0 — out-of-stack mgmt-shaped port.
    interfaces.append(CanonicalInterface(name="GigabitEthernet0/0"))
    return CanonicalIntent(interfaces=interfaces)


def test_collision_dedup_in_render_output():
    """End-to-end: feed a synthetic c9300-shaped intent through the
    cross-vendor orchestrator (Cisco source → MikroTik target) and
    render the result.  The rendered RouterOS export must contain
    NO duplicate ``set [ find name=<port> ]`` lines for any port.
    Pre-fix this test would have failed with multiple
    ``set [ find name=sfp-sfpplus1 ]`` rows.
    """
    intent = _build_c9300_intent()
    src = CiscoIOSXECLICodec()
    tgt = MikroTikRouterOSCodec()

    # Run the cross-vendor port-name rewrite (mutates intent in place).
    translate_port_names(intent, src, tgt)

    out = render_intent(intent)

    # Collect every ``set [ find name=<X> ]`` occurrence and check
    # for duplicates.  A duplicate name means two source identities
    # collapsed to one rendered name — exactly the smoke-test bug.
    import re
    found = re.findall(r"set \[ find name=([^\s\]]+)", out)
    duplicates = {n: found.count(n) for n in set(found) if found.count(n) > 1}
    assert not duplicates, (
        f"render emitted duplicate `set [ find name=...]` rows: "
        f"{duplicates}\n\n--- render ---\n{out}"
    )

    # Also verify the canonical interface names themselves are
    # unique post-rename — a different tree-level invariant.
    names = [iface.name for iface in intent.interfaces]
    assert len(set(names)) == len(names), (
        f"duplicate canonical interface names after rename: "
        f"{ {n: names.count(n) for n in names if names.count(n) > 1} }"
    )
