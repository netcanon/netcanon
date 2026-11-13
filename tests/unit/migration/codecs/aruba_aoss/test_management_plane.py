"""AOS-S's management plane is read and written: the domain, the
resolvers, the time servers the switch polls, and syslog.

The parser read the resolvers and the SNTP servers alone, each line
whatever came after the address and whether or not the switch ran an
SNTP client; it read no ``ntp server`` line (the time client of every
AOS-S 16.x config that has one), no domain and no ``logging`` line, and
the job did not say so.  The renderer wrote the domain while the matrix
said it was not written, every resolver and every time server at
priority 1, which the switch refuses after the first, and the time
servers with no ``sntp unicast`` and no ``timesync``, so that the
switch did not poll them.

What HPE documents for each form is in the module docstring of
:mod:`netcanon.migration.codecs.aruba_aoss.management_plane`.  What is
read and written is held to what is typed here, and the output is read
by a reader of this module's own, not by the parser.  Each check is
handed the defect it is for, and has to fail.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.aruba_aoss import management_plane as mp
from netcanon.migration.codecs.aruba_aoss import render as aoss_render
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

HEAD = (
    "; J9727A Configuration Editor; Created on release #WB.16.10.0010\n"
    'hostname "sw1"\n'
)

#: A plane in SNTP form: the second resolver's line before the first's,
#: a time server with a version and a key, a syslog server with words
#: after its address, and a line no field of the tree holds.
PLANE = HEAD + (
    "ip dns domain-name example.net\n"
    "ip dns server-address priority 2 2001:db8::53\n"
    "ip dns server-address priority 1 198.51.100.53\n"
    "timesync sntp\n"
    "sntp unicast\n"
    "sntp server priority 1 203.0.113.123\n"
    "sntp server priority 2 203.0.113.124 4 key-id 1\n"
    "logging 192.0.2.80\n"
    "logging 192.0.2.81 oobm\n"
    "time timezone -300\n"
)

#: What :data:`PLANE` states, typed by hand: the resolvers by priority.
PLANE_READ = {
    "domain": "example.net",
    "dns_servers": ["198.51.100.53", "2001:db8::53"],
    "ntp_servers": ["203.0.113.123", "203.0.113.124"],
    "syslog_servers": ["192.0.2.80", "192.0.2.81"],
}

#: The rows :data:`PLANE` gives: what is read and not translated.
PLANE_ROWS = [
    "sntp server ... key-id (",
    "logging ... (the words after the address",
    "time timezone ... (not translated)",
]

#: The same switch with an NTP client: ``timesync ntp``, unicast mode,
#: enabled, and a server's polling words and key.
NTP = HEAD + (
    "timesync ntp\n"
    "ntp unicast\n"
    "ntp server 203.0.113.10 iburst\n"
    "ntp server 203.0.113.11 key-id 5 max-poll 10\n"
    "ntp enable\n"
)

_EMPTY = {"domain": None, "dns_servers": [], "ntp_servers": [], "syslog_servers": []}


def _plane(tree: CanonicalIntent) -> dict:
    return {
        "domain": tree.domain or None,
        "dns_servers": list(tree.dns_servers),
        "ntp_servers": list(tree.ntp_servers),
        "syslog_servers": list(tree.syslog_servers),
    }


def _rows(tree: CanonicalIntent) -> list[str]:
    return list(tree.dropped_tier3_sections)


def _has_row(tree: CanonicalIntent, start: str) -> bool:
    return any(row.startswith(start) for row in _rows(tree))


def _no_value_in_a_row(tree: CanonicalIntent, text: str) -> None:
    """No address of *text* is in a row: a row names a statement, never
    its value."""
    values = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|[0-9a-f]*:[0-9a-f:]+", text)
    for row in _rows(tree):
        for value in values:
            assert value not in row, row


def _check_read(text: str, expected: dict, rows: list[str]) -> None:
    tree = get_codec("aruba_aoss").parse(text)
    assert _plane(tree) == expected
    for start in rows:
        assert _has_row(tree, start), start
    _no_value_in_a_row(tree, text)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def test_the_sntp_plane_is_read() -> None:
    _check_read(PLANE, PLANE_READ, PLANE_ROWS)


def test_the_ntp_client_is_read() -> None:
    _check_read(
        NTP, {**_EMPTY, "ntp_servers": ["203.0.113.10", "203.0.113.11"]},
        ["ntp server ... key-id ("],
    )


def test_the_check_fails_when_nothing_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mp.ManagementPlane, "read", lambda self, line: None)
    with pytest.raises(AssertionError):
        _check_read(PLANE, PLANE_READ, PLANE_ROWS)


#: Lines of the plane's words in forms AOS-S does not print, each with
#: an address in it, and the row each gives: its words, never a value.
ODD = HEAD + "logging host 192.0.2.99\nsntp 203.0.113.99\ntimesync 203.0.113.98\n"
ODD_ROWS = ["logging host ... (not translated)", "sntp (not translated)", "timesync (not translated)"]


def test_a_form_the_parser_does_not_read_is_said_by_its_words() -> None:
    _check_read(ODD, _EMPTY, ODD_ROWS)


def test_the_check_fails_when_a_row_names_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row that keeps the line as it stands names the address."""
    monkeypatch.setattr(mp, "_statement", lambda words: " ".join(words))
    with pytest.raises(AssertionError):
        _check_read(ODD, _EMPTY, [])


