"""Round-trip + honesty coverage for the ``/system/syslog-server`` harvest
(promotions #1 cisco_iosxe_cli, #11 arista_eos).

The three codecs that genuinely wire syslog — ``juniper_junos``
(``set system syslog host <ip>``), ``cisco_iosxe_cli`` and ``arista_eos``
(``logging host <ip>``) — must:

* harvest the destination host out of the vendor ``logging`` grammar,
  IGNORING the large family of non-destination ``logging`` sub-commands
  (buffer sizes, severities, message ids, UDP ports …) via an IP-literal
  guard;
* round-trip that host back on render (same-vendor stability);
* classify ``/system/syslog-server`` as ``supported`` (explicit list).

The adversarial ``batfish_cisco_logging.txt`` fixture is the minefield: a
``logging <everything>`` dump where the true destinations are buried among
dozens of look-alike sub-commands.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "real"
_BATFISH = _FIXTURES / "cisco_iosxe" / "batfish_cisco_logging.txt"
_KSATOR = _FIXTURES / "arista_eos" / "ksator_dcs_7150s64_eos4224.txt"

# The six distinct true destinations in the batfish minefield, first-seen order.
_BATFISH_HOSTS = [
    "1.2.3.4", "dead:beef::1", "10.246.131.130",
    "10.246.131.138", "1.1.1.1", "11.2.3.4",
]
# Non-destination numeric arguments that MUST NOT be harvested as "servers".
_BATFISH_NOISE = {
    "5000", "5", "100000", "512", "6", "3", "0", "100", "9", "10", "25",
    "1222444", "1233334", "1111234", "32000", "12345", "514", "50000",
}


class TestIosxeCliSyslogHarvest:
    def test_harvests_only_true_hosts_from_minefield(self) -> None:
        codec = get_codec("cisco_iosxe_cli")
        got = codec.parse(_BATFISH.read_text()).syslog_servers
        assert got == _BATFISH_HOSTS

    def test_no_noise_token_leaks(self) -> None:
        codec = get_codec("cisco_iosxe_cli")
        got = set(codec.parse(_BATFISH.read_text()).syslog_servers)
        assert not (_BATFISH_NOISE & got)

    def test_same_vendor_round_trip_is_stable(self) -> None:
        codec = get_codec("cisco_iosxe_cli")
        intent = codec.parse(_BATFISH.read_text())
        reparsed = codec.parse(codec.render(intent))
        assert reparsed.syslog_servers == _BATFISH_HOSTS

    def test_render_emits_logging_host(self) -> None:
        codec = get_codec("cisco_iosxe_cli")
        rendered = codec.render(codec.parse("logging host 10.9.9.9\n"))
        assert "logging host 10.9.9.9" in rendered

    def test_classify_supported(self) -> None:
        caps = get_codec("cisco_iosxe_cli").capabilities
        assert caps.classify("/system/syslog-server") == "supported"
        assert "/system/syslog-server" in set(caps.supported)


class TestAristaSyslogHarvest:
    def test_harvests_host_from_ksator(self) -> None:
        codec = get_codec("arista_eos")
        got = codec.parse(_KSATOR.read_text()).syslog_servers
        assert got == ["10.83.28.52"]

    def test_render_emits_logging_host(self) -> None:
        codec = get_codec("arista_eos")
        rendered = codec.render(codec.parse("logging host 10.83.28.52\n"))
        assert "logging host 10.83.28.52" in rendered

    def test_same_vendor_round_trip_is_stable(self) -> None:
        codec = get_codec("arista_eos")
        intent = codec.parse(_KSATOR.read_text())
        reparsed = codec.parse(codec.render(intent))
        assert reparsed.syslog_servers == ["10.83.28.52"]

    def test_classify_supported(self) -> None:
        caps = get_codec("arista_eos").capabilities
        assert caps.classify("/system/syslog-server") == "supported"
        assert "/system/syslog-server" in set(caps.supported)

    def test_noise_only_config_harvests_nothing(self) -> None:
        # A `logging` config with NO host destination must yield an empty list
        # and render no `logging host` line.
        codec = get_codec("arista_eos")
        noise = "logging buffered 5000\nlogging trap informational\n"
        intent = codec.parse(noise)
        assert intent.syslog_servers == []
        assert "logging host" not in codec.render(intent)


class TestCrossVendorSyslogPreserve:
    """A syslog host survives across each wired pair."""

    @pytest.mark.parametrize("target", ["cisco_iosxe_cli", "arista_eos", "juniper_junos", "cisco_nxos"])
    def test_arista_source_preserves_to_wired_target(self, target: str) -> None:
        arista = get_codec("arista_eos")
        tgt = get_codec(target)
        intent = arista.parse(_KSATOR.read_text())
        # Render to the target, then read it back with the target's own parser.
        reparsed = tgt.parse(tgt.render(intent))
        assert "10.83.28.52" in reparsed.syslog_servers


class TestInvalidIpRejected:
    """The IP-literal guard rejects tokens that are not valid IPv4/IPv6 — this
    is why a bare-hostname syslog target is a known (documented) gap and why
    an out-of-range dotted quad (``10.0.0.514``) is not mistaken for a host."""

    @pytest.mark.parametrize("codec_name", ["cisco_iosxe_cli", "arista_eos"])
    def test_out_of_range_quad_not_harvested(self, codec_name: str) -> None:
        codec = get_codec(codec_name)
        got = codec.parse("logging host 10.0.0.514\n").syslog_servers
        assert got == []
