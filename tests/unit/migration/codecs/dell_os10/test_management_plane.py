"""OS10's management plane is read and written in its bare forms.

An OS10 config's domain, resolvers, NTP servers and syslog servers were
read by nothing: each line was a row (``test_what_no_reader_takes.py``),
and a tree from another platform lost all four onto OS10.  The parser
now reads ``ip domain-name <name>``, ``ip name-server <ip> [<ip> ...]``,
``ntp server <host>`` and ``logging server <host>`` -- the forms Dell's
User Guide gives (10.4.1.0: a host is ``{hostname | ipv4-address |
ipv6-address}``, and ``ip name-server`` takes up to three addresses)
and the committed inputs print -- and the renderer writes them, after
the static routes and before SNMP, in the order the committed inputs
print them.

Only the bare form is read.  A tail says what the tree cannot hold (a
VRF, an NTP key or ``prefer``, a syslog transport, port or severity),
and the server written without it would be another statement, so such
a line keeps its row.  A value the form does not take is not written
-- a name server that is not an address, an NTP or syslog server that
is neither an address nor a host name, a domain not shaped as a domain
name -- nor are the resolvers after the third, and the output says so
in a review line that names the kind and no value.

What is read and written is held to what is typed here, and the output
is read by a reader of this module's own, not by the parser.  Each
check is handed the defect it is for, and has to fail.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.dell_os10 import parse as os10_parse
from netcanon.migration.codecs.dell_os10 import render as os10_render
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PLANE = (
    "! Version 10.5.4.0\n"
    "hostname sw1\n"
    "ip domain-name example.net\n"
    "ip name-server 192.0.2.53 2001:db8::53\n"
    "ip name-server 192.0.2.54\n"
    "ntp server 192.0.2.123\n"
    "ntp server 192.0.2.123\n"
    "ntp server time.example.org\n"
    "logging server 192.0.2.10\n"
    "logging server log.example.org\n"
)

#: What :data:`PLANE` states, typed by hand: each server once, in the
#: order its lines come.
PLANE_READ = {
    "domain": "example.net",
    "dns_servers": ["192.0.2.53", "2001:db8::53", "192.0.2.54"],
    "ntp_servers": ["192.0.2.123", "time.example.org"],
    "syslog_servers": ["192.0.2.10", "log.example.org"],
}

#: Lines with a tail, or with a value the forms do not take, and the row
#: each keeps: typed from Dell's grammar.
TAILS = [
    ("ip name-server vrf management 192.0.2.53", "ip name-server"),
    ("ip name-server 192.0.2.53 ns.example.net", "ip name-server"),
    ("ntp server 192.0.2.123 key 1", "ntp server"),
    ("ntp server 192.0.2.123 prefer", "ntp server"),
    ("ntp server 1.2.3", "ntp server"),
    ("ntp server time_one", "ntp server"),
    ("logging server 192.0.2.10 severity log-info", "logging server"),
    ("logging server 192.0.2.10 vrf management", "logging server"),
    ("logging server 192.0.2.10 tcp 601", "logging server"),
    ("logging server log_one", "logging server"),
    ("ip domain-name example.net extra", "ip domain-name"),
    ("ip domain-name vrf", "ip domain-name"),
    ("ntp enable vrf management", "ntp enable"),
    ("ip domain-list example.org", "ip domain-list"),
]

_EMPTY = {"domain": None, "dns_servers": [], "ntp_servers": [], "syslog_servers": []}

#: A line of the output in each bare form, read here and not by the
#: parser.
_WRITTEN = re.compile(
    r"^(ip name-server|ip domain-name|ntp server|logging server) (\S+)$",
)
_FIELD = {
    "ip name-server": "dns_servers",
    "ip domain-name": "domain",
    "ntp server": "ntp_servers",
    "logging server": "syslog_servers",
}


def _plane(tree: CanonicalIntent) -> dict:
    return {
        "domain": tree.domain or None,
        "dns_servers": list(tree.dns_servers),
        "ntp_servers": list(tree.ntp_servers),
        "syslog_servers": list(tree.syslog_servers),
    }


def _written(text: str) -> dict:
    """The management plane of an OS10 output, read from its text."""
    found: dict = {"domain": None, "dns_servers": [], "ntp_servers": [], "syslog_servers": []}
    for line in text.splitlines():
        m = _WRITTEN.match(line)
        if not m:
            continue
        field = _FIELD[m.group(1)]
        if field == "domain":
            found["domain"] = m.group(2)
        else:
            found[field].append(m.group(2))
    return found


def _check_read(text: str, expected: dict) -> None:
    tree = get_codec("dell_os10").parse(text)
    assert _plane(tree) == expected
    assert not [row for row in tree.dropped_tier3_sections if row in _FIELD]


def _check_written(tree: CanonicalIntent) -> None:
    """The renderer writes the plane of *tree* in the bare forms, and
    the parser reads the same plane back."""
    out = get_codec("dell_os10").render(tree)
    assert _written(out) == _plane(tree)
    assert _plane(get_codec("dell_os10").parse(out)) == _plane(tree)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def test_the_bare_forms_are_read() -> None:
    _check_read(PLANE, PLANE_READ)


@pytest.mark.parametrize("line,row", TAILS, ids=[t[0] for t in TAILS])
def test_a_line_with_a_tail_is_not_read_and_keeps_its_row(line: str, row: str) -> None:
    tree = get_codec("dell_os10").parse(f"hostname sw1\n{line}\n")
    assert _plane(tree) == _EMPTY
    assert row in tree.dropped_tier3_sections


def test_of_two_domains_the_last_is_kept() -> None:
    tree = get_codec("dell_os10").parse(
        "hostname sw1\nip domain-name one.example\nip domain-name two.example\n",
    )
    assert tree.domain == "two.example"


def test_an_indented_line_is_not_read() -> None:
    """A line under a stanza is not the switch's: only column 0 is read."""
    tree = get_codec("dell_os10").parse(
        "hostname sw1\ninterface ethernet1/1/1\n ntp server 192.0.2.1\n!\n",
    )
    assert tree.ntp_servers == []