#: A time server the switch does not poll, in each way HPE gives: SNTP
#: with no mode (SNTP is enabled by giving it a mode), SNTP in
#: broadcast mode, SNTP where ``timesync`` selects another protocol;
#: NTP that is not enabled, and NTP where ``timesync`` is not ``ntp``.
UNPOLLED = {
    "sntp with no mode": ("sntp server priority 1 203.0.113.1\n", "sntp"),
    "sntp in broadcast mode": (
        "sntp broadcast\nsntp server priority 1 203.0.113.1\n", "sntp",
    ),
    "sntp under timesync timep": (
        "timesync timep\nsntp unicast\nsntp server priority 1 203.0.113.1\n", "sntp",
    ),
    "sntp under timesync ntp": (
        "timesync ntp\nsntp unicast\nsntp server priority 1 203.0.113.1\n", "sntp",
    ),
    "ntp not enabled": ("timesync ntp\nntp unicast\nntp server 203.0.113.1\n", "ntp"),
    "ntp under timesync sntp": (
        "timesync sntp\nntp unicast\nntp enable\nntp server 203.0.113.1\n", "ntp",
    ),
    "ntp with no timesync": ("ntp unicast\nntp enable\nntp server 203.0.113.1\n", "ntp"),
}


@pytest.mark.parametrize("case", sorted(UNPOLLED))
def test_a_time_server_the_switch_does_not_poll_is_left_out_and_said(case: str) -> None:
    body, protocol = UNPOLLED[case]
    _check_read(HEAD + body, _EMPTY, [f"disabled: {protocol} server ("])


