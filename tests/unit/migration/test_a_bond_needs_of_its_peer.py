"""A LAG is written as what the ports it faces must be configured for.

A LAG's mode decides what its PEER has to be: an LACP partner, a static
aggregate of its own, or nothing at all.  Every switch parser reads
``static`` from the platform's static aggregate (``mode on``, an AOS-S
``trunk``).  Up to 2026-11 the RouterOS, VyOS and OPNsense renderers
wrote ``static`` as a bond that needs no aggregate -- RouterOS
``active-backup``, OPNsense ``failover``, and on VyOS no ``mode`` line,
which is 802.3ad -- so a switch's static port-channel came out as a bond
that drops what its peer hashes onto the second port; and their parsers
read a bond that needs no aggregate as ``static``, which every switch
then wrote as ``mode on``.  The jobs said ``completed``.

What each word asks of the peer is typed here from the vendors' own
pages, and each output is read by a reader of its own grammar, typed
here too, never by the codec's parser:

* Linux bonding, Switch Configuration: "The active-backup, balance-tlb
  and balance-alb modes do not require any specific configuration of the
  switch"; balance-rr, balance-xor and broadcast "generally require that
  the switch have the appropriate ports grouped together"; 802.3ad needs
  the ports "configured as an 802.3ad aggregation".  RouterOS's default
  mode is balance-rr (MikroTik, Bonding).
* VyOS bonding: "The default is 802.3ad"; xor-hash "operates without the
  LACP", and round-robin and xor-hash are its "EtherChannel-compatible
  modes".
* FreeBSD lagg(4): ``failover`` "Sends traffic only through the active
  port", and by default received traffic "is only accepted when it is
  received through the active port"; ``loadbalance`` "is a static setup
  and does not negotiate aggregation with the peer"; OPNsense lists
  ``fec`` as the same.

A switch has no bond that needs nothing of its peer: it writes such a
LAG as a static aggregate, with a review line beside it (IOS XR, which
writes no review line, says it in the job's warnings alone) and a
warning in the job.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration._bonds import ACTIVE_BACKUP
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

LACP, AGGREGATE, NOTHING = "LACP", "an aggregate", "nothing"

#: Linux bonding (RouterOS): what each mode needs of the switch.
LINUX = {
    "802.3ad": LACP,
    "balance-rr": AGGREGATE,
    "balance-xor": AGGREGATE,
    "broadcast": AGGREGATE,
    "active-backup": NOTHING,
    "balance-tlb": NOTHING,
    "balance-alb": NOTHING,
}
ROUTEROS_DEFAULT = "balance-rr"

#: VyOS bonding.
VYOS = {
    "802.3ad": LACP,
    "round-robin": AGGREGATE,
    "xor-hash": AGGREGATE,
    "broadcast": AGGREGATE,
    "active-backup": NOTHING,
    "transmit-load-balance": NOTHING,
    "adaptive-load-balance": NOTHING,
}
VYOS_DEFAULT = "802.3ad"

#: FreeBSD lagg(4), as OPNsense names its protocols.
FREEBSD = {
    "lacp": LACP,
    "loadbalance": AGGREGATE,
    "fec": AGGREGATE,
    "roundrobin": AGGREGATE,
    "broadcast": AGGREGATE,
    "failover": NOTHING,
}

#: What the tree holds for each need (netcanon.migration._bonds).
CANONICAL = {LACP: "active", AGGREGATE: "static", NOTHING: ACTIVE_BACKUP}

#: The targets that have a bond needing nothing of its peer.
HOSTS = frozenset({"mikrotik_routeros", "vyos", "opnsense"})

#: The target that writes no LAG at all (its matrix says so).
WRITES_NO_LAG = frozenset({"cisco_iosxe"})

#: The target that writes no review line anywhere; the job says it.
NO_REVIEW_LINES = frozenset({"cisco_iosxr"})

#: What the review line and the warning say, typed here.
SAID = "needs no aggregate of its peer ports"


# ---------------------------------------------------------------------------
# Sources, one bond each, in each platform's own grammar
# ---------------------------------------------------------------------------


def _routeros(word: str | None) -> str:
    mode = f" mode={word}" if word else ""
    return (
        "/interface bonding\n"
        f"add name=bond1 slaves=ether2,ether3{mode}\n"
        "/ip address\n"
        "add address=10.0.0.1/24 interface=bond1\n"
        "/system identity\n"
        "set name=r1\n"
    )


def _vyos(word: str | None) -> str:
    mode = f"        mode {word}\n" if word else ""
    return (
        "interfaces {\n"
        "    bonding bond1 {\n"
        '        address "10.0.0.1/24"\n'
        f"{mode}"
        "        member {\n"
        "            interface eth1\n"
        "            interface eth2\n"
        "        }\n"
        "    }\n"
        "    ethernet eth1 {\n"
        "    }\n"
        "    ethernet eth2 {\n"
        "    }\n"
        "}\n"
        "system {\n"
        "    host-name r1\n"
        "}\n"
    )


def _opnsense(word: str) -> str:
    return (
        '<?xml version="1.0"?>\n'
        "<opnsense>\n"
        "  <system><hostname>fw1</hostname></system>\n"
        "  <interfaces>\n"
        "    <lan><if>lagg1</if><enable>1</enable>"
        "<ipaddr>10.0.0.1</ipaddr><subnet>24</subnet></lan>\n"
        "  </interfaces>\n"
        "  <laggs>\n"
        "    <lagg><laggif>lagg1</laggif><members>igb1,igb2</members>"
        f"<proto>{word}</proto></lagg>\n"
        "  </laggs>\n"
        "</opnsense>\n"
    )


def _iosxe(word: str) -> str:
    return (
        "hostname sw1\n"
        "interface GigabitEthernet1/0/1\n"
        f" channel-group 1 mode {word}\n"
        "!\n"
        "interface GigabitEthernet1/0/2\n"
        f" channel-group 1 mode {word}\n"
        "!\n"
        "interface Port-channel1\n"
        " no switchport\n"
        " ip address 10.0.0.1 255.255.255.0\n"
        "!\n"
        "end\n"
    )


#: (source codec, word, config, what the source asks of its peer).
SOURCES = [
    *[("mikrotik_routeros", w, _routeros(w), need) for w, need in LINUX.items()],
    ("mikrotik_routeros", None, _routeros(None), LINUX[ROUTEROS_DEFAULT]),
    *[("vyos", w, _vyos(w), need) for w, need in VYOS.items()],
    ("vyos", None, _vyos(None), VYOS[VYOS_DEFAULT]),
    *[("opnsense", w, _opnsense(w), need) for w, need in FREEBSD.items()],
    ("cisco_iosxe_cli", "on", _iosxe("on"), AGGREGATE),
    ("cisco_iosxe_cli", "active", _iosxe("active"), LACP),
]


def _ids(source):
    return f"{source[0]}-{source[1] or 'no-mode'}"


# ---------------------------------------------------------------------------
# Readers of each target's text: what its LAGs ask of their peer
# ---------------------------------------------------------------------------

_CHANNEL_GROUP = re.compile(r"(?m)^[ \t]*channel-group \d+ mode (\S+)[ \t]*$")
_BUNDLE = re.compile(r"(?m)^[ \t]*bundle id \d+ mode (\S+)[ \t]*$")
_AOSS_TRUNK = re.compile(r"(?m)^trunk \S+ \S+ (\S+)[ \t]*$")
_JUNOS_MEMBER_OF = re.compile(r"(?m)^set interfaces \S+ ether-options 802\.3ad (ae\d+)[ \t]*$")
_JUNOS_LACP = re.compile(
    r"(?m)^set interfaces (ae\d+) aggregated-ether-options lacp (?:active|passive)[ \t]*$",
)
_FORTI_LACP_MODE = re.compile(r"(?m)^[ \t]*set lacp-mode (\S+)[ \t]*$")
_ROUTEROS_BOND = re.compile(r"(?m)^(?:/interface bonding )?add\b(?=.*\bslaves=)(.*)$")
_ROUTEROS_MODE = re.compile(r"\bmode=(\S+)")
_OPNSENSE_PROTO = re.compile(r"<lagg>.*?<proto>([^<]*)</proto>", re.S)


def _switch_word(word: str) -> str:
    return AGGREGATE if word == "on" else LACP


def _aoscx(text: str) -> list[str]:
    needs, inside, lacp = [], False, False
    for line in [*text.splitlines(), "end"]:
        if inside and line[:1] not in (" ", "\t"):
            needs.append(LACP if lacp else AGGREGATE)
            inside = False
        if re.match(r"interface lag \d+[ \t]*$", line):
            inside, lacp = True, False
        elif inside and re.match(r"[ \t]+lacp mode (?:active|passive)[ \t]*$", line):
            lacp = True
    return needs


def _vyos_out(text: str) -> list[str]:
    needs, depth, bond_depth, word = [], 0, None, None
    for line in text.splitlines():
        stripped = line.strip()
        if bond_depth is None and re.match(r"bonding \S+ \{$", stripped):
            bond_depth, word = depth, None
        elif bond_depth is not None and depth == bond_depth + 1:
            m = re.match(r"mode (\S+)$", stripped)
            if m:
                word = m.group(1)
        depth += stripped.endswith("{") - (stripped == "}")
        if bond_depth is not None and depth == bond_depth:
            needs.append(VYOS[word or VYOS_DEFAULT])
            bond_depth = None
    return needs


def peer_needs(target: str, text: str) -> list[str]:
    """What each LAG of *text* asks of its peer, read by *target*'s grammar."""
    if target in ("arista_eos", "cisco_iosxe_cli", "cisco_nxos", "dell_os10"):
        # A member line each; one LAG here, so one reading of the set.
        return sorted({_switch_word(w) for w in _CHANNEL_GROUP.findall(text)})
    if target == "cisco_iosxr":
        return sorted({_switch_word(w) for w in _BUNDLE.findall(text)})
    if target == "aruba_aoss":
        return [AGGREGATE if w == "trunk" else LACP for w in _AOSS_TRUNK.findall(text)]
    if target == "aruba_aoscx":
        return _aoscx(text)
    if target == "juniper_junos":
        lacp = set(_JUNOS_LACP.findall(text))
        return [LACP if ae in lacp else AGGREGATE for ae in sorted(set(_JUNOS_MEMBER_OF.findall(text)))]
    if target == "fortigate_cli":
        return [AGGREGATE if w == "static" else LACP for w in _FORTI_LACP_MODE.findall(text)]
    if target == "mikrotik_routeros":
        out = []
        for rest in _ROUTEROS_BOND.findall(text):
            m = _ROUTEROS_MODE.search(rest)
            out.append(LINUX[m.group(1) if m else ROUTEROS_DEFAULT])
        return out
    if target == "vyos":
        return _vyos_out(text)
    if target == "opnsense":
        return [FREEBSD[w] for w in _OPNSENSE_PROTO.findall(text)]
    raise AssertionError(f"no reader for {target}: add one, typed from its grammar")