def test_the_check_fails_when_nothing_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os10_parse, "_parse_management_plane", lambda raw, intent: None)
    with pytest.raises(AssertionError):
        _check_read(PLANE, PLANE_READ)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def test_a_round_trip_keeps_the_plane() -> None:
    tree = get_codec("dell_os10").parse(PLANE)
    _check_written(tree)
    assert _plane(tree) == PLANE_READ


def test_the_plane_sits_after_the_static_routes_and_before_snmp() -> None:
    out = get_codec("dell_os10").render(get_codec("dell_os10").parse(
        PLANE + "ip route 0.0.0.0/0 192.0.2.1\nsnmp-server location lab\n",
    ))
    lines = out.splitlines()
    plane = [n for n, line in enumerate(lines) if _WRITTEN.match(line)]
    assert [lines[n] for n in plane] == [
        "ip name-server 192.0.2.53",
        "ip name-server 2001:db8::53",
        "ip name-server 192.0.2.54",
        "ip domain-name example.net",
        "ntp server 192.0.2.123",
        "ntp server time.example.org",
        "logging server 192.0.2.10",
        "logging server log.example.org",
    ]
    assert plane == list(range(plane[0], plane[0] + len(plane)))
    route = next(n for n, line in enumerate(lines) if line.startswith("ip route "))
    snmp = next(n for n, line in enumerate(lines) if line.startswith("snmp-server "))
    assert route < plane[0] and plane[-1] < snmp


#: Sources in their own grammar, typed by hand, each stating the same
#: plane as :data:`FROM_ELSEWHERE`.
SOURCES = {
    "juniper_junos": (
        "set system host-name r1\n"
        "set system domain-name example.net\n"
        "set system name-server 192.0.2.53\n"
        "set system ntp server 192.0.2.123\n"
        "set system syslog host 192.0.2.10 any any\n"
    ),
    "cisco_nxos": (
        "hostname n1\n"
        "ip domain-name example.net\n"
        "ip name-server 192.0.2.53\n"
        "ntp server 192.0.2.123\n"
        "logging server 192.0.2.10\n"
    ),
    "arista_eos": (
        "hostname a1\n"
        "dns domain example.net\n"
        "ip name-server 192.0.2.53\n"
        "ntp server 192.0.2.123\n"
        "logging host 192.0.2.10\n"
    ),
}
FROM_ELSEWHERE = {
    "domain": "example.net",
    "dns_servers": ["192.0.2.53"],
    "ntp_servers": ["192.0.2.123"],
    "syslog_servers": ["192.0.2.10"],
}


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_another_platforms_plane_reaches_the_output(source: str) -> None:
    job = run_plan_with_checked_names(
        get_codec(source), get_codec("dell_os10"), SOURCES[source], port_rename_map={},
    )
    assert job.rendered, job.error
    assert _written(job.rendered) == FROM_ELSEWHERE