@pytest.mark.parametrize("case", ["sntp with no mode", "ntp not enabled"])
def test_the_check_fails_for_a_parser_that_reads_every_server(
    case: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    finish = mp.ManagementPlane.finish

    def polls_everything(self):
        self._sntp_mode = self._ntp_mode = "unicast"
        self._ntp_enabled = True
        self._timesync = "ntp" if self._ntp else None
        return finish(self)

    monkeypatch.setattr(mp.ManagementPlane, "finish", polls_everything)
    body, protocol = UNPOLLED[case]
    with pytest.raises(AssertionError):
        _check_read(HEAD + body, _EMPTY, [f"disabled: {protocol} server ("])


def test_sntp_with_no_timesync_line_is_polled() -> None:
    """``timep-or-sntp`` is ``timesync``'s default, which runs SNTP."""
    _check_read(
        HEAD + "sntp unicast\nsntp server priority 1 203.0.113.1\n",
        {**_EMPTY, "ntp_servers": ["203.0.113.1"]}, [],
    )


def test_an_ntp_client_in_broadcast_mode_is_not_translated_and_said() -> None:
    """Broadcast is the NTP client's default mode, and no HPE page says
    whether it polls the servers it names: they are not translated,
    and the row says it is not established."""
    tree = get_codec("aruba_aoss").parse(
        HEAD + "timesync ntp\nntp enable\nntp server 203.0.113.1\n",
    )
    assert tree.ntp_servers == []
    assert _has_row(tree, "ntp server (the source's NTP client is in broadcast mode")
    assert not _has_row(tree, "disabled: ")


def test_a_priority_an_earlier_line_gave_is_not_read() -> None:
    """The switch refuses another address for a priority it holds."""
    _check_read(
        HEAD + (
            "ip dns server-address priority 1 198.51.100.1\n"
            "ip dns server-address priority 1 198.51.100.2\n"
            "sntp unicast\n"
            "sntp server priority 1 203.0.113.1\n"
            "sntp server priority 1 203.0.113.2\n"
        ),
        {**_EMPTY, "dns_servers": ["198.51.100.1"], "ntp_servers": ["203.0.113.1"]},
        ["ip dns server-address priority ... (a priority", "sntp server priority ... (a priority"],
    )


def test_a_syslog_server_after_the_sixth_is_not_read() -> None:
    lines = "".join(f"logging 192.0.2.{n}\n" for n in range(31, 38))
    _check_read(
        HEAD + lines,
        {**_EMPTY, "syslog_servers": [f"192.0.2.{n}" for n in range(31, 37)]},
        ["logging ... (an address after the sixth"],
    )


def test_of_two_domains_the_last_is_kept() -> None:
    tree = get_codec("aruba_aoss").parse(
        HEAD + "ip dns domain-name one.example\nip dns domain-name two.example\n",
    )
    assert tree.domain == "two.example"


def test_a_plane_line_after_a_stanza_with_no_indentation_is_read() -> None:
    """A line in column 0 that the top reads ends the stanza before it."""
    tree = get_codec("aruba_aoss").parse(
        HEAD + 'vlan 10\nname "ten"\nlogging 192.0.2.80\nip dns domain-name example.net\n',
    )
    assert (tree.syslog_servers, tree.domain) == (["192.0.2.80"], "example.net")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

#: The output's management plane, read here and not by the parser.
_WRITTEN = re.compile(
    r"^(?:ip dns domain-name (?P<domain>\S+)"
    r"|ip dns server-address priority (?P<dns_priority>[123]) (?P<dns>\S+)"
    r"|sntp server priority (?P<ntp_priority>[123]) (?P<ntp>\S+)"
    r"|logging (?P<syslog>\S+))$",
)


def _written(text: str) -> dict:
    """The management plane of an AOS-S output, read from its text: a
    time server only where the output makes the switch poll it, and a
    priority only once, from 1 up."""
    found: dict = {"domain": None, "dns_servers": [], "ntp_servers": [], "syslog_servers": []}
    lines = text.splitlines()
    for line in lines:
        m = _WRITTEN.match(line)
        if not m:
            continue
        if m["domain"]:
            found["domain"] = m["domain"]
        elif m["dns"]:
            assert int(m["dns_priority"]) == len(found["dns_servers"]) + 1, line
            found["dns_servers"].append(m["dns"])
        elif m["ntp"]:
            assert int(m["ntp_priority"]) == len(found["ntp_servers"]) + 1, line
            found["ntp_servers"].append(m["ntp"])
        else:
            found["syslog_servers"].append(m["syslog"])
    if found["ntp_servers"]:
        assert "sntp unicast" in lines and "timesync sntp" in lines
    return found


def _check_written(tree: CanonicalIntent) -> None:
    """The renderer writes the plane of *tree*, and the parser reads
    the same plane back."""
    out = get_codec("aruba_aoss").render(tree)
    assert _written(out) == _plane(tree)
    assert _plane(get_codec("aruba_aoss").parse(out)) == _plane(tree)


def test_a_round_trip_keeps_the_plane() -> None:
    _check_written(get_codec("aruba_aoss").parse(PLANE))


def test_an_ntp_client_is_written_as_sntp_and_read_back() -> None:
    _check_written(get_codec("aruba_aoss").parse(NTP))


def test_the_check_fails_when_nothing_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_render, "management_lines", lambda *a: mp.Written())
    with pytest.raises(AssertionError):
        _check_written(get_codec("aruba_aoss").parse(PLANE))


