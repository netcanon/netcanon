"""Port names no device has — emitted by the formatters, found 2026-10-07.

Both were surfaced by the stacking / model research run
(``docs/reviews/2026-10-07-stacking-and-models/``) and reproduced on the main
thread before being fixed.

Scope note.  The same run found a wider family — ``x or default`` in ten
formatters conflating "absent" with "zero" (``ge-0/0/0`` and ``ge-0/0/1``
both becoming AOS-S ``0/1``; ``ae0`` and ``ae1`` both becoming ``Trk1``).
Those are deliberately NOT changed here.  They produce a *collision*, which
the rename orchestrator now reports, and three existing tests pin the
behaviour on purpose (it keeps OPNsense ``igb0`` from being dropped).  The
correct fix is positional mapping between declared source and target models,
not a second heuristic; see ``99a-implementation-plan.md`` in that run dir.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.port_names import PortIdentity
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


class TestJunos25GPrefix:
    """``xle`` is 40GbE under the QFabric package only; 25G is ``et-``."""

    @pytest.mark.parametrize(
        ("source", "name"),
        [
            ("cisco_iosxe_cli", "TwentyFiveGigE1/0/5"),
            ("cisco_iosxr", "TwentyFiveGigE0/0/0/5"),
        ],
    )
    def test_a_25g_port_is_not_emitted_as_xle(
        self, source: str, name: str,
    ) -> None:
        ident = get_codec(source).classify_port_name(name)
        assert ident.name_speed_hint == "25gig", (
            "probe no longer yields a 25G identity — pick another name"
        )
        out = get_codec("juniper_junos").format_port_identity(ident)
        assert out is not None
        assert out.startswith("et-"), f"{name} -> {out}"

    def test_xle_reads_as_40g(self) -> None:
        ident = get_codec("juniper_junos").classify_port_name("xle-0/0/3")
        assert ident.name_speed_hint == "40gig"

    @pytest.mark.parametrize(
        "name",
        ["xle-0/0/3", "ge-0/0/1", "mge-0/0/4", "xe-1/2/0", "et-0/0/48"],
    )
    def test_a_junos_name_is_never_renamed_on_its_way_back_to_junos(
        self, name: str,
    ) -> None:
        """The speed hint is lossy — 25G, 40G and 100G all share ``et``, and
        ``xle`` is an alternate spelling of 40G — so the literal prefix is
        carried for the same-vendor round-trip instead of re-derived."""
        codec = get_codec("juniper_junos")
        assert codec.format_port_identity(codec.classify_port_name(name)) == name


class TestRouterOSIndexIsNeverNegative:
    """A 0-based source has ``stack == 0``; ``stack - 1`` went negative and
    ``xe-0/2/0`` rendered as ``sfp-sfpplus-800``."""

    def test_the_reported_case(self) -> None:
        ident = get_codec("juniper_junos").classify_port_name("xe-0/2/0")
        out = get_codec("mikrotik_routeros").format_port_identity(ident)
        assert out == "sfp-sfpplus200"

    @pytest.mark.parametrize("stack", [None, 0, 1, 2, 9])
    @pytest.mark.parametrize("module", [None, 0, 1, 2])
    @pytest.mark.parametrize("port", [0, 1, 24])
    def test_no_identity_yields_a_negative_index(
        self, stack, module, port,
    ) -> None:
        from netcanon.migration.codecs.mikrotik_routeros.port_names import (
            _flat_port_index,
        )

        ident = PortIdentity(
            kind="physical", stack=stack, module=module, port=port,
        )
        assert _flat_port_index(ident) >= 0