def test_the_check_fails_when_nothing_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os10_render, "_render_management_plane", lambda tree: [])
    with pytest.raises(AssertionError):
        _check_written(get_codec("dell_os10").parse(PLANE))


def test_the_check_fails_for_a_form_with_a_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """A renderer that writes ``prefer`` after each NTP server writes a
    line the parser does not read back: the check fails."""
    written = os10_render._render_management_plane

    def with_a_tail(tree):
        return [
            f"{line} prefer" if line.startswith("ntp server ") else line
            for line in written(tree)
        ]

    monkeypatch.setattr(os10_render, "_render_management_plane", with_a_tail)
    with pytest.raises(AssertionError):
        _check_written(get_codec("dell_os10").parse(PLANE))


# ---------------------------------------------------------------------------
# Left out
# ---------------------------------------------------------------------------

#: A value of each kind the form does not take, a host name for each
#: kind that takes one, and a fourth resolver.
LEFT_OUT = CanonicalIntent(
    hostname="sw1",
    domain="exa_mple",
    dns_servers=["192.0.2.1", "ns.example.net", "192.0.2.2", "192.0.2.3", "192.0.2.4"],
    ntp_servers=["time.example.org", "time_one"],
    syslog_servers=["log_one", "192.0.2.9"],
)


def _check_left_out(out: str) -> None:
    """What the forms do not take is in no line, nor is the fourth
    resolver; each has a review line that names no value; and the
    rest is written."""
    for value in ("exa_mple", "ns.example.net", "time_one", "log_one", "192.0.2.4"):
        assert value not in out, value
    reviews = [line for line in out.splitlines() if line.startswith("! ") and "-- review:" in line]
    for kind in ("ip name-server", "ip domain-name", "ntp server", "logging server"):
        assert any(
            line.startswith(f"! {kind} -- review:") and "is not" in line for line in reviews
        ), kind
    assert any(
        line.startswith("! ip name-server -- review:") and "three" in line for line in reviews
    )
    assert _written(out) == {
        "domain": None,
        "dns_servers": ["192.0.2.1", "192.0.2.2", "192.0.2.3"],
        "ntp_servers": ["time.example.org"],
        "syslog_servers": ["192.0.2.9"],
    }


def test_what_a_form_does_not_take_is_left_out_and_said() -> None:
    out = get_codec("dell_os10").render(LEFT_OUT)
    _check_left_out(out)
    back = get_codec("dell_os10").parse(out)
    assert back.dropped_tier3_sections == []


def test_the_check_fails_for_a_renderer_that_writes_every_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os10_parse, "an_address", lambda value: True)
    monkeypatch.setattr(os10_parse, "a_domain_name", lambda value: True)
    with pytest.raises(AssertionError):
        _check_left_out(get_codec("dell_os10").render(LEFT_OUT))


def test_the_check_fails_for_a_renderer_that_takes_no_host_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os10_parse, "a_host", os10_parse.an_address)
    with pytest.raises(AssertionError):
        _check_left_out(get_codec("dell_os10").render(LEFT_OUT))


def test_the_check_fails_for_a_renderer_that_writes_every_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os10_render, "_NAME_SERVERS_AT_MOST", 99)
    with pytest.raises(AssertionError):
        _check_left_out(get_codec("dell_os10").render(LEFT_OUT))


# ---------------------------------------------------------------------------
# Onto every target
# ---------------------------------------------------------------------------

_PATHS = {
    "/system/domain": ["example.net"],
    "/system/dns-server": ["192.0.2.53", "2001:db8::53", "192.0.2.54"],
    "/system/ntp-server": ["192.0.2.123", "time.example.org"],
    "/system/syslog-server": ["192.0.2.10", "log.example.org"],
}


@pytest.mark.parametrize("target", list_public_codecs())
def test_what_a_target_says_it_takes_is_in_its_output(target: str) -> None:
    """From OS10 onto every public codec, each value of a path the
    target's matrix calls supported is in the output's text."""
    codec = get_codec(target)
    job = run_plan_with_checked_names(
        get_codec("dell_os10"), codec,
        PLANE + "interface ethernet1/1/1\n no switchport\n ip address 198.51.100.1/24\n!\n",
        port_rename_map={},
    )
    assert job.rendered, job.error
    for path, values in _PATHS.items():
        if codec.capabilities.classify(path) == "supported":
            for value in values:
                assert value in job.rendered, (path, value)