def test_the_check_fails_for_every_server_at_priority_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the renderer wrote before: the switch refuses the second."""
    written = mp.management_lines

    def at_priority_1(*args):
        out = written(*args)
        out.lines = [re.sub(r"priority \d ", "priority 1 ", line) for line in out.lines]
        return out

    monkeypatch.setattr(aoss_render, "management_lines", at_priority_1)
    with pytest.raises(AssertionError):
        _check_written(get_codec("aruba_aoss").parse(PLANE))


def test_the_check_fails_for_time_servers_the_switch_does_not_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the renderer wrote before: no ``sntp unicast``."""
    written = mp.management_lines

    def unpolled(*args):
        out = written(*args)
        out.lines = [line for line in out.lines if line not in ("sntp unicast", "timesync sntp")]
        return out

    monkeypatch.setattr(aoss_render, "management_lines", unpolled)
    with pytest.raises(AssertionError):
        _check_written(get_codec("aruba_aoss").parse(PLANE))


#: Sources in their own grammar, typed by hand, each stating the plane
#: of :data:`FROM_ELSEWHERE`.
SOURCES = {
    "juniper_junos": (
        "set system host-name r1\n"
        "set system domain-name example.net\n"
        "set system name-server 198.51.100.53\n"
        "set system ntp server 203.0.113.123\n"
        "set system syslog host 192.0.2.80 any any\n"
    ),
    "cisco_nxos": (
        "hostname n1\n"
        "ip domain-name example.net\n"
        "ip name-server 198.51.100.53\n"
        "ntp server 203.0.113.123\n"
        "logging server 192.0.2.80\n"
    ),
    "arista_eos": (
        "hostname a1\n"
        "dns domain example.net\n"
        "ip name-server 198.51.100.53\n"
        "ntp server 203.0.113.123\n"
        "logging host 192.0.2.80\n"
    ),
}
FROM_ELSEWHERE = {
    "domain": "example.net",
    "dns_servers": ["198.51.100.53"],
    "ntp_servers": ["203.0.113.123"],
    "syslog_servers": ["192.0.2.80"],
}


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_another_platforms_plane_reaches_the_output(source: str) -> None:
    job = run_plan_with_checked_names(
        get_codec(source), get_codec("aruba_aoss"), SOURCES[source], port_rename_map={},
    )
    assert job.rendered, job.error
    assert _written(job.rendered) == FROM_ELSEWHERE
    assert not [w for w in job.warnings if w.startswith("AOS-S is not given")]


# ---------------------------------------------------------------------------
# Left out
# ---------------------------------------------------------------------------

#: A value of each kind AOS-S cannot be given, past the most it takes
#: of each, beside values it takes.
LEFT_OUT = CanonicalIntent(
    hostname="sw1",
    dns_servers=[
        "198.51.100.1", "ns.example.net", "0.0.0.0", "198.51.100.2", "fe80::1%eth0",
        "198.51.100.3", "198.51.100.4",
    ],
    ntp_servers=[
        "time.example.org", "203.0.113.5", "fe80::5%vlan10", "::", "203.0.113.6",
        "203.0.113.7",
    ],
    syslog_servers=[
        "2001:db8::9", "log.example.org", *(f"192.0.2.{n}" for n in range(41, 48)),
    ],
)

