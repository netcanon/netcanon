"""
OPNsense: kind=mgmt cascade from cisco_iosxe_cli Mgmt-vrf source.

Closes the cross-vendor cascade gap identified in commit ``56a4cde``
(Wave 2): the cisco_iosxe_cli parser promotes ``GigabitEthernet0/0``
bound to ``Mgmt-vrf`` to ``CanonicalInterface.kind="mgmt"``, but the
OPNsense render previously dropped the override (formatter returned
``None`` for kind=mgmt, the rename mesh stripped the port from the
canonical tree, and the management IP was silently lost).

OPNsense has no native VRF / dedicated OOBM-port concept.  Best-effort
cross-vendor mapping is a dedicated ``opt_mgmt`` zone with a
``<descr>Management</descr>`` element so the OPNsense GUI labels the
zone clearly — see docs.opnsense.org/manual/interfaces.html
("Optional interfaces are commonly named opt1, opt2, ...").

Mirrors ``test_mgmt_vrf_cascades_to_aruba_oobm`` from
tests/unit/migration/codecs/cisco_iosxe_cli/test_mgmt_vrf_kind_promotion.py.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
)
from netconfig.migration.canonical.port_names import (
    PortIdentity,
    translate_port_names,
)
from netconfig.migration.codecs.cisco_iosxe_cli.codec import (
    CiscoIOSXECLICodec,
)
from netconfig.migration.codecs.opnsense import OPNsenseCodec
from netconfig.migration.codecs.opnsense.port_names import (
    format_port_identity,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Identity-level: kind=mgmt → "opt_mgmt"
# ---------------------------------------------------------------------------


def test_kind_mgmt_renders_as_opt_mgmt_zone() -> None:
    """A bare ``kind="mgmt"`` :class:`PortIdentity` formats to
    ``opt_mgmt`` — OPNsense's optional-zone naming convention.  The
    ``opt_*`` prefix is preserved verbatim by the renderer's
    ``_zone_tag_for`` helper (which special-cases names starting with
    ``opt``)."""
    ident = PortIdentity(kind="mgmt", original="GigabitEthernet0/0")
    assert format_port_identity(ident) == "opt_mgmt"


def test_kind_mgmt_renders_with_zone_marker() -> None:
    """A canonical interface with ``kind="mgmt"`` produces an
    ``<opt_mgmt>`` zone with a ``<descr>Management</descr>`` marker
    — the operator-visible zone label in the OPNsense GUI.  When the
    canonical interface carries its own description, that wins (no
    Management override)."""
    tree = CanonicalIntent(
        hostname="opn1",
        interfaces=[
            CanonicalInterface(
                name="opt_mgmt",
                kind="mgmt",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.10.10.252", prefix_length=24,
                    ),
                ],
                enabled=True,
            ),
        ],
    )
    out = OPNsenseCodec().render(tree)
    assert "<opt_mgmt>" in out
    assert "<descr>Management</descr>" in out
    assert "<ipaddr>10.10.10.252</ipaddr>" in out
    assert "<subnet>24</subnet>" in out


def test_kind_mgmt_with_description_does_not_clobber() -> None:
    """When the canonical interface carries an explicit description
    (e.g. the operator labelled it ``out-of-band-mgmt`` upstream),
    that description wins — the Management default only fires for
    bare cross-vendor mgmt ports without a human-readable label."""
    tree = CanonicalIntent(
        hostname="opn1",
        interfaces=[
            CanonicalInterface(
                name="opt_mgmt",
                kind="mgmt",
                description="out-of-band-mgmt",
                enabled=True,
            ),
        ],
    )
    out = OPNsenseCodec().render(tree)
    assert "<descr>out-of-band-mgmt</descr>" in out
    assert "<descr>Management</descr>" not in out


# ---------------------------------------------------------------------------
# Full pipeline cascade: cisco Mgmt-vrf → opnsense mgmt zone
# ---------------------------------------------------------------------------


def test_cisco_mgmt_vrf_cascades_to_opnsense_mgmt() -> None:
    """End-to-end cascade — Cisco IOS-XE source with
    ``vrf forwarding Mgmt-vrf`` on ``GigabitEthernet0/0`` translates
    to an OPNsense output containing the ``<opt_mgmt>`` zone with the
    Management descr and the IP preserved.  Mirrors the Aruba
    ``oobm`` cascade test in
    tests/unit/migration/codecs/cisco_iosxe_cli/test_mgmt_vrf_kind_promotion.py.

    Without the kind=mgmt branch in opnsense's port_names, the cisco
    source would have its name dropped by the rename mesh's
    auto-strip pass (``format_port_identity`` returned None) — the
    operator's intended out-of-band management address would
    disappear from the rendered config entirely.
    """
    cfg = (
        "hostname r1\n"
        "interface GigabitEthernet0/0\n"
        " vrf forwarding Mgmt-vrf\n"
        " ip address 10.10.10.252 255.255.255.0\n"
        "!\n"
    )
    cisco_codec = CiscoIOSXECLICodec()
    opn_codec = OPNsenseCodec()
    intent = cisco_codec.parse(cfg)

    # Sanity: parser set the kind override.
    gi = next(
        i for i in intent.interfaces if i.name == "GigabitEthernet0/0"
    )
    assert gi.kind == "mgmt"

    # Translate port names cisco → opnsense.  The override threads
    # through to format_port_identity and produces "opt_mgmt".
    result = translate_port_names(intent, cisco_codec, opn_codec)
    assert result.applied.get("GigabitEthernet0/0") == "opt_mgmt"

    # Render and confirm the mgmt zone emits with the descr marker
    # and the IP attached.
    out = opn_codec.render(intent)
    assert "<opt_mgmt>" in out, (
        "OPNsense render should emit the dedicated opt_mgmt zone "
        "when the source's mgmt-vrf-bound port cascades to kind=mgmt"
    )
    assert "<descr>Management</descr>" in out
    assert "<ipaddr>10.10.10.252</ipaddr>" in out
    assert "<subnet>24</subnet>" in out
