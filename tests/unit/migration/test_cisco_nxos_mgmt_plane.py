"""Round-trip + matrix coverage for the cisco_nxos management-plane wire-up
(promotion #4): ``/system/domain`` + ``/system/dns-server`` +
``/system/ntp-server`` + ``/system/syslog-server``.

NX-OS render-dropped all four until this change.  Grammar is attested in the
codec's own real fixtures: ``ip domain-name``, ``ntp server <ip> [prefer]
[use-vrf <name>]``, ``logging server <ip> <sev> [port N]``.  DNS
(``ip name-server``) is grammar-grounded (no corpus line) but round-trips.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "real" / "cisco_nxos"
_NAUTOBOT = _FIXTURES / "nautobot_gc_nxos_snmp_spine01_nxos933.txt"


class TestNxosManagementPlaneHarvest:
    def test_parses_domain_ntp_syslog_from_real_fixture(self) -> None:
        intent = get_codec("cisco_nxos").parse(_NAUTOBOT.read_text())
        assert intent.domain == "infra.ntc.com"
        # `ntp server 10.1.1.1 use-vrf default` + `... 10.2.2.2 prefer use-vrf`.
        assert intent.ntp_servers == ["10.1.1.1", "10.2.2.2"]
        # `logging server 10.125.1.171 6 port 7008` — first IP token only.
        assert intent.syslog_servers == ["10.125.1.171"]

    def test_syslog_ignores_non_destination_logging(self) -> None:
        # `logging console`/`logging monitor`/`logging level` carry no IP.
        intent = get_codec("cisco_nxos").parse(
            "hostname h\nlogging console 5\nlogging monitor 6\n"
            "logging server 10.9.9.9 6\n"
        )
        assert intent.syslog_servers == ["10.9.9.9"]

    def test_render_emits_nxos_forms(self) -> None:
        codec = get_codec("cisco_nxos")
        intent = codec.parse(_NAUTOBOT.read_text())
        rendered = codec.render(intent)
        assert "ip domain-name infra.ntc.com" in rendered
        assert "ntp server 10.1.1.1" in rendered
        assert "logging server 10.125.1.171" in rendered

    def test_same_vendor_round_trip_stable(self) -> None:
        codec = get_codec("cisco_nxos")
        intent = codec.parse(_NAUTOBOT.read_text())
        reparsed = codec.parse(codec.render(intent))
        assert reparsed.domain == intent.domain
        assert reparsed.ntp_servers == intent.ntp_servers
        assert reparsed.syslog_servers == intent.syslog_servers

    def test_dns_round_trips_grammar_grounded(self) -> None:
        # No `ip name-server` in the corpus, but the wire-up round-trips it.
        codec = get_codec("cisco_nxos")
        intent = codec.parse("hostname h\nip name-server 8.8.8.8 1.1.1.1\n")
        assert intent.dns_servers == ["8.8.8.8", "1.1.1.1"]
        assert codec.parse(codec.render(intent)).dns_servers == ["8.8.8.8", "1.1.1.1"]

    def test_name_server_use_vrf_tail_not_harvested(self) -> None:
        # HEAD-review L1-2: ``ip name-server <ip> use-vrf <name>`` — the
        # trailing ``use-vrf management`` modifier must NOT be minted as fake
        # resolvers (pre-fix: dns_servers == ["10.0.80.10", "use-vrf",
        # "management"]).  IP-guard drops the non-address tokens.
        codec = get_codec("cisco_nxos")
        intent = codec.parse("ip name-server 10.0.80.10 use-vrf management\n")
        assert intent.dns_servers == ["10.0.80.10"]

    def test_no_mgmt_config_renders_nothing(self) -> None:
        codec = get_codec("cisco_nxos")
        intent = codec.parse("hostname bare\n")
        assert intent.ntp_servers == [] and intent.syslog_servers == []
        assert intent.dns_servers == [] and intent.domain == ""
        rendered = codec.render(intent)
        assert "ntp server" not in rendered and "logging server" not in rendered

    @pytest.mark.parametrize("path", [
        "/system/domain", "/system/dns-server",
        "/system/ntp-server", "/system/syslog-server",
    ])
    def test_classify_supported(self, path: str) -> None:
        caps = get_codec("cisco_nxos").capabilities
        assert caps.classify(path) == "supported"
        assert path not in {u.path for u in caps.unsupported}