#: What is not written, and what is, typed by hand.
NOT_WRITTEN = (
    "ns.example.net", "0.0.0.0", "fe80::1%eth0", "198.51.100.4", "time.example.org",
    "203.0.113.7", "2001:db8::9", "log.example.org", "192.0.2.47",
)
LEFT_OUT_WRITTEN = {
    "domain": None,
    "dns_servers": ["198.51.100.1", "198.51.100.2", "198.51.100.3"],
    "ntp_servers": ["203.0.113.5", "fe80::5%vlan10", "203.0.113.6"],
    "syslog_servers": [f"192.0.2.{n}" for n in range(41, 47)],
}


def _check_left_out(tree: CanonicalIntent) -> None:
    """What AOS-S cannot be given is in no line, each has a review line
    and a warning that name no value, and the rest is written."""
    out = get_codec("aruba_aoss").render(tree)
    lines = out.splitlines()
    for value in NOT_WRITTEN:
        assert not [line for line in lines if value in line.split()], value
    assert _written(out) == LEFT_OUT_WRITTEN
    reviews = [line for line in lines if line.startswith("; review: ")]
    for kind, why in (
        ("a DNS resolver", "is no address"), ("a DNS resolver", "after the third"),
        ("a time server", "is no address"), ("a time server", "after the third"),
        ("a syslog server", "is no address"), ("a syslog server", "IPv6"),
        ("a syslog server", "after the sixth"),
    ):
        assert any(kind in line and why in line for line in reviews), (kind, why)
    warnings = [
        w for w in get_codec("aruba_aoss").render_warnings(tree)
        if w.startswith("AOS-S is not given")
    ]
    assert len(warnings) == len(reviews) == 10
    for said in (*reviews, *warnings):
        for value in NOT_WRITTEN:
            assert value not in said.split(), said


def test_what_aoss_cannot_be_given_is_left_out_and_said() -> None:
    _check_left_out(LEFT_OUT)


@pytest.mark.parametrize("defect", ["every value", "every resolver", "every syslog server"])
def test_the_check_fails_for_a_renderer_that_writes_it(
    defect: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    if defect == "every value":
        monkeypatch.setattr(mp, "_given", lambda value: True)
    elif defect == "every resolver":
        monkeypatch.setattr(mp, "MOST_RESOLVERS", 99)
    else:
        monkeypatch.setattr(mp, "MOST_SYSLOG_SERVERS", 99)
    with pytest.raises(AssertionError):
        _check_left_out(LEFT_OUT)


def test_a_job_whose_target_is_not_given_a_resolver_is_partial() -> None:
    """A fourth resolver is a record AOS-S leaves out: the job says so."""
    job = run_plan_with_checked_names(
        get_codec("arista_eos"), get_codec("aruba_aoss"),
        "hostname a1\n" + "".join(f"ip name-server 198.51.100.{n}\n" for n in range(1, 5)),
        port_rename_map={},
    )
    assert job.status == "partial"
    assert job.error.startswith("The target left out 1 record(s)")
    assert any("after the third" in w for w in job.warnings)


# ---------------------------------------------------------------------------
# Onto every target
# ---------------------------------------------------------------------------

_PATHS = {
    "/system/domain": ["example.net"],
    "/system/dns-server": ["198.51.100.53", "2001:db8::53"],
    "/system/ntp-server": ["203.0.113.123", "203.0.113.124"],
    "/system/syslog-server": ["192.0.2.80", "192.0.2.81"],
}


@pytest.mark.parametrize("target", list_public_codecs())
def test_what_a_target_says_it_takes_is_in_its_output(target: str) -> None:
    """From AOS-S onto every public codec, each value of a path the
    target's matrix calls supported is in the output's text."""
    codec = get_codec(target)
    job = run_plan_with_checked_names(
        get_codec("aruba_aoss"), codec,
        PLANE + 'vlan 10\n   name "ten"\n   ip address 10.10.0.1 255.255.255.0\n   exit\n',
        port_rename_map={},
    )
    assert job.rendered, job.error
    for path, values in _PATHS.items():
        if codec.capabilities.classify(path) == "supported":
            for value in values:
                assert value in job.rendered, (path, value)
