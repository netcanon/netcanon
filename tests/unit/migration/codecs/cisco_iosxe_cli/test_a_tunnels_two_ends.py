"""A tunnel's two ends are read, written and said.

IOS states where a tunnel's packets leave from and where they go
(``tunnel source``, ``tunnel destination``).  No parser read either
line, and a job from IOS-XE to IOS-XE wrote each tunnel with no ends
in a job that said ``completed``.  The IOS-XE CLI parser reads them now,
into three fields of the tree -- an address or an interface for the
source, an address or a host name for the destination -- and the IOS-XE
CLI renderer writes them back.  Every other public codec declares the
three paths unsupported, so that a job onto it that holds a tunnel's end
is ``partial`` and lists the path, where it does not drop the tunnel
itself and list that.

The forms are Cisco's (Interface and Hardware Component Command
Reference): ``tunnel source {ip-address | ipv6-address | interface-type
interface-number | dynamic}`` and ``tunnel destination {host-name |
ip-address | ipv6-address | dynamic}``.  ``dynamic`` has no form in the
tree, and is said in a row of ``dropped_tier3_sections``; so is a line
of a form the parser does not read.

The source interface is a port name: the port translator moves it and a
drop of it is said (``test_what_goes_with_a_dropped_name.py``,
``test_port_name_universe.py``).  The sanitiser redacts a public address
and a host name (``tests/unit/tools/test_sanitize_completeness.py``).

Each check is also handed the defect it is for.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli import parse as ios_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from netcanon.tools.sanitize import sanitize_intent, sanitize_text

pytestmark = pytest.mark.unit

IOS = "cisco_iosxe_cli"

#: The three paths of a tunnel's ends.
_ENDS = (
    "/interfaces/interface/tunnel-source-address",
    "/interfaces/interface/tunnel-source-interface",
    "/interfaces/interface/tunnel-destination",
)

_TUNNELS = """hostname sw
!
interface Loopback0
 ip address 192.0.2.1 255.255.255.255
!
interface GigabitEthernet1/0/1
 no switchport
 ip address 10.1.0.1 255.255.255.0
!
interface Tunnel0
 ip address 10.9.0.1 255.255.255.252
 tunnel source Loopback0
 tunnel destination 198.51.100.7
!
interface Tunnel1
 ip address 10.9.1.1 255.255.255.252
 tunnel source 192.0.2.1
 tunnel destination 2001:db8::7
!
interface Tunnel2
 ip address 10.9.2.1 255.255.255.252
 tunnel source GigabitEthernet1/0/1
 tunnel destination vpn.example.test
