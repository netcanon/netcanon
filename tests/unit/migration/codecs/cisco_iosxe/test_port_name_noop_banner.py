"""Port-name translation for CiscoIOSXECodec (NETCONF / OpenConfig).

History
-------
R-21 originally declared ``"ports"`` in this codec's
``unsupported_rename_categories`` so that migrating TO it surfaced ONE
amber pane-compat banner instead of N per-port "no native
representation" warning rows.  That was framed as a cosmetic UI hint.

It was sitting on top of total interface loss.  ``classify_port_name``
and ``format_port_identity`` were inherited ``CodecBase`` no-ops
(kind="unknown" / ``None``), and because ``strip_unmappable`` defaults
to True, "no native representation" means the name is DELETED rather
than left verbatim — despite the base docstring claiming the latter.
Every foreign port name was therefore dropped on the way in: measured at
96% of 441 interfaces across five source codecs, with arista_eos,
cisco_nxos and aruba_aoscx each losing 100%, producing a ~60-byte render
carrying zero interfaces while the job still reported ``completed``.
This codec is offered in the operator target dropdown.

#482 closed it the way that comment invited ("Remove when the stub grows
real port-name translation"): IOS-XE NETCONF and IOS-XE CLI are the same
platform in two wire formats, so both methods now delegate to the CLI
sibling's shared port-name bridge, and ``"ports"`` is gone from
``unsupported_rename_categories``.

``"snmpv3"`` remains declared — that gap is real and unrelated.

See ``docs/reviews/2026-09-22-api-full-mesh/`` (defect D1).
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.port_names import (
    PortIdentity,
    translate_port_names,
)
from netcanon.migration.codecs.cisco_iosxe.codec import CiscoIOSXECodec
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


class TestCiscoIOSXEUnsupportedRenameCategories:
    def test_ports_no_longer_declared_unsupported(self):
        """#482: ports translate for real now, so the banner must be gone.

        If this fails because someone re-added ``"ports"``, check whether
        the port-name delegation below was removed with it — the two are
        a pair, and re-declaring the banner without restoring real
        translation reinstates silent interface deletion.
        """
        codec = CiscoIOSXECodec()
        assert "ports" not in codec.unsupported_rename_categories

    def test_snmpv3_still_declared_unsupported(self):
        """Regression: 'snmpv3' must remain — that gap is genuine."""
        codec = CiscoIOSXECodec()
        assert "snmpv3" in codec.unsupported_rename_categories


class TestCiscoIOSXEPortNameBridge:
    def test_classify_port_name_resolves_a_real_identity(self):
        codec = CiscoIOSXECodec()
        ident = codec.classify_port_name("GigabitEthernet1/0/1")
        assert ident.kind == "physical"
        assert ident.original == "GigabitEthernet1/0/1"

    def test_format_port_identity_returns_a_cisco_name(self):
        codec = CiscoIOSXECodec()
        ident = PortIdentity(kind="physical", port=1, original="Gi1/0/1")
        assert codec.format_port_identity(ident) is not None

    def test_agrees_with_the_cli_sibling(self):
        """The two wire formats must never disagree about what a Cisco
        port name looks like — that is why the bridge is shared rather
        than reimplemented."""
        netconf = get_codec("cisco_iosxe")
        cli = get_codec("cisco_iosxe_cli")
        for name in (
            "GigabitEthernet1/0/1",
            "TenGigabitEthernet0/0/2",
            "Loopback0",
            "Port-channel10",
            "Vlan200",
        ):
            assert (
                netconf.classify_port_name(name).kind
                == cli.classify_port_name(name).kind
            ), name
            ident = netconf.classify_port_name(name)
            assert netconf.format_port_identity(
                ident
            ) == cli.format_port_identity(ident), name


class TestForeignPortsSurviveTranslation:
    """The actual defect: interfaces must not vanish en route."""

    @pytest.mark.parametrize(
        "source_name",
        ["arista_eos", "cisco_nxos", "aruba_aoscx", "juniper_junos"],
    )
    def test_physical_ports_are_not_deleted(self, source_name: str) -> None:
        source = get_codec(source_name)
        target = get_codec("cisco_iosxe")

        intent = source.parse(_MINIMAL_SOURCES[source_name])
        assert intent.interfaces, (
            f"{source_name} fixture parsed to zero interfaces — this test "
            "would pass vacuously"
        )
        before = len(intent.interfaces)

        translate_port_names(intent, source, target, rename_map={})

        assert len(intent.interfaces) == before, (
            f"{source_name} -> cisco_iosxe deleted "
            f"{before - len(intent.interfaces)} of {before} interfaces"
        )
        for iface in intent.interfaces:
            assert iface.name, "an interface survived with an empty name"


# Minimal single-physical-port configs, one per source grammar.  Kept
# inline and tiny so the assertion above is about port-name survival and
# nothing else.
_MINIMAL_SOURCES = {
    "arista_eos": (
        "hostname leaf1\n"
        "!\n"
        "interface Ethernet1\n"
        "   description uplink\n"
        "!\n"
    ),
    "cisco_nxos": (
        "hostname leaf1\n"
        "\n"
        "interface Ethernet1/1\n"
        "  description uplink\n"
        "\n"
    ),
    "aruba_aoscx": (
        "hostname leaf1\n"
        "!\n"
        "interface 1/1/1\n"
        "    description uplink\n"
        "!\n"
    ),
    "juniper_junos": (
        "interfaces {\n"
        "    ge-0/0/0 {\n"
        "        description uplink;\n"
        "    }\n"
        "}\n"
    ),
}