_TARGETS = list_public_codecs()


def check(source, target: str) -> None:
    """The output of *source* onto *target* asks of its peer what the
    source asks, or -- for a bond that needs nothing, on a target that
    has none -- is a static aggregate that says so."""
    codec, word, text, need = source
    job = run_plan_with_checked_names(
        get_codec(codec), get_codec(target), text, port_rename_map={},
    )
    out = job.rendered or ""
    read = peer_needs(target, out)
    said = [w for w in job.warnings if SAID in w]
    reviewed = "review:" in out and SAID in out
    if need == NOTHING and target not in HOSTS:
        assert read == [AGGREGATE], (codec, word, target, read)
        assert said, (codec, word, target, "no warning")
        assert reviewed or target in NO_REVIEW_LINES, (codec, word, target, "no review line")
    else:
        assert read == [need], (codec, word, target, read, need)
        assert not said and not reviewed, (codec, word, target, "said active-backup")


@pytest.mark.parametrize("target", [t for t in _TARGETS if t not in WRITES_NO_LAG])
@pytest.mark.parametrize("source", SOURCES, ids=_ids)
def test_the_output_asks_of_the_peer_what_the_source_does(source, target):
    check(source, target)


def test_every_public_codec_has_a_reader_or_writes_no_lag():
    for target in _TARGETS:
        if target in WRITES_NO_LAG:
            continue
        peer_needs(target, "")