!
end
"""

#: What each tunnel of :data:`_TUNNELS` states, typed by hand:
#: (source address, source interface, destination).
_STATED = {
    "Tunnel0": ("", "Loopback0", "198.51.100.7"),
    "Tunnel1": ("192.0.2.1", "", "2001:db8::7"),
    "Tunnel2": ("", "GigabitEthernet1/0/1", "vpn.example.test"),
}


def _one_tunnel(*lines: str) -> str:
    body = "".join(f"{line}\n" for line in lines)
    return f"hostname sw\n!\ninterface Tunnel0\n ip address 10.9.0.1 255.255.255.252\n{body}!\nend\n"


def _ends(tree) -> dict[str, tuple[str, str, str]]:
    return {
        iface.name: (
            iface.tunnel_source_address,
            iface.tunnel_source_interface,
            iface.tunnel_destination,
        )
        for iface in tree.interfaces
        if iface.name.startswith("Tunnel")
    }


def _rows(tree) -> list[str]:
    return [row for row in tree.dropped_tier3_sections if row.startswith("tunnel ")]


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


class TestTheParser:
    def test_every_tunnel_of_the_config(self) -> None:
        tree = get_codec(IOS).parse(_TUNNELS)
        assert _ends(tree) == _STATED
        assert _rows(tree) == []

    @pytest.mark.parametrize(("line", "stated"), [
        (" tunnel source 192.0.2.1", ("192.0.2.1", "", "")),
        (" tunnel source 2001:db8::1", ("2001:db8::1", "", "")),
        (" tunnel source Loopback0", ("", "Loopback0", "")),
        # A type and its number written apart are one name.
        (" tunnel source Loopback 0", ("", "Loopback0", "")),
        (" tunnel source GigabitEthernet 1/0/1", ("", "GigabitEthernet1/0/1", "")),
        (" tunnel  source  Loopback0  ", ("", "Loopback0", "")),
        (" TUNNEL SOURCE Loopback0", ("", "Loopback0", "")),
        (" tunnel destination 198.51.100.7", ("", "", "198.51.100.7")),
        (" tunnel destination 2001:db8::7", ("", "", "2001:db8::7")),
        (" tunnel destination vpn.example.test", ("", "", "vpn.example.test")),
    ])
    def test_each_form(self, line: str, stated: tuple[str, str, str]) -> None:
        tree = get_codec(IOS).parse(_one_tunnel(line))
        assert _ends(tree) == {"Tunnel0": stated}
        assert _rows(tree) == []

    @pytest.mark.parametrize("end", ["source", "destination"])
    def test_dynamic_is_said(self, end: str) -> None:
        tree = get_codec(IOS).parse(_one_tunnel(f" tunnel {end} dynamic"))
        assert _ends(tree) == {"Tunnel0": ("", "", "")}
        assert _rows(tree) == [
            f"tunnel {end} dynamic: Tunnel0 -- the tree has no form for an end "
            f"applied dynamically, so the tunnel is translated without it",
        ]

    @pytest.mark.parametrize(("line", "end"), [
        # Two words that are not one name.
        (" tunnel source foo bar", "source"),
        (" tunnel source 192.0.2.1 extra", "source"),
        (" tunnel destination 198.51.100.7 extra", "destination"),
    ])
    def test_a_form_not_read_is_said(self, line: str, end: str) -> None:
        tree = get_codec(IOS).parse(_one_tunnel(line))
        assert _ends(tree) == {"Tunnel0": ("", "", "")}
        assert _rows(tree) == [
            f"tunnel {end}: Tunnel0 -- a form of the line this parser does not "
            f"read, so the tunnel is translated without it",
        ]

    def test_a_row_names_each_interface_once(self) -> None:
        text = _one_tunnel(" tunnel source dynamic") + _one_tunnel(" tunnel source dynamic")
        assert _rows(get_codec(IOS).parse(text)) == [
            "tunnel source dynamic: Tunnel0 -- the tree has no form for an end "
            "applied dynamically, so the tunnel is translated without it",
        ]

    def test_a_later_line_of_the_same_end_replaces_an_earlier_one(self) -> None:
        """A tunnel has one source, as on the device."""
        ios = get_codec(IOS)
        tree = ios.parse(_one_tunnel(" tunnel source 192.0.2.1", " tunnel source Loopback0"))
        assert _ends(tree) == {"Tunnel0": ("", "Loopback0", "")}
        tree = ios.parse(_one_tunnel(" tunnel source Loopback0", " tunnel source 192.0.2.1"))
        assert _ends(tree) == {"Tunnel0": ("192.0.2.1", "", "")}

    def test_the_other_tunnel_lines_are_not_ends(self) -> None:
        tree = get_codec(IOS).parse(_one_tunnel(
            " tunnel mode gre ip", " tunnel key 5", " tunnel path-mtu-discovery",
        ))
        assert _ends(tree) == {"Tunnel0": ("", "", "")}
        assert tree.interfaces[0].tunnel_type == "gre"
        assert _rows(tree) == []


# ---------------------------------------------------------------------------
# IOS-XE onto IOS-XE
# ---------------------------------------------------------------------------


def _round_trip_problems(codec, text: str) -> list[str]:
    """What a parse, a render and a parse again lose of the ends, and
    the lines of the output that do not state them."""
    rendered = codec.render(codec.parse(text))
    problems = [
        f"{name}: {stated} came back as {_ends(codec.parse(rendered)).get(name)}"
        for name, stated in _ends(codec.parse(text)).items()
        if _ends(codec.parse(rendered)).get(name) != stated
    ]
    lines = [line.rstrip() for line in rendered.splitlines()]
    for source_address, source_interface, destination in _ends(codec.parse(text)).values():
        source = source_interface or source_address
        if source and f" tunnel source {source}" not in lines:
            problems.append(f"no line: tunnel source {source}")
        if destination and f" tunnel destination {destination}" not in lines:
            problems.append(f"no line: tunnel destination {destination}")
    return problems


class TestOntoItself:
    def test_the_round_trip(self) -> None:
        assert _round_trip_problems(get_codec(IOS), _TUNNELS) == []

    def test_the_job(self) -> None:
        ios = get_codec(IOS)
        job = run_plan_with_checked_names(ios, ios, _TUNNELS, port_rename_map={})
        assert job.status == MigrationJobStatus.completed
        assert _ends(ios.parse(job.rendered)) == _STATED
        assert set(_ENDS) <= set(job.validation.supported_paths)


# ---------------------------------------------------------------------------
# Onto every other public codec
# ---------------------------------------------------------------------------


def _unsaid(job: MigrationJob, tunnels: dict[str, tuple[str, str, str]]) -> list[str]:
    """The ends of *tunnels* a job onto a codec that writes none of
    them leaves unsaid: a job that says ``completed``, or a tunnel the
    job neither lists as unresolved nor reports the paths of its ends
    for."""
    problems = []
    if job.status == MigrationJobStatus.completed:
        problems.append("the job says completed")
    unsupported = {u.path for u in job.validation.unsupported_paths} if job.validation else set()
    for name, (source_address, source_interface, destination) in tunnels.items():
        if name in job.unresolved_ports:
            continue
        held = [
            path for path, value in zip(_ENDS, (source_address, source_interface, destination))
            if value
        ]
        missing = [path for path in held if path not in unsupported]
        if missing:
            problems.append(f"{name}: not listed unsupported: {missing}")
    return problems


#: An entry that keeps each tunnel by its own name, so that it is on
#: every target and its ends are the target's to write or not.
_KEEP = {name: name for name in _STATED}

_OTHERS = [name for name in list_public_codecs() if name != IOS]


class TestOntoEveryOtherCodec:
    @pytest.mark.parametrize("target", _OTHERS)
    def test_with_no_entry(self, target: str) -> None:
        job = run_plan_with_checked_names(
            get_codec(IOS), get_codec(target), _TUNNELS, port_rename_map={},
        )
        assert _unsaid(job, _STATED) == []

    @pytest.mark.parametrize("target", _OTHERS)
    def test_with_each_tunnel_kept(self, target: str) -> None:
        job = run_plan_with_checked_names(
            get_codec(IOS), get_codec(target), _TUNNELS, port_rename_map=_KEEP,
        )
        assert [name for name in _STATED if name in job.unresolved_ports] == []
        assert _unsaid(job, _STATED) == []
        # Written by none of them: no destination is in the output.
        for _source_address, _source_interface, destination in _STATED.values():
            assert destination not in job.rendered

    def test_every_public_codec_is_asked(self) -> None:
        assert sorted([*_OTHERS, IOS]) == sorted(list_public_codecs())


# ---------------------------------------------------------------------------
# The sanitiser
# ---------------------------------------------------------------------------

_PUBLIC = _one_tunnel(" tunnel source 8.8.8.8", " tunnel destination 9.9.9.9") + _one_tunnel(
    " tunnel source Loopback0", " tunnel destination vpn.corp.example.com",
).replace("Tunnel0", "Tunnel1")


class TestTheSanitiser:
    def test_a_public_address_and_a_host_name_are_redacted(self) -> None:
        sanitized, subs = sanitize_intent(get_codec(IOS).parse(_PUBLIC))
        ends = _ends(sanitized)
        assert ends["Tunnel0"][0] not in ("", "8.8.8.8")
        assert ends["Tunnel0"][2] not in ("", "9.9.9.9")
        # A port name stays.
        assert ends["Tunnel1"] == ("", "Loopback0", "host-1.example.test")
        fields = {sub.field for sub in subs}
        assert {
            "interfaces[0].tunnel_source_address",
            "interfaces[0].tunnel_destination",
            "interfaces[1].tunnel_destination",
        } <= fields

    def test_the_text(self) -> None:
        result = sanitize_text(_PUBLIC, IOS)
        for value in ("8.8.8.8", "9.9.9.9", "corp.example.com"):
            assert value not in result.sanitized_text
        assert " tunnel source Loopback0" in result.sanitized_text.splitlines()

    def test_a_private_address_stays(self) -> None:
        tree = get_codec(IOS).parse(
            _one_tunnel(" tunnel source 10.255.0.1", " tunnel destination 172.16.0.7"),
        )
        sanitized, _ = sanitize_intent(tree)
        assert _ends(sanitized)["Tunnel0"] == ("10.255.0.1", "", "172.16.0.7")


# ---------------------------------------------------------------------------
# Each check is handed the defect it is for
# ---------------------------------------------------------------------------


class _EndsCalledSupported(type(get_codec("arista_eos"))):
    """EOS, with a matrix that does not list the ends."""

    @property
    def capabilities(self):
        caps = super().capabilities
        return caps.model_copy(update={"unsupported": [
            u for u in caps.unsupported if u.path not in _ENDS
        ]})


class TestTheChecksCanFail:
    def test_a_parser_that_reads_no_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ios_parse, "_TUNNEL_END_RE", re.compile(r"(?!)"))
        assert _ends(get_codec(IOS).parse(_TUNNELS)) != _STATED

    def test_a_renderer_that_writes_no_destination(self) -> None:
        ios = get_codec(IOS)
        real = ios.render

        def without(tree, *args, **kwargs):
            return "\n".join(
                line for line in real(tree, *args, **kwargs).splitlines()
                if not line.startswith(" tunnel destination")
            )

        ios.render = without
        assert _round_trip_problems(ios, _TUNNELS) != []

    def test_a_matrix_that_calls_the_ends_supported(self) -> None:
        job = run_plan_with_checked_names(
            get_codec(IOS), _EndsCalledSupported(), _TUNNELS, port_rename_map=_KEEP,
        )
        assert _unsaid(job, _STATED) != []

    def test_a_job_that_drops_no_tunnel_and_lists_nothing(self) -> None:
        job = MigrationJob.model_construct(
            status=MigrationJobStatus.partial, unresolved_ports=[], validation=None,
        )
        assert _unsaid(job, _STATED) != []
