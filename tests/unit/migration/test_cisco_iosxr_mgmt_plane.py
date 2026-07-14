"""Round-trip + matrix coverage for the cisco_iosxr management-plane wire-up
(promotion #13): ``/system/dns-server`` + ``/system/ntp-server`` +
``/system/syslog-server`` (``/system/domain`` was already wired).

XR render-dropped DNS / NTP / syslog until this change.  NTP is a *block*
(``ntp`` / indented ``server <ip> [maxpoll N] [prefer]`` / ``source`` /
``update-calendar``); DNS is ``domain name-server <ip>`` (disjoint from the
``domain name <fqdn>`` line); syslog is the bare ``logging <ip>`` form.  The
one real XR fixture's ntp block is the corpus anchor; dns/syslog are
grammar-grounded but round-trip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "real" / "cisco_iosxr"
_XR = _FIXTURES / "iosxr_design_cst_pa3_xr752.cfg"


class TestXrNtpBlockHarvest:
    def test_parses_ntp_block_from_real_fixture(self) -> None:
        # `ntp` / ` server 198.51.100.118 maxpoll 8 prefer` / ` server 192.0.2.3`
        # / ` source MgmtEth0/RP0/CPU0/0` / ` update-calendar`.
        intent = get_codec("cisco_iosxr").parse(_XR.read_text())
        assert intent.ntp_servers == ["198.51.100.118", "192.0.2.3"]

    def test_ntp_block_skips_non_server_leaves(self) -> None:
        intent = get_codec("cisco_iosxr").parse(
            "ntp\n server 10.0.0.1\n source Loopback0\n update-calendar\n!\n"
        )
        assert intent.ntp_servers == ["10.0.0.1"]

    def test_ntp_server_vrf_infix_keeps_the_address(self) -> None:
        # HEAD-review L1-3: ``server vrf MGMT <ip>`` — the vrf infix precedes
        # the address on IOS-XR; pre-fix ``vrf`` was captured as the server and
        # the real IP lost (ntp_servers == ["vrf"]).
        intent = get_codec("cisco_iosxr").parse(
            "ntp\n server vrf MGMT 10.11.23.7\n"
        )
        assert intent.ntp_servers == ["10.11.23.7"]


class TestXrSyslogHarvest:
    def test_ignores_non_destination_logging(self) -> None:
        # The real fixture carries `logging console debugging` (no IP).
        intent = get_codec("cisco_iosxr").parse(_XR.read_text())
        assert intent.syslog_servers == []

    def test_harvests_bare_logging_ip(self) -> None:
        intent = get_codec("cisco_iosxr").parse(
            "logging 10.9.9.9\nlogging console debugging\nlogging trap warnings\n"
        )
        assert intent.syslog_servers == ["10.9.9.9"]


class TestXrDnsDisjointFromDomain:
    def test_name_server_and_domain_dont_shadow(self) -> None:
        codec = get_codec("cisco_iosxr")
        intent = codec.parse(
            "domain name example.com\ndomain name-server 8.8.8.8\n"
            "domain name-server 1.1.1.1\n"
        )
        assert intent.domain == "example.com"
        assert intent.dns_servers == ["8.8.8.8", "1.1.1.1"]


class TestXrManagementPlaneRoundTrip:
    _SRC = (
        "hostname r1\ndomain name lab.local\ndomain name-server 8.8.8.8\n"
        "ntp\n server 10.0.0.1\n server 10.0.0.2\n source Loopback0\n!\n"
        "logging 10.9.9.9\n"
    )

    def test_render_emits_xr_forms(self) -> None:
        codec = get_codec("cisco_iosxr")
        rendered = codec.render(codec.parse(self._SRC))
        assert "domain name-server 8.8.8.8" in rendered
        assert "ntp" in rendered and " server 10.0.0.1" in rendered
        assert "logging 10.9.9.9" in rendered

    def test_round_trip_stable(self) -> None:
        codec = get_codec("cisco_iosxr")
        intent = codec.parse(self._SRC)
        reparsed = codec.parse(codec.render(intent))
        assert reparsed.dns_servers == ["8.8.8.8"]
        assert reparsed.ntp_servers == ["10.0.0.1", "10.0.0.2"]
        assert reparsed.syslog_servers == ["10.9.9.9"]
        assert reparsed.domain == "lab.local"

    def test_no_mgmt_config_renders_nothing(self) -> None:
        codec = get_codec("cisco_iosxr")
        rendered = codec.render(codec.parse("hostname bare\n"))
        assert "domain name-server" not in rendered
        assert "\nntp\n" not in rendered and "logging" not in rendered

    @pytest.mark.parametrize("path", [
        "/system/dns-server", "/system/ntp-server", "/system/syslog-server",
    ])
    def test_classify_supported(self, path: str) -> None:
        caps = get_codec("cisco_iosxr").capabilities
        assert caps.classify(path) == "supported"
        assert path not in {u.path for u in caps.unsupported}