@pytest.mark.parametrize("source", SOURCES, ids=_ids)
def test_the_parser_reads_what_the_bond_needs(source):
    codec, word, text, need = source
    tree = get_codec(codec).parse(text)
    assert [lag.mode for lag in tree.lags] == [CANONICAL[need]], (codec, word)


@pytest.mark.parametrize("target", _TARGETS)
def test_what_a_codec_says_it_writes_is_what_it_writes(target):
    """``active_backup_written_as`` is held to the output, by experiment."""
    source = ("mikrotik_routeros", "active-backup", _routeros("active-backup"), NOTHING)
    codec = get_codec(target)
    job = run_plan_with_checked_names(
        get_codec(source[0]), codec, source[2], port_rename_map={},
    )
    said = [w for w in job.warnings if SAID in w]
    stated = codec.active_backup_written_as
    if stated == "nothing":
        assert target in WRITES_NO_LAG and not said
        return
    read = peer_needs(target, job.rendered or "")
    if stated == "itself":
        assert read == [NOTHING] and not said
    else:
        assert stated == "static" and read == [AGGREGATE] and said


# ---------------------------------------------------------------------------
# Each check is handed the defect it is for
# ---------------------------------------------------------------------------


def _fails(source, target) -> bool:
    try:
        check(source, target)
    except AssertionError:
        return True
    return False


