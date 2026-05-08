"""
Unit tests for ``netcanon.services.migration_detect`` and the
per-codec :meth:`CodecBase.probe` overrides (R5 auto-detection).
"""

from __future__ import annotations

import pytest

import netcanon.migration  # noqa: F401 — side-effect: register codecs

from netcanon.migration.codecs._mock import MockCodec
from netcanon.migration.codecs.base import CodecBase
from netcanon.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.opnsense import OPNsenseCodec
from netcanon.services.migration_detect import (
    DetectCandidate,
    best_codec,
    detect_codec,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CodecBase default
# ---------------------------------------------------------------------------


class TestBaseProbe:
    def test_default_probe_returns_none(self):
        """A codec that doesn't override probe() is silent."""
        class Silent(CodecBase):
            name = "silent-test"
            @property
            def capabilities(self): return None  # noqa: ANN201
            def parse(self, raw): return raw
            def render(self, tree): return ""
        assert Silent.probe("anything") is None


# ---------------------------------------------------------------------------
# Per-codec probe signatures
# ---------------------------------------------------------------------------


class TestOPNsenseProbe:
    def test_matches_opnsense_root(self):
        raw = '<?xml version="1.0"?>\n<opnsense>\n  <system></system>\n</opnsense>\n'
        hit = OPNsenseCodec.probe(raw)
        assert hit is not None
        confidence, reason = hit
        assert confidence >= 95
        assert "opnsense" in reason.lower()

    def test_matches_opnsense_with_attrs(self):
        raw = '<opnsense xmlns:opn="opnsense">\n</opnsense>'
        hit = OPNsenseCodec.probe(raw)
        assert hit is not None

    def test_ignores_netconf_xml(self):
        raw = '<?xml version="1.0"?><rpc-reply><data><interfaces/></data></rpc-reply>'
        assert OPNsenseCodec.probe(raw) is None

    def test_ignores_plain_text(self):
        assert OPNsenseCodec.probe("hostname router1\n") is None


class TestCiscoNETCONFProbe:
    def test_matches_openconfig_namespace(self):
        raw = '<?xml version="1.0"?>\n<interfaces xmlns="http://openconfig.net/yang/interfaces">'
        hit = CiscoIOSXECodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 90

    def test_matches_rpc_reply(self):
        raw = '<rpc-reply><data></data></rpc-reply>'
        hit = CiscoIOSXECodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 50

    def test_ignores_opnsense(self):
        raw = '<opnsense><system/></opnsense>'
        # No openconfig namespace, no rpc-reply — no match.
        assert CiscoIOSXECodec.probe(raw) is None

    def test_ignores_ios_cli(self):
        raw = "!\nhostname r1\n!\n"
        assert CiscoIOSXECodec.probe(raw) is None


class TestCiscoCLIProbe:
    def test_matches_show_running_config_banner(self):
        raw = "Building configuration...\n\nCurrent configuration : 1234 bytes\n!\nhostname r1\n"
        hit = CiscoIOSXECLICodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 95

    def test_matches_interface_giga_and_ip_address(self):
        raw = (
            "!\n"
            "interface GigabitEthernet0/0/0\n"
            " description WAN\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            " no shutdown\n"
            "!\n"
        )
        hit = CiscoIOSXECLICodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 85

    def test_matches_switchport(self):
        raw = (
            "interface GigabitEthernet1/0/1\n"
            " switchport mode access\n"
            " switchport access vlan 10\n"
            "!\n"
        )
        hit = CiscoIOSXECLICodec.probe(raw)
        assert hit is not None

    def test_hostname_alone_is_weak(self):
        raw = "hostname r1\n!\n"
        hit = CiscoIOSXECLICodec.probe(raw)
        assert hit is not None
        # Should rank LOW since the signature is ambiguous.
        assert hit[0] < 60

    def test_ignores_xml(self):
        assert CiscoIOSXECLICodec.probe("<?xml version='1.0'?>") is None

    def test_ignores_json(self):
        assert CiscoIOSXECLICodec.probe('{"foo": "bar"}') is None


class TestMikroTikProbe:
    def test_matches_routeros_banner(self):
        raw = (
            "# jan/15/2024 10:00:00 by RouterOS 7.13.5\n"
            "# software id = ABCD-EFGH\n"
            "/system identity\n"
            "set name=r1\n"
        )
        hit = MikroTikRouterOSCodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 95

    def test_matches_section_headers(self):
        raw = "/system identity\nset name=r1\n/ip address\n"
        hit = MikroTikRouterOSCodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 85

    def test_matches_find_default_name_idiom(self):
        raw = '/interface ethernet\nset [ find default-name=ether1 ] disabled=no\n'
        hit = MikroTikRouterOSCodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 85

    def test_ignores_xml(self):
        assert MikroTikRouterOSCodec.probe("<opnsense/>") is None


class TestMockProbe:
    def test_matches_valid_json(self):
        raw = '{"/interfaces/eth0/ip": "10.0.0.1"}'
        hit = MockCodec.probe(raw)
        assert hit is not None
        assert 40 <= hit[0] <= 70

    def test_weak_match_on_bad_json_shape(self):
        raw = '{malformed json'
        hit = MockCodec.probe(raw)
        assert hit is not None
        assert hit[0] < 55   # lower than valid JSON

    def test_ignores_xml(self):
        assert MockCodec.probe("<data/>") is None

    def test_ignores_cli(self):
        assert MockCodec.probe("interface Gi0/0/0\n") is None


# ---------------------------------------------------------------------------
# Detection service
# ---------------------------------------------------------------------------


class TestDetectCodec:
    def test_empty_input_returns_empty_list(self):
        assert detect_codec("") == []

    def test_random_text_returns_empty_list(self):
        assert detect_codec("This is just a README.md") == []

    def test_opnsense_detects_uniquely(self):
        raw = "<opnsense><system/></opnsense>"
        results = detect_codec(raw)
        assert len(results) == 1
        assert results[0].codec == "opnsense"
        assert results[0].confidence >= 95

    def test_mikrotik_detects_uniquely(self):
        raw = "# ... by RouterOS 7.13\n/system identity\nset name=r1\n"
        results = detect_codec(raw)
        names = [c.codec for c in results]
        assert "mikrotik_routeros" in names
        assert results[0].codec == "mikrotik_routeros"

    def test_ios_cli_beats_any_other_codec(self):
        raw = (
            "!\ninterface GigabitEthernet0/0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n no shutdown\n!\n"
        )
        results = detect_codec(raw)
        assert results[0].codec == "cisco_iosxe_cli"
        assert results[0].confidence >= 85

    def test_aruba_running_config_with_command_echo_does_not_match_cisco(self):
        """Regression for the user-reported bug where pasting an Aruba
        ``show running-config`` whose head carried the Aruba prompt
        + command echo (``Aruba-Stack-2930M# show running-config``)
        fired Cisco's probe at 95% because the literal string
        ``show running-config`` appeared.  ``show running-config`` is
        a COMMAND operators run on multiple vendors, not a Cisco-
        specific banner.  Aruba's banner (``; hpStack_WC Configuration
        Editor``) MUST win because it's unambiguously Aruba."""
        raw = (
            "Aruba-Stack-2930M# show running-config\n"
            "\n"
            "Running configuration:\n"
            "\n"
            "; hpStack_WC Configuration Editor; "
            "Created on release #WC.16.11.0025\n"
            "; Ver #14:67.6f.f8.1d.9b.3f.bf.bb.ef.7c.59.fc:44\n"
            "\n"
            "stacking\n"
            '   member 1 type "JL323A" mac-address 040973-b4f2c0\n'
        )
        results = detect_codec(raw)
        assert results[0].codec == "aruba_aoss", (
            f"expected aruba_aoss to win; got {results[0]!r}"
        )
        assert results[0].confidence >= 95
        # Cisco MAY still appear as a low-confidence runner-up (the
        # ``show running-config`` echo + ``hostname`` shape can both
        # weakly match Cisco's probe), but it MUST NOT outrank Aruba.
        cisco = next(
            (c for c in results if c.codec == "cisco_iosxe_cli"), None,
        )
        if cisco is not None:
            assert cisco.confidence < results[0].confidence

    def test_aruba_jl_part_number_banner_detected(self):
        """Newer Aruba part numbers use a ``JL`` letter prefix
        (JL256A 2930F, JL323A 2930M, JL260A) rather than the older
        all-digit ``J9850A`` form.  The probe regex must accept both.
        Coverage gap discovered when fixing the user-reported
        misdetection bug."""
        raw = (
            '; JL260A Configuration Editor; '
            'Created on release #WC.16.07.0002\n'
            'hostname "fw-01"\n'
            'vlan 10\n   name "USERS"\n   exit\n'
        )
        results = detect_codec(raw)
        assert results[0].codec == "aruba_aoss"
        assert results[0].confidence >= 95

    def test_aruba_hpstack_banner_detected(self):
        """Stacked Aruba switches emit ``; hpStack_<branch>
        Configuration Editor`` instead of the per-chassis part number.
        The probe regex must accept this form too."""
        raw = (
            '; hpStack_WC Configuration Editor; '
            'Created on release #WC.16.11.0025\n'
            'hostname "stack-01"\n'
            'stacking\n   member 1 type "JL323A"\n'
        )
        results = detect_codec(raw)
        assert results[0].codec == "aruba_aoss"
        assert results[0].confidence >= 95

    def test_cisco_banner_pair_wins_over_show_running_phrase(self):
        """When the input carries the ``Building configuration...`` +
        ``Current configuration : N bytes`` Cisco-specific banner
        pair, it MUST resolve to Cisco IOS-XE — these two strings
        together are unambiguous Cisco output and are NOT emitted by
        any other vendor."""
        raw = (
            "Building configuration...\n"
            "\n"
            "Current configuration : 5545 bytes\n"
            "!\n"
            "! Last configuration change at 10:59:41 UTC Fri\n"
            "!\n"
            "version 16.9\n"
            "service timestamps debug datetime msec\n"
            "hostname r1\n"
            "!\n"
        )
        results = detect_codec(raw)
        assert results[0].codec == "cisco_iosxe_cli"
        assert results[0].confidence >= 95

    def test_show_running_phrase_alone_does_not_max_cisco_score(self):
        """The bare phrase ``show running-config`` without any other
        Cisco-specific marker must NOT produce 95+ confidence — that
        was the loose match that caused the user-reported false
        positive on Aruba inputs.  Either the probe returns None, or
        it returns a score below 95."""
        raw = (
            "Some-Device# show running-config\n"
            "\n"
            "Some random output that isn't a real config.\n"
        )
        results = detect_codec(raw)
        # Either no match (preferred — phrase alone is not diagnostic)
        # or a low-confidence match below the 95 threshold.
        cisco = next(
            (c for c in results if c.codec == "cisco_iosxe_cli"), None,
        )
        if cisco is not None:
            assert cisco.confidence < 95, (
                f"bare 'show running-config' phrase should not produce "
                f"95+ confidence on Cisco probe — got {cisco.confidence}"
            )

    def test_netconf_xml_beats_opnsense_when_namespace_present(self):
        """The openconfig namespace is a unique NETCONF signature; the
        OPNsense codec should NOT claim this input."""
        raw = (
            '<?xml version="1.0"?>\n'
            '<interfaces xmlns="http://openconfig.net/yang/interfaces">\n'
            '  <interface><name>Gi0/0</name></interface>\n'
            '</interfaces>\n'
        )
        results = detect_codec(raw)
        assert results[0].codec == "cisco_iosxe"
        codec_names = [c.codec for c in results]
        assert "opnsense" not in codec_names

    def test_candidates_are_sorted_by_confidence(self):
        """When multiple codecs match, highest score comes first."""
        # A bare '!' + 'hostname' matches cisco_iosxe_cli at low
        # confidence AND might not match anything else.  Just verify
        # whatever returns is sorted descending.
        raw = "hostname r1\n!\ninterface Loopback0\n ip address 1.1.1.1 255.255.255.255\n!\n"
        results = detect_codec(raw)
        confidences = [c.confidence for c in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_min_confidence_filters_weak_matches(self):
        """Setting min_confidence=80 should drop 'hostname r1!' -style weak matches."""
        raw = "hostname r1\n!\n"
        weak = detect_codec(raw, min_confidence=1)
        strong = detect_codec(raw, min_confidence=80)
        # weak has an entry (45% confidence), strong is empty.
        assert len(weak) >= 1
        assert all(c.confidence >= 80 for c in strong)

    def test_probe_bytes_truncation(self):
        """Only the first N bytes should be probed."""
        # Put a matching OPNsense signature way past 500 bytes.
        padding = "x" * 1000
        raw = padding + "\n<opnsense>\n<system/>\n</opnsense>\n"
        # default: miss (signature past the probe cutoff).
        assert detect_codec(raw) == []
        # explicit larger probe_bytes: match.
        results = detect_codec(raw, probe_bytes=2000)
        assert len(results) == 1
        assert results[0].codec == "opnsense"

    def test_returns_detect_candidate_instances(self):
        raw = "<opnsense/>"
        results = detect_codec(raw)
        assert all(isinstance(c, DetectCandidate) for c in results)


class TestBestCodec:
    def test_best_returns_top(self):
        raw = "<opnsense><system/></opnsense>"
        top = best_codec(raw)
        assert top is not None
        assert top.codec == "opnsense"

    def test_best_returns_none_for_empty(self):
        assert best_codec("") is None

    def test_best_min_confidence_default_is_strict(self):
        """best_codec() defaults to min_confidence=50; weak matches → None."""
        # 'hostname r1!' scores ~45 for CLI codec — below default strict threshold.
        raw = "hostname r1\n!\n"
        assert best_codec(raw) is None
        # But explicit min_confidence=1 gets it.
        top = best_codec(raw, min_confidence=1)
        assert top is not None
        assert top.codec == "cisco_iosxe_cli"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestProbeRobustness:
    def test_broken_codec_does_not_break_detection(self, monkeypatch):
        """If one codec's probe raises, detection still returns
        results from the others."""
        def bad_probe(cls, raw_prefix):
            raise RuntimeError("simulated bug in probe")
        monkeypatch.setattr(
            MockCodec, "probe", classmethod(bad_probe)
        )
        # OPNsense should still detect cleanly.
        raw = "<opnsense><system/></opnsense>"
        results = detect_codec(raw)
        assert any(c.codec == "opnsense" for c in results)
        assert all(c.codec != "mock" for c in results)