_STATIC = ("cisco_iosxe_cli", "on", _iosxe("on"), AGGREGATE)
_BACKUP = ("mikrotik_routeros", "active-backup", _routeros("active-backup"), NOTHING)


def test_the_check_fails_on_the_old_render_maps(monkeypatch):
    from netcanon.migration.codecs.mikrotik_routeros import render as ros
    from netcanon.migration.codecs.opnsense import render as opn
    from netcanon.migration.codecs.vyos import render as vy

    assert not _fails(_STATIC, "opnsense")
    monkeypatch.setitem(opn._CANONICAL_MODE_TO_OPNSENSE_PROTO, "static", "failover")
    assert _fails(_STATIC, "opnsense")
    monkeypatch.setitem(ros._CANONICAL_MODE_TO_ROUTEROS_BONDING, "static", "active-backup")
    assert _fails(_STATIC, "mikrotik_routeros")
    monkeypatch.delitem(vy._CANONICAL_TO_VYOS_BOND_MODE, "static")
    assert _fails(_STATIC, "vyos")


def test_the_check_fails_on_the_old_parse_maps(monkeypatch):
    from netcanon.migration.codecs.mikrotik_routeros import parse as ros

    assert not _fails(_BACKUP, "mikrotik_routeros")
    monkeypatch.setitem(ros._ROUTEROS_BONDING_MODE_TO_CANONICAL, "active-backup", "static")
    assert _fails(_BACKUP, "mikrotik_routeros")
    assert _fails(_BACKUP, "arista_eos")


def test_the_check_fails_without_the_review_line_or_the_warning(monkeypatch):
    from netcanon.migration.codecs import base
    from netcanon.migration.codecs.arista_eos import render as eos

    assert not _fails(_BACKUP, "arista_eos")
    monkeypatch.setattr(eos, "active_backup_review", lambda name: "nothing to see")
    assert _fails(_BACKUP, "arista_eos")
    monkeypatch.undo()
    monkeypatch.setattr(base, "active_backup_warnings", lambda lags: [])
    assert _fails(_BACKUP, "cisco_iosxr")


def test_a_reader_is_not_its_own_oracle():
    """The readers answer from the text alone: a hand-typed line of each
    grammar reads as the vendor's page says."""
    assert peer_needs("opnsense", "<lagg><proto>failover</proto></lagg>") == [NOTHING]
    assert peer_needs("opnsense", "<lagg><proto>loadbalance</proto></lagg>") == [AGGREGATE]
    assert peer_needs("mikrotik_routeros", "add name=bond1 slaves=ether1,ether2") == [AGGREGATE]
    assert peer_needs(
        "mikrotik_routeros", "add mode=active-backup name=bond1 slaves=ether1,ether2",
    ) == [NOTHING]
    assert peer_needs("vyos", "interfaces {\n    bonding bond1 {\n    }\n}\n") == [LACP]
    assert peer_needs(
        "vyos", "interfaces {\n    bonding bond1 {\n        mode xor-hash\n    }\n}\n",
    ) == [AGGREGATE]
    assert peer_needs("arista_eos", "interface Ethernet1\n   channel-group 1 mode on\n") == [AGGREGATE]
    assert peer_needs("aruba_aoscx", "interface lag 1\n    no shutdown\n!\n") == [AGGREGATE]
    assert peer_needs(
        "aruba_aoscx", "interface lag 1\n    lacp mode active\n!\n",
    ) == [LACP]
