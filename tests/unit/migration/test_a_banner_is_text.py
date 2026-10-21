"""A banner is text, not config: IOS-XE CLI, NX-OS, AOS-CX, OS10, AOS-S
and IOS XR (and, for the line ends of a body, EOS).

Each of these parsers read a banner's body as lines of the config.  A
banner whose body held a line ``username <name> privilege 15 ...`` in
the platform's own grammar, and lines that began ``vlan``,
``interface`` and ``ip route``, came out with that account, VLAN,
interface and route on every target, in jobs that said ``completed``.
No committed banner body holds such a line, so nothing in the corpus
showed it.

Each platform ends a body its own way, from its vendor:

* IOS / IOS-XE -- the delimiter after the keyword, printed as the two
  characters ``^C``, ends the body wherever it next occurs (on the line
  that opens it, in the middle of a line, at its start); what follows
  it on its line is discarded.  The same for ``aaa authentication
  banner`` / ``fail-message``, ``menu`` titles and prompts,
  ``busy-message``, a line's ``vacant-message`` / ``refuse-message``
  and a web authentication ``banner text`` / ``title`` (the last two
  at any indentation); a ``macro name`` runs to a line that is ``@``.
* NX-OS -- the delimiter as typed, wherever it next occurs; a
  ``scheduler job name`` runs to a line that is ``end-job``.
* AOS-CX -- the one character after the type, at the end of a later
  line: the switch prints the stored text and then the character, so
  one with text after it on its line is the text's own.
* AOS-S -- a printed banner is a double-quoted string across lines,
  ended by the first quote no backslash escapes; text after it is
  refused.  A banner typed with another delimiter ends at its next
  occurrence.
* OS10 -- a line that is the delimiter and nothing else, in column 0.
* IOS XR -- the ONE character after the type (``^C`` is ``^``),
  wherever it next occurs, the line that opens the banner included; XR
  prints the delimiter that was typed, and what follows the closer on
  its line is the banner's.  ``aaa banner login`` the same.  Each kind
  of banner is a row of ``dropped_tier3_sections`` with its count of
  lines.

A body with no end is refused in words, naming the line that opens it
and quoting nothing.  So is a line of a body that ends in another of
the characters ``str.splitlines`` ends a line at (a form feed, a
vertical tab ...), on all seven parsers; on IOS-XE, AOS-S and OS10,
a line outside every body that holds what the device printed to end a
banner whose own text held it too; and on IOS XR, a line that names a
banner XR does not print, and a ``^`` alone in a banner printed with
``^C`` (one delimiter or two: the readings end it on different
lines).  Tested here:

(a) for each parser, a banner whose body holds an account, a VLAN, an
    interface with an address, a route and an ACL: the parse holds none
    of it, and the job onto every public codec writes none of it;
(b) each form, the opener and the closer as the vendor prints them, with
    what the parser makes of the text typed by hand beside it;
(c) each refusal, with its sentence;
(d) every committed input of the seven parses to the tree it gave before
    the change, and none is refused;
(e) a line end the device does not count, in every place of a body, on
    the seven;
(f) each check, handed the defect it is for, fails (the last section).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from netcanon.migration.codecs import _scanner
from netcanon.migration.codecs.arista_eos import parse as eos_parse
from netcanon.migration.codecs.aruba_aoscx import codec as aoscx_codec
from netcanon.migration.codecs.aruba_aoscx import parse as aoscx_parse
from netcanon.migration.codecs.aruba_aoss import codec as aoss_codec
from netcanon.migration.codecs.aruba_aoss import deployment_detect as aoss_detect
from netcanon.migration.codecs.aruba_aoss import parse as aoss_parse
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.cisco_iosxe_cli import codec as ios_codec
from netcanon.migration.codecs.cisco_iosxe_cli import parse as ios_parse
from netcanon.migration.codecs.cisco_iosxr import codec as xr_codec
from netcanon.migration.codecs.cisco_iosxr import parse as xr_parse
from netcanon.migration.codecs.cisco_nxos import codec as nxos_codec
from netcanon.migration.codecs.cisco_nxos import parse as nxos_parse
from netcanon.migration.codecs.dell_os10 import codec as os10_codec
from netcanon.migration.codecs.dell_os10 import parse as os10_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_detect import detect_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

#: Each parser's module and its codec's module: the two places that call
#: the body pass (the parse, and the Tier-3 rows the codec reads after
#: it).
MODULES: dict[str, tuple[ModuleType, ModuleType]] = {
    "cisco_iosxe_cli": (ios_parse, ios_codec),
    "cisco_nxos": (nxos_parse, nxos_codec),
    "aruba_aoscx": (aoscx_parse, aoscx_codec),
    "dell_os10": (os10_parse, os10_codec),
    "aruba_aoss": (aoss_parse, aoss_codec),
    "cisco_iosxr": (xr_parse, xr_codec),
}
CODECS = list(MODULES)


def _parse(codec: str, text: str):
    return get_codec(codec).parse(text)


def _refusal(codec: str, text: str) -> ParseError:
    with pytest.raises(ParseError) as caught:
        _parse(codec, text)
    return caught.value


# ---------------------------------------------------------------------------
# Small configs, typed by hand
# ---------------------------------------------------------------------------

#: What comes before a banner: the lines each platform prints first.
HEAD = {
    "cisco_iosxe_cli": "Building configuration...\n!\nversion 17.9\n",
    "cisco_nxos": "!Command: show running-config\n!\nversion 9.3(5)\n",
    "aruba_aoscx": "!Version ArubaOS-CX GL.10.09.0010\n!\n",
    "dell_os10": "! Version 10.5.1.0\n!\n",
    "aruba_aoss": "; J9729A Configuration Editor; Created on release #WC.16.10.0001\n",
    "cisco_iosxr": "!! IOS XR Configuration 7.3.2\n!\n",
}
#: What comes after it, in each grammar: a VLAN, an interface with an
#: address and a route.  None of them holds a delimiter a test below
#: uses (no ``!`` and no ``^C`` line, no odd number of quotes), so a
#: banner opened before them and never ended is refused.  (AOS-S's
#: names are quoted.  IOS XR's has no ``!``, ``^``, ``;``, ``#`` and no
#: ``"``; it has ``/`` and ``c``, which no IOS XR banner below leaves
#: open.  Its VLAN is a sub-interface's tag.)
AFTER = {
    "cisco_iosxe_cli": (
        "hostname r1\n!\nvlan 10\n name users\n!\ninterface GigabitEthernet1\n"
        " ip address 192.0.2.1 255.255.255.0\n!\nip route 0.0.0.0 0.0.0.0 192.0.2.254\n!\nend\n"
    ),
    "cisco_nxos": (
        "hostname n1\nfeature interface-vlan\nvlan 10\n  name users\n\ninterface Ethernet1/1\n"
        "  no switchport\n  ip address 192.0.2.1/24\n  no shutdown\n\nip route 0.0.0.0/0 192.0.2.254\n"
    ),
    "aruba_aoscx": (
        "hostname c1\nvlan 10\n    name users\ninterface 1/1/1\n    no shutdown\n    routing\n"
        "    ip address 192.0.2.1/24\nip route 0.0.0.0/0 192.0.2.254\n"
    ),
    "dell_os10": (
        "hostname d1\ninterface vlan10\n no shutdown\n\ninterface ethernet1/1/1\n no switchport\n"
        " ip address 192.0.2.1/24\n no shutdown\n\nip route 0.0.0.0/0 192.0.2.254\n"
    ),
    "aruba_aoss": (
        'hostname "s1"\nvlan 10\n   name "users"\n   untagged 1\n   ip address 192.0.2.1 255.255.255.0\n'
        "   exit\nip route 0.0.0.0 0.0.0.0 192.0.2.254\n"
    ),
    "cisco_iosxr": (
        "hostname x1\ninterface GigabitEthernet0/0/0/0.10\n encapsulation dot1q 10\n"
        " ipv4 address 192.0.2.1 255.255.255.0\nrouter static\n address-family ipv4 unicast\n"
        "  0.0.0.0/0 192.0.2.254\nend\n"
    ),
}
#: What the parser makes of ``AFTER``, read by hand: the accounts, the
#: VLAN ids, the interface addresses and the routes' destinations.
AFTER_HOLDS = ([], [10], ["192.0.2.1"], ["0.0.0.0/0"])
#: The same with VLAN 3999 too: the line after a banner that ends on its
#: own line is configuration.
WITH_3999 = ([], [10, 3999], ["192.0.2.1"], ["0.0.0.0/0"])
#: A line that declares VLAN 3999 in each grammar (OS10 makes a VLAN of
#: its interface).
VLAN_3999 = {
    "cisco_iosxe_cli": "vlan 3999\n",
    "cisco_nxos": "vlan 3999\n",
    "aruba_aoscx": "vlan 3999\n",
    "dell_os10": "interface vlan3999\n",
    "aruba_aoss": "vlan 3999\n   exit\n",
    "cisco_iosxr": "interface Bundle-Ether1.3999\n encapsulation dot1q 3999\n",
}
#: A privilege-15 account line in each grammar.
ACCOUNT = {
    "cisco_iosxe_cli": "username intruder privilege 15 secret 0 x",
    "cisco_nxos": "username intruder password 0 x role network-admin",
    "aruba_aoscx": "user intruder group administrators password plaintext x",
    "dell_os10": "username intruder password x role sysadmin",
    "aruba_aoss": 'password manager user-name "intruder" plaintext "x"',
    "cisco_iosxr": "username intruder\n group root-lr\n secret 0 x",
}

#: A banner in each grammar whose body holds an account with privilege
#: 15, a hostname, a VLAN, an interface with an address, a route and an
#: ACL (a Tier-3 row), as each platform writes them.  Each word of them
#: is in ``BANNER_WORDS``.  The AOS-S one is typed with ``%`` (a pasted
#: script): a printed AOS-S banner is a quoted string, and the account
#: line's own quotes would end it.
BANNER = {
    "cisco_iosxe_cli": (
        "banner motd ^C\nhostname from-the-banner\nusername intruder privilege 15 secret 0 from-the-banner\n"
        "vlan 3999\ninterface GigabitEthernet9\n ip address 198.51.100.66 255.255.255.0\n"
        "ip route 203.0.113.0 255.255.255.0 198.51.100.1\nip access-list extended FROM_BANNER\n^C\n!\n"
    ),
    "cisco_nxos": (
        "banner motd #\nhostname from-the-banner\nusername intruder password 0 from-the-banner role network-admin\n"
        "vlan 3999\ninterface Ethernet1/9\n  no switchport\n  ip address 198.51.100.66/24\n"
        "ip route 203.0.113.0/24 198.51.100.1\nip access-list FROM_BANNER\n#\n"
    ),
    "aruba_aoscx": (
        "banner motd !\nhostname from-the-banner\n"
        "user intruder group administrators password plaintext from-the-banner\n"
        "vlan 3999\ninterface 1/1/9\n    routing\n    ip address 198.51.100.66/24\n"
        "ip route 203.0.113.0/24 198.51.100.1\naccess-list ip FROM_BANNER\n!\n"
    ),
    "dell_os10": (
        "banner motd ^C\nhostname from-the-banner\nusername intruder password from-the-banner role sysadmin\n"
        "interface vlan3999\n ip address 198.51.100.66/24\nip route 203.0.113.0/24 198.51.100.1\n"
        "ip access-list FROM_BANNER\n^C\n"
    ),
    "aruba_aoss": (
        'banner motd %\npassword manager user-name "intruder" plaintext "from-the-banner"\n'
        'vlan 3999\n   name "from-the-banner"\n   ip address 198.51.100.66 255.255.255.0\n   exit\n'
        "ip route 203.0.113.0 255.255.255.0 198.51.100.1\n"
        'ip access-list extended "FROM_BANNER"\n%\n'
    ),
    "cisco_iosxr": (
        "banner motd ;\nhostname from-the-banner\nusername intruder\n group root-lr\n"
        " secret 0 from-the-banner\nvrf FROM_BANNER\ninterface GigabitEthernet0/0/0/9.3999\n"
        " encapsulation dot1q 3999\n ipv4 address 198.51.100.66 255.255.255.0\nrouter static\n"
        " address-family ipv4 unicast\n  203.0.113.0/24 198.51.100.1\nipv4 access-list FROM_BANNER\n;\n"
    ),
}
#: The rows each parser gives the banner above: IOS XR's says it is not
#: translated, and how many lines it took; the others give none.
BANNER_ROWS = {"cisco_iosxr": ["banner motd (14 lines, from line 3)"]}
BANNER_WORDS = ("intruder", "3999", "198.51.100.66", "203.0.113", "FROM_BANNER", "from-the-banner")


def _with_banner(codec: str) -> str:
    return HEAD[codec] + BANNER[codec] + AFTER[codec]


def _without_banner(codec: str) -> str:
    return HEAD[codec] + AFTER[codec]


def _holds(codec: str, text: str) -> tuple:
    tree = _parse(codec, text)
    return (
        sorted(u.name for u in tree.local_users),
        sorted(v.id for v in tree.vlans),
        sorted(a.ip for i in tree.interfaces for a in i.ipv4_addresses),
        sorted(r.destination for r in tree.static_routes),
    )


def test_each_config_without_its_banner_holds_what_is_typed_beside_it() -> None:
    for codec in CODECS:
        assert _holds(codec, _without_banner(codec)) == AFTER_HOLDS, codec


# ---------------------------------------------------------------------------
# (a) A banner's lines make no record, and no target writes them
# ---------------------------------------------------------------------------


def _check_banner_tree(codec: str) -> None:
    tree = _parse(codec, _with_banner(codec))
    bare = _parse(codec, _without_banner(codec))
    assert _holds(codec, _with_banner(codec)) == AFTER_HOLDS, codec
    assert tree.dropped_tier3_sections == BANNER_ROWS.get(codec, []), codec
    assert bare.dropped_tier3_sections == [], codec
    assert tree.hostname == {
        "cisco_iosxe_cli": "r1", "cisco_nxos": "n1", "aruba_aoscx": "c1", "dell_os10": "d1", "aruba_aoss": "s1",
        "cisco_iosxr": "x1",
    }[codec]
    # Every line after the banner is read as it is without it.
    assert tree.model_dump(exclude={"dropped_tier3_sections"}) == bare.model_dump(
        exclude={"dropped_tier3_sections"},
    ), codec


@pytest.mark.parametrize("codec", CODECS)
def test_a_banners_lines_make_no_record(codec: str) -> None:
    _check_banner_tree(codec)


def _check_banner_outputs(codec: str) -> None:
    source = get_codec(codec)
    for target in list_public_codecs():
        job = run_plan_with_checked_names(source, get_codec(target), _with_banner(codec), port_rename_map={})
        bare = run_plan_with_checked_names(source, get_codec(target), _without_banner(codec), port_rename_map={})
        assert job.rendered, (codec, target, job.error)
        assert [w for w in BANNER_WORDS if w.lower() in job.rendered.lower()] == [], (codec, target)
        # The banner is not translated, and changes nothing that is.
        assert (job.status, job.rendered, job.warnings) == (bare.status, bare.rendered, bare.warnings), target
        assert job.dropped_tier3_sections == BANNER_ROWS.get(codec, []), target
        # And the target's own parser finds no account, VLAN or route of
        # the banner's in what was written.
        read_back = get_codec(target).parse(job.rendered)
        assert "intruder" not in [u.name for u in read_back.local_users], (codec, target)
        assert 3999 not in [v.id for v in read_back.vlans], (codec, target)
        assert not [r for r in read_back.static_routes if r.destination.startswith("203.0.113.")], (codec, target)


@pytest.mark.parametrize("codec", CODECS)
def test_no_target_writes_a_banners_words(codec: str) -> None:
    """Read as lines of the config, the banner above was an account with
    privilege 15, a VLAN, an interface with an address and a route in
    the output of every target.  The OUTPUT of every public codec is
    read as text for each of the banner's words, and with the target's
    own parser."""
    _check_banner_outputs(codec)


@pytest.mark.parametrize("codec", CODECS)
def test_detection_reads_the_text_as_it_came_and_names_the_source(codec: str) -> None:
    """The probes read the paste as it came (a banner can only add to
    the score of a text that is the codec's own): each config with its
    banner is still detected as its own platform."""
    ranked = detect_codec(_with_banner(codec), min_confidence=40)
    assert ranked and ranked[0].codec == codec, codec


# ---------------------------------------------------------------------------
# (b) Each form, as the vendor prints it, and what the device holds
# ---------------------------------------------------------------------------

#: Per codec: a form, and what the parser makes of ``HEAD + form +
#: AFTER`` -- read by hand.  A body below holds a line that declares a
#: VLAN (3997, 3998) or an account: read as configuration, it would be
#: in the holds.  Where the holds have VLAN 3999, the banner ended on
#: the line it is written to end on, and the line after it is read.
FORMS: dict[str, dict[str, tuple[str, tuple]]] = {
    "cisco_iosxe_cli": {
        # As IOS-XE prints it (racc captures): the closing ^C alone.
        "banner motd, its closing ^C alone on a line": (
            "banner motd ^C\nusername intruder privilege 15 secret 0 x\nvlan 3998\n^C\nvlan 3999\n", WITH_3999,
        ),
        # As IOSv prints it (batfish / cml captures): the closing ^C
        # after the text on the body's last line, and the next banner
        # straight after it.
        "three banners, each ^C after the text of its last line": (
            "banner exec ^C\nvlan 3996\n*****^C\nbanner incoming ^C\nvlan 3997\n*****^C\n"
            "banner login ^C\nvlan 3998\n*****^C\nvlan 3999\n",
            WITH_3999,
        ),
        "a banner on one line": ("banner login ^CAuthorised access only^C\nvlan 3999\n", WITH_3999),
        # "Characters after the ending delimiter are discarded."
        "what follows the closing delimiter on its line": (
            "banner motd ^C\nvlan 3998\n^C vlan 3997\nvlan 3999\n", WITH_3999,
        ),
        # The printed delimiter is the two characters ^C: a caret alone
        # in the body is text.
        "a caret alone in the body": (
            "banner motd ^C\n ^ ^ ^\nvlan 3998\n^ username intruder privilege 15 secret 0 x\n^C\nvlan 3999\n",
            WITH_3999,
        ),
        "a typed delimiter": ("banner motd #\nvlan 3998\n#\nvlan 3999\n", WITH_3999),
        "a delimiter compared by its case": ("banner motd x\nX\nvlan 3998\nx\nvlan 3999\n", WITH_3999),
        "the byte 0x03 as the delimiter": ("banner motd \x03\nvlan 3998\n\x03\nvlan 3999\n", WITH_3999),
        "banner with no type (a MOTD banner)": ("banner #\nvlan 3998\n#\nvlan 3999\n", WITH_3999),
        "prompt-timeout, slip-ppp and config-save": (
            "banner prompt-timeout ^C\nvlan 3996\n^C\nbanner slip-ppp ^C\nvlan 3997\n^C\n"
            "banner config-save ^C\nvlan 3998\n^C\nvlan 3999\n",
            WITH_3999,
        ),
        "aaa authentication banner and fail-message": (
            "aaa authentication banner *Unauthorized Access Prohibited*\n"
            "aaa authentication fail-message ^C\nvlan 3998\n^C\nvlan 3999\n",
            WITH_3999,
        ),
        "a menu's title and prompt": (
            "menu NEW title ^C\nvlan 3997\n^C\nmenu NEW prompt ^C\nvlan 3998\n^C\nmenu NEW text 1 Telnet\n"
            "vlan 3999\n",
            WITH_3999,
        ),
        # O'Reilly's Cisco IOS in a Nutshell: `busy-message host d text d`.
        "a busy message": ("busy-message host1 ^C\nvlan 3998\n^C\nvlan 3999\n", WITH_3999),
        "a line's vacant and refuse messages": (
            "line vty 0 4\n vacant-message ^C\nvlan 3997\n^C\n refuse-message & line in use &\n"
            " transport input ssh\n!\nvlan 3999\n",
            WITH_3999,
        ),
        # A text whose indentation was lost: neither is a command of the
        # top level.
        "a line's vacant and refuse messages, in column 0": (
            "line vty 0 4\nvacant-message ^C\nvlan 3997\n^C\nrefuse-message ^C\nvlan 3998\n^C\n!\nvlan 3999\n",
            WITH_3999,
        ),
        # Printed with a caret and the TYPED character: `^c` is a caret.
        "a web authentication banner": (
            "parameter-map type webauth global\n banner text ^c login page banner ^c\n banner title ^C\n"
            "vlan 3998\n^C\n!\nvlan 3999\n",
            WITH_3999,
        ),
        # In column 0, `text` and `title` after `banner` are still those
        # words, never a delimiter.
        "a web authentication banner, in column 0": (
            "parameter-map type webauth global\nbanner text ^c\nvlan 3997\n^c\nbanner title ^C\n"
            "vlan 3998\n^C\n!\nvlan 3999\n",
            WITH_3999,
        ),
        "a macro, to its @ line": (
            "macro name EGRESS\nmls qos trust dscp\nusername intruder privilege 15 secret 0 x\nvlan 3998\n@\n"
            "vlan 3999\n",
            WITH_3999,
        ),
        # Only a line that is `@` ends it.
        "a macro whose lines hold an @": (
            "macro name EGRESS\ndescription noc@example.net\n@ the end\nvlan 3998\n@\nvlan 3999\n", WITH_3999,
        ),
        "lines that open nothing": (
            "no banner exec\nbanner motd\nbanner text\nline vty 0 4\n vacant-message\n exec-banner\n motd-banner\n"
            "!\nvlan 3999\n",
            WITH_3999,
        ),
        # Only a body opened with what a device writes (^C, the byte 3)
        # leaves that behind when its text holds it.
        "^C in a line outside a banner a device printed": (
            "snmp-server contact Press ^C to stop\nbanner motd #\nvlan 3998\n#\nsnmp-server location ^C\n"
            "vlan 3999\n",
            WITH_3999,
        ),
        # The shape check reads the text with the banner's lines empty.
        "a banner whose text begins as JSON does": (
            "banner motd ^C\n{ authorised access only }\n^C\nvlan 3999\n", WITH_3999,
        ),
    },
    "cisco_nxos": {
        "banner motd, its closing delimiter alone on a line": (
            "banner motd #\nusername intruder password 0 x role network-admin\nvlan 3998\n#\nvlan 3999\n",
            WITH_3999,
        ),
        "a banner on one line": ("banner motd #Welcome to the Switch#\nvlan 3999\n", WITH_3999),
        # Cisco's NX-API page: `banner exec 123:12` is the message `23:`.
        "a banner on one line, and what follows its end": ("banner exec 123:12\nvlan 3999\n", WITH_3999),
        "the closing delimiter after text, and text after it": (
            "banner exec %\nvlan 3998\nend of banner% vlan 3997\nvlan 3999\n", WITH_3999,
        ),
        "a delimiter compared by its case": ("banner motd x\nX\nvlan 3998\nx\nvlan 3999\n", WITH_3999),
        # As 9.2(2) prints a job: its commands in column 0.
        "a scheduler job, to its end-job line": (
            "scheduler job name personalitybck\nusername intruder password 0 x role network-admin\n"
            "vlan 3998\n \nend-job\nvlan 3999\n",
            WITH_3999,
        ),
        # Only a line that is `end-job`, in column 0, ends it.
        "a scheduler job whose lines hold end-job otherwise": (
            "scheduler job name J\n  end-job\nend-jobs\nend-job now\nvlan 3998\nend-job\nvlan 3999\n", WITH_3999,
        ),
        "lines that open nothing": ("no banner motd\nbanner exec\nvlan 3999\n", WITH_3999),
        "a banner whose text begins as JSON does": (
            "banner motd #\n{ authorised access only }\n#\nvlan 3999\n", WITH_3999,
        ),
    },
    "aruba_aoscx": {
        "banner motd, its closing ! alone on a line": (
            "banner motd !\nuser intruder group administrators password plaintext x\nvlan 3998\n!\nvlan 3999\n",
            WITH_3999,
        ),
        # Printed so when the text ended where the delimiter was typed.
        "the closing ! at the end of the last line": (
            "banner exec !\nvlan 3998\nAccess prohibited!\nvlan 3999\n", WITH_3999,
        ),
        # The switch prints the stored text, then the character: one with
        # text after it on its line is the text's own.
        "the delimiter with text after it, in the text": (
            "banner motd !\nWARNING! Authorised access only\nvlan 3998 ! here\nvlan 3997\n!\nvlan 3999\n",
            WITH_3999,
        ),
        "another delimiter": ("banner motd $\nvlan 3998\n$\nvlan 3999\n", WITH_3999),
        "a delimiter compared by its case": ("banner motd x\nX\nvlan 3998\nx\nvlan 3999\n", WITH_3999),
        "an empty banner": ("banner motd !\n!\nvlan 3999\n", WITH_3999),
        "white space after the delimiter": ("banner exec ! \nvlan 3998\n!  \nvlan 3999\n", WITH_3999),
        "lines that open nothing": ("no banner motd\nbanner exec\nvlan 3999\n", WITH_3999),
        "a banner whose text begins as JSON does": (
            "banner motd !\n{ authorised access only }\n!\nvlan 3999\n", WITH_3999,
        ),
    },
    "dell_os10": {
        # As Dell prints it: ^C, the two characters.
        "banner motd, its ^C alone on a line": (
            "banner motd ^C\nusername intruder password x role sysadmin\ninterface vlan3998\n^C\n"
            "interface vlan3999\n",
            WITH_3999,
        ),
        "banner login with another delimiter": (
            "banner login ^\ninterface vlan3998\n^\ninterface vlan3999\n", WITH_3999,
        ),
        # Dell: "a line that contains only the delimiter character".
        "the delimiter inside a line": (
            "banner motd ^C\nsee ^C here\ninterface vlan3998\n^C\ninterface vlan3999\n", WITH_3999,
        ),
        "the delimiter with white space in front of it": (
            "banner motd ^C\n ^C\ninterface vlan3998\n^C\ninterface vlan3999\n", WITH_3999,
        ),
        "white space after the delimiter": (
            "banner motd ^C \ninterface vlan3998\n^C  \ninterface vlan3999\n", WITH_3999,
        ),
        # `!` is OS10's comment mark: a line of it after a banner it
        # delimits is not taken for that banner's end left behind.
        "a line that is ! after a banner delimited by it": (
            "banner motd !\ninterface vlan3998\n!\n!\ninterface vlan3999\n", WITH_3999,
        ),
        "lines that open nothing": (
            "banner motd disable\nbanner login disable\nno banner motd\nbanner login\ninterface vlan3999\n",
            WITH_3999,
        ),
        "a banner whose text begins as JSON does": (
            "banner motd ^C\n{ authorised access only }\n^C\ninterface vlan3999\n", WITH_3999,
        ),
    },
    "aruba_aoss": {
        "the one-line form": ('banner motd "Authorized use only."\nvlan 3999\n   exit\n', WITH_3999),
        # HPE's K.11.00 figure: the closing quote at the end of the text.
        "several lines, the closing quote after the text": (
            'banner motd "    This is a private system maintained by the\nvlan 3998\n'
            "   ip address 198.51.100.66 255.255.255.0\n   exit\n"
            '      civil and criminal penalties!"\nvlan 3999\n   exit\n',
            WITH_3999,
        ),
        # R.11.121: the closing quote alone on its line.
        "several lines, the closing quote alone": (
            'banner motd "     ***Authorized access only!***\nvlan 3998\n   exit\n"\nvlan 3999\n   exit\n',
            WITH_3999,
        ),
        # 16.x prints the escapes as typed: \" is the text's own quote.
        "escapes": (
            'banner motd "use the \\\'banner motd\\\' command, \\"quoted\\", and a backslash \\\\\n'
            'vlan 3998\n   exit\nescape characters."\nvlan 3999\n   exit\n',
            WITH_3999,
        ),
        # A backslash at the end of a line takes the line end with it,
        # and nothing of the next line.
        "a backslash at the end of a line": ('banner motd "first line\\\n"\nvlan 3999\n   exit\n', WITH_3999),
        "escapes for line ends on one line": (
            'banner motd "line one\\n\\n\\tline two"\nvlan 3999\n   exit\n', WITH_3999,
        ),
        "banner exec": ('banner exec "Welcome\nvlan 3998\n   exit\n"\nvlan 3999\n   exit\n', WITH_3999),
        # A banner typed in a pasted script, with another delimiter.
        "the typed form": (
            'banner motd %\npassword manager user-name "intruder" plaintext "x"\nvlan 3998\n   exit\n'
            "end of text% vlan 3997\nvlan 3999\n   exit\n",
            WITH_3999,
        ),
        "the typed form on one line": ("banner motd %Welcome%\nvlan 3999\n   exit\n", WITH_3999),
        # After a printed banner, a quote a backslash escapes is no
        # quote: this line holds two.
        "an escaped quote in a line after a banner": (
            'banner motd "Welcome"\nsnmp-server contact "a \\" b"\nvlan 3999\n   exit\n', WITH_3999,
        ),
        # Before any printed banner, an odd number of quotes is no end of
        # a banner's.
        "an odd number of quotes before any banner": (
            'snmp-server contact "a\nvlan 3999\n   exit\n', WITH_3999,
        ),
        "lines that open nothing": ("no banner motd\nbanner motd\nvlan 3999\n   exit\n", WITH_3999),
        "a banner whose text begins as JSON does": (
            'banner motd "\n{ authorised access only }\n"\nvlan 3999\n   exit\n', WITH_3999,
        ),
    },
    "cisco_iosxr": {
        # Printed so by 6.4.1 (`;`), 7.11.2 (`#`) and 7.10.1 (`/`): the
        # opener alone, the text, the delimiter alone.
        "a semicolon alone on the lines that open and end it": (
            "banner motd ;\n" + ACCOUNT["cisco_iosxr"] + "\n" + "vrf X\n;\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        "a hash alone on the lines that open and end it": (
            "banner login #\n" + ACCOUNT["cisco_iosxr"] + "\n#\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        "a slash alone on the lines that open and end it": (
            "banner exec /\n" + ACCOUNT["cisco_iosxr"] + "\n/\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # 5.2.1 (Batfish's capture): a caret, and the text's first line empty.
        "a caret, the first line of the text empty": (
            "banner login ^\n\n" + ACCOUNT["cisco_iosxr"] + "\n^\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # 6.1.3 (XRv): `^C` on the opener, the closing `^C` after the text
        # of the last line.
        "^C, the end after the text of the last line": (
            "banner motd ^C\n" + ACCOUNT["cisco_iosxr"] + "\nthe end^C\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # 7.3.2 (DevNet): `^c`, the closing line `^c` and eight spaces.
        "^c, the closing line with spaces after it": (
            "banner motd ^c\n" + ACCOUNT["cisco_iosxr"] + "\n^c        \n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # A caret alone and the two on one line: read as one character or
        # as two, the delimiter ends the banner on that line.
        "^C, a caret alone and the end on one line": (
            "banner motd ^C\n" + ACCOUNT["cisco_iosxr"] + "\na ^ b^C\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        "^C on one line, a caret alone before its end": (
            "banner motd ^Ca ^ b^C\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # 7.3.2 (DevNet): the text begins on the opener line, and the
        # closing quote ends the last line of it.
        "text on the line that opens it, the end after the text of the last line": (
            'banner motd "Welcome\n' + ACCOUNT["cisco_iosxr"] + '\nbye"\n' + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # Two printed corpus lines: the closer at the start of a line,
        # more text after it.
        "the end at the start of a line, with more after it": (
            "banner motd ;\n" + ACCOUNT["cisco_iosxr"] + "\n;and the rest\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # A line `!` or `end` in the text is text: only the delimiter ends it.
        "lines that are ! and end in the text": (
            "banner motd #\n!\nend\n" + ACCOUNT["cisco_iosxr"] + "\n#\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        "aaa banner login": (
            "aaa banner login ;\n" + ACCOUNT["cisco_iosxr"] + "\n;\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # 6.5.1: two banners with an empty text, each on one line.
        "two banners on one line each, their texts empty": (
            "banner motd cc\nbanner login cc\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # 7.8.1: one line, two spaces after its end.
        "a banner on one line, spaces after its end": (
            'banner motd "Authorised access only"  \n' + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # 7.8.1: one line, text after its end.
        "a banner on one line, text after its end": (
            "banner exec DHello. Dthe rest of it\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        # The keyword and the type in another letter case; the delimiter
        # is compared by its own, so a line `C` is text.
        "a delimiter compared by its case": (
            "BANNER MOTD c\nC\nusername intruder\n group root-lr\nc\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        "lines that open nothing": (
            "service sysadmin-login-banner disable\nhostname banner\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
        "a banner whose text begins as JSON does": (
            "banner motd ;\n{ authorised access only }\n;\n" + VLAN_3999["cisco_iosxr"], WITH_3999,
        ),
    },
}
#: The forms whose lines are configuration either way: read as lines,
#: they make the same records.
_HIDES_NOTHING = {
    "lines that open nothing", "a banner on one line", "a banner on one line, and what follows its end",
    "the one-line form", "the typed form on one line", "escapes for line ends on one line", "an empty banner",
    "a backslash at the end of a line", "an escaped quote in a line after a banner",
    "an odd number of quotes before any banner", "two banners on one line each, their texts empty",
    "a banner on one line, spaces after its end", "a banner on one line, text after its end",
    "^C on one line, a caret alone before its end",
}
FORM_IDS = [(codec, name) for codec in CODECS for name in FORMS[codec]]


def _form_text(codec: str, name: str) -> str:
    return HEAD[codec] + FORMS[codec][name][0] + AFTER[codec]


def _check_form(codec: str, name: str) -> None:
    assert _holds(codec, _form_text(codec, name)) == FORMS[codec][name][1], (codec, name)


@pytest.mark.parametrize(("codec", "name"), FORM_IDS, ids=[f"{c}: {n}" for c, n in FORM_IDS])
def test_each_form_holds_what_is_typed_beside_it(codec: str, name: str) -> None:
    _check_form(codec, name)


#: IOS XR: banners of three kinds, one of them twice, and what the rows
#: say -- each kind once, its lines counted, from where its first begins.
_XR_KINDS = (
    "banner motd ;\nhello\n;\nbanner login cc\naaa banner login #\none\ntwo\n#\n"
    "banner motd /\nbye/\n"
)
_XR_KINDS_ROWS = [
    "banner motd (5 lines, from line 3)", "banner login (1 line, from line 6)",
    "aaa banner login (4 lines, from line 7)",
]


def _check_xr_rows() -> None:
    text = HEAD["cisco_iosxr"] + _XR_KINDS + AFTER["cisco_iosxr"]
    assert _holds("cisco_iosxr", text) == AFTER_HOLDS
    assert _parse("cisco_iosxr", text).dropped_tier3_sections == _XR_KINDS_ROWS


def test_ios_xr_says_each_kind_of_banner_and_its_lines() -> None:
    """A banner is not translated: each kind is a row, which quotes
    nothing of the text and counts its lines."""
    _check_xr_rows()


def test_ios_xr_a_banner_printed_with_no_end_of_its_own() -> None:
    """Cisco's xrdocs.io shows a banner set through NETCONF printed as
    ``banner login ! <text>``, with no second ``!``.  Its text runs on
    to the next ``!``, and the lines before it are taken for its text:
    the safe side (the account under it is not read, and no line of a
    banner is), and the row says how many lines it took.  A known
    limitation, written here as it stands."""
    text = (
        HEAD["cisco_iosxr"] + "banner login ! Unauthorised access to this device is restricted.\n"
        + "username admin\n group root-lr\n!\n" + AFTER["cisco_iosxr"]
    )
    tree = _parse("cisco_iosxr", text)
    assert _holds("cisco_iosxr", text) == AFTER_HOLDS
    assert tree.dropped_tier3_sections == ["banner login (4 lines, from line 3)"]


def test_a_banner_at_the_end_with_no_line_end_after_it() -> None:
    """The committed OS10 capture's last line is its banner's closing
    delimiter, with no line end."""
    text = HEAD["dell_os10"] + AFTER["dell_os10"] + "banner login ^\ninterface vlan3998\n^"
    assert _holds("dell_os10", text) == AFTER_HOLDS


#: The release on AOS-S's config-editor line, and a banner whose line
#: says another: the release is the config's, never the banner's.
_RELEASE_IN_A_BANNER = 'banner motd "Created on release #XX.16.01.0001\nWelcome\n"\n'


def _check_the_release() -> None:
    assert _parse("aruba_aoss", _RELEASE_IN_A_BANNER + AFTER["aruba_aoss"]).source_version == ""
    assert _parse(
        "aruba_aoss", HEAD["aruba_aoss"] + _RELEASE_IN_A_BANNER + AFTER["aruba_aoss"],
    ).source_version == "WC.16.10.0001"


def test_the_line_that_opens_a_banner_is_read_by_no_reader() -> None:
    """The release pattern is not anchored to a line's start, so a line
    that opens a banner and goes on with its text is the one it would
    read."""
    _check_the_release()


# ---------------------------------------------------------------------------
# (c) Each refusal, with its sentence
# ---------------------------------------------------------------------------

#: A text that is refused, the sentence, the numbers it names (``line``:
#: the line refused, which ``path`` names too; ``opened``: the line of
#: the banner whose text held its end) and the delimiter its banner uses
#: (which the sentence must not hold).
REFUSED: dict[str, tuple[str, str, str, dict[str, int], str]] = {
    "cisco_iosxe_cli: a banner with no end": (
        "cisco_iosxe_cli", HEAD["cisco_iosxe_cli"] + "banner motd ^C\nvlan 3998\n" + AFTER["cisco_iosxe_cli"],
        ios_parse.UNENDED_BODY_MESSAGE, {"line": 4}, "^C",
    ),
    "cisco_iosxe_cli: a typed banner with no end": (
        "cisco_iosxe_cli", HEAD["cisco_iosxe_cli"] + "banner exec %\nvlan 3998\n" + AFTER["cisco_iosxe_cli"],
        ios_parse.UNENDED_BODY_MESSAGE, {"line": 4}, "%",
    ),
    "cisco_iosxe_cli: a macro with no @": (
        "cisco_iosxe_cli", HEAD["cisco_iosxe_cli"] + "macro name EGRESS\nvlan 3998\n" + AFTER["cisco_iosxe_cli"],
        ios_parse.UNENDED_BODY_MESSAGE, {"line": 4}, "%",
    ),
    # A banner typed with `#` whose text holds `^C`: printed between two
    # ^C, it ends at its own, and the ^C the device printed is left on a
    # line outside it.
    "cisco_iosxe_cli: the text of a banner holds its printed end": (
        "cisco_iosxe_cli", HEAD["cisco_iosxe_cli"] + "banner motd ^C\nPress ^C to abort\n" + ACCOUNT["cisco_iosxe_cli"]
        + "\nvlan 3998\n^C\n" + AFTER["cisco_iosxe_cli"],
        ios_parse.ORPHAN_MESSAGE, {"line": 8, "opened": 4}, "^C",
    ),
    # The same, the text's last line indented: the ^C the device printed
    # is at the end of that line.
    "cisco_iosxe_cli: the text of a banner holds its printed end, its last line indented": (
        "cisco_iosxe_cli", HEAD["cisco_iosxe_cli"] + "banner motd ^C\nPress ^C to abort\n" + ACCOUNT["cisco_iosxe_cli"]
        + "\n   the end^C\n" + AFTER["cisco_iosxe_cli"],
        ios_parse.ORPHAN_MESSAGE, {"line": 7, "opened": 4}, "^C",
    ),
    "cisco_nxos: a banner with no end": (
        "cisco_nxos", HEAD["cisco_nxos"] + "banner motd #\nvlan 3998\n" + AFTER["cisco_nxos"],
        nxos_parse.UNENDED_BODY_MESSAGE, {"line": 4}, "#",
    ),
    "cisco_nxos: a scheduler job with no end-job": (
        "cisco_nxos", HEAD["cisco_nxos"] + "scheduler job name backup\nvlan 3998\n" + AFTER["cisco_nxos"],
        nxos_parse.UNENDED_BODY_MESSAGE, {"line": 4}, "#",
    ),
    "aruba_aoscx: a banner with no end": (
        "aruba_aoscx", HEAD["aruba_aoscx"] + "banner motd !\nvlan 3998\n" + AFTER["aruba_aoscx"],
        aoscx_parse.UNENDED_BODY_MESSAGE, {"line": 3}, "!",
    ),
    # A typed text with more after its end: the end is the text's, and
    # the banner runs on, here to the end of the text.
    "aruba_aoscx: a banner whose delimiter has text after it, and no other": (
        "aruba_aoscx", HEAD["aruba_aoscx"] + "banner motd !\nWARNING! Authorised access only\nvlan 3998\n"
        + AFTER["aruba_aoscx"],
        aoscx_parse.UNENDED_BODY_MESSAGE, {"line": 3}, "!",
    ),
    "aruba_aoscx: more than one character on the line that opens it": (
        "aruba_aoscx", HEAD["aruba_aoscx"] + "banner motd !Welcome!\nvlan 3999\n" + AFTER["aruba_aoscx"],
        aoscx_parse.MORE_ON_THE_OPENER_MESSAGE, {"line": 3}, "!",
    ),
    "dell_os10: a banner with no end": (
        "dell_os10", HEAD["dell_os10"] + "banner motd ^C\ninterface vlan3998\n" + AFTER["dell_os10"],
        os10_parse.UNENDED_BODY_MESSAGE, {"line": 3}, "^C",
    ),
    # The delimiter in a line does not end it, nor does one indented.
    "dell_os10: a banner whose delimiter is only inside lines": (
        "dell_os10", HEAD["dell_os10"] + "banner motd ^C\nsee ^C here\n ^C\n" + AFTER["dell_os10"],
        os10_parse.UNENDED_BODY_MESSAGE, {"line": 3}, "^C",
    ),
    "dell_os10: more than the delimiter on the line that opens it": (
        "dell_os10", HEAD["dell_os10"] + "banner motd ^CWelcome^C\ninterface vlan3999\n" + AFTER["dell_os10"],
        os10_parse.MORE_ON_THE_OPENER_MESSAGE, {"line": 3}, "^C",
    ),
    # A banner typed with `%` whose text holds a line `^C`: printed with
    # ^C, it ends there, and the ^C line Dell printed is left behind.
    "dell_os10: a line of the text is the delimiter alone": (
        "dell_os10", HEAD["dell_os10"] + "banner motd ^C\nHello\n^C\n" + ACCOUNT["dell_os10"]
        + "\ninterface vlan3998\n^C\n" + AFTER["dell_os10"],
        os10_parse.ORPHAN_MESSAGE, {"line": 8, "opened": 3}, "^C",
    ),
    "aruba_aoss: a banner with no closing quote": (
        "aruba_aoss", HEAD["aruba_aoss"] + 'banner motd "good morning\nvlan 3998\n   exit\n',
        aoss_parse.UNENDED_BODY_MESSAGE, {"line": 2}, '"',
    ),
    "aruba_aoss: a typed banner with no end": (
        "aruba_aoss", HEAD["aruba_aoss"] + "banner motd %\nvlan 3998\n   exit\n",
        aoss_parse.UNENDED_BODY_MESSAGE, {"line": 2}, "%",
    ),
    # HPE's own listing whose banner never closes: the next quote is in
    # the line after it, with text after it.
    "aruba_aoss: text after the quote that ends it": (
        "aruba_aoss", HEAD["aruba_aoss"] + 'banner motd "good morning\ntacacs-server host 192.0.2.9 key "fake"\n'
        + AFTER["aruba_aoss"],
        aoss_parse.TEXT_AFTER_THE_END_MESSAGE, {"line": 3}, '"',
    ),
    "aruba_aoss: text after the quote on the line that opens it": (
        "aruba_aoss", HEAD["aruba_aoss"] + 'banner motd "Welcome" vlan 3999\n' + AFTER["aruba_aoss"],
        aoss_parse.TEXT_AFTER_THE_END_MESSAGE, {"line": 2}, '"',
    ),
    # A text with a line that is a quote: printed, the banner ends at
    # it, and the quote the switch printed after the text is left behind.
    "aruba_aoss: a line of the text is a double quote alone": (
        "aruba_aoss", HEAD["aruba_aoss"] + 'banner motd "Hello\n"\n' + ACCOUNT["aruba_aoss"]
        + '\nvlan 3998\n   exit\n"\n' + AFTER["aruba_aoss"],
        aoss_parse.ORPHAN_MESSAGE, {"line": 7, "opened": 2}, '"',
    ),
    # The same with a line of the text that ends in a quote.
    "aruba_aoss: a line of the text ends in a double quote": (
        "aruba_aoss", HEAD["aruba_aoss"] + 'banner motd "Welcome"\n' + ACCOUNT["aruba_aoss"]
        + '\nbye"\n' + AFTER["aruba_aoss"],
        aoss_parse.ORPHAN_MESSAGE, {"line": 4, "opened": 2}, '"',
    ),
    "cisco_iosxr: a banner with no end": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "banner motd ;\n" + ACCOUNT["cisco_iosxr"] + "\n" + AFTER["cisco_iosxr"],
        xr_parse.UNENDED_BODY_MESSAGE, {"line": 3}, ";",
    ),
    # Its text on the line that opens it, and no other `#`.
    "cisco_iosxr: a banner with no end, its text on the line that opens it": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "banner login # Welcome\nvrf X\n" + AFTER["cisco_iosxr"],
        xr_parse.UNENDED_BODY_MESSAGE, {"line": 3}, "#",
    ),
    # IOS's form: `banner` and a delimiter, with no type.
    "cisco_iosxr: a banner with no type": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "banner ^C\n" + ACCOUNT["cisco_iosxr"] + "\n^C\n" + AFTER["cisco_iosxr"],
        xr_parse.UNKNOWN_BANNER_MESSAGE, {"line": 3}, "^",
    ),
    "cisco_iosxr: a type IOS XR does not list": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "banner config-save ;\nvrf X\n;\n" + AFTER["cisco_iosxr"],
        xr_parse.UNKNOWN_BANNER_MESSAGE, {"line": 3}, ";",
    ),
    "cisco_iosxr: a banner with no text after its type": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "banner motd\nvrf X\n" + AFTER["cisco_iosxr"],
        xr_parse.UNKNOWN_BANNER_MESSAGE, {"line": 3}, ";",
    ),
    "cisco_iosxr: an aaa banner IOS XR does not list": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "aaa banner fail-message ;\nvrf X\n;\n" + AFTER["cisco_iosxr"],
        xr_parse.UNKNOWN_BANNER_MESSAGE, {"line": 3}, ";",
    ),
    # Printed with `^C`, a caret alone: read as one character the banner
    # ends there and the account after it is configuration; read as two
    # it runs on.
    "cisco_iosxr: a caret alone in a banner printed with ^C": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "banner motd ^C\nbye^\n" + ACCOUNT["cisco_iosxr"] + "\n^C\n"
        + AFTER["cisco_iosxr"],
        xr_parse.CARET_MESSAGE, {"line": 4}, "^",
    ),
    "cisco_iosxr: a caret alone on the line that opens a banner printed with ^c": (
        "cisco_iosxr", HEAD["cisco_iosxr"] + "banner motd ^cWelcome^\n" + ACCOUNT["cisco_iosxr"] + "\n^c\n"
        + AFTER["cisco_iosxr"],
        xr_parse.CARET_MESSAGE, {"line": 3}, "^",
    ),
}
#: The refusals of a body with no end, and of a text that holds its end.
UNENDED = [name for name, (codec, _, sentence, _, _) in REFUSED.items()
           if sentence is MODULES[codec][0].UNENDED_BODY_MESSAGE]
ORPHANS = {codec: [name for name, (c, _, sentence, _, _) in REFUSED.items()
                   if c == codec and sentence is getattr(MODULES[codec][0], "ORPHAN_MESSAGE", None)]
           for codec in ("cisco_iosxe_cli", "dell_os10", "aruba_aoss")}
#: Each word of the texts above that is the config's, not a sentence's.
_TEXT_WORDS = ("3998", "3999", "morning", "Welcome", "WARNING", "fake", "tacacs", "EGRESS", "backup",
               "intruder", "Press", "Hello", "bye")
_WORD = re.compile(r"[^\s`'\"()]+")


def _quotes_nothing(error: ParseError, sentence: str, delimiter: str) -> None:
    """*error* says *sentence* with numbers in it, and nothing else."""
    fixed = set(_WORD.findall(re.sub(r"\{\w+\}", "", sentence)))
    extra = set(_WORD.findall(str(error))) - fixed
    assert error.path.split()[-1] in extra and all(word.isdigit() for word in extra), extra
    assert error.snippet == ""
    assert delimiter not in str(error)
    assert [w for w in _TEXT_WORDS if w in str(error)] == []


def _check_refused(name: str) -> None:
    codec, text, sentence, numbers, delimiter = REFUSED[name]
    error = _refusal(codec, text)
    assert str(error) == sentence.format(**numbers), name
    assert error.path == f"line {numbers['line']}", name
    _quotes_nothing(error, sentence, delimiter)
    job = run_plan_with_checked_names(get_codec(codec), get_codec("juniper_junos"), text, port_rename_map={})
    assert (job.status.value, job.error) == ("failed", "parse failed: " + str(error)), name


@pytest.mark.parametrize("name", list(REFUSED))
def test_a_banner_that_cannot_be_told_from_the_config_is_refused(name: str) -> None:
    """Read as it stands, the rest of the config would be the banner's
    text, or where the banner ends cannot be told: refused in words,
    naming the line, quoting nothing of the text and no delimiter (the
    delimiter is the operator's), and the job says ``parse failed:``."""
    _check_refused(name)


def _line_end_sentence(codec: str) -> str:
    command = "show running-configuration" if codec == "dell_os10" else "show running-config"
    return _scanner.LINE_END_MESSAGE.format(codec=codec, command=command, line="{line}")


def test_the_sentences_name_no_delimiter_and_say_what_to_paste() -> None:
    sentences = [
        ios_parse.UNENDED_BODY_MESSAGE, ios_parse.ORPHAN_MESSAGE, nxos_parse.UNENDED_BODY_MESSAGE,
        aoscx_parse.UNENDED_BODY_MESSAGE, aoscx_parse.MORE_ON_THE_OPENER_MESSAGE,
        os10_parse.UNENDED_BODY_MESSAGE, os10_parse.MORE_ON_THE_OPENER_MESSAGE, os10_parse.ORPHAN_MESSAGE,
        aoss_parse.UNENDED_BODY_MESSAGE, aoss_parse.TEXT_AFTER_THE_END_MESSAGE, aoss_parse.ORPHAN_MESSAGE,
        xr_parse.UNENDED_BODY_MESSAGE, xr_parse.UNKNOWN_BANNER_MESSAGE, xr_parse.CARET_MESSAGE,
        *(_line_end_sentence(codec) for codec in (*CODECS, "arista_eos")),
    ]
    for sentence in sentences:
        assert sentence.count("{line}") >= 1, sentence
        assert "show running-config" in sentence or "remove the banner's lines" in sentence, sentence
        for mark in ("^", '"', "!", "#", "%", "$"):
            assert mark not in sentence, (mark, sentence)
    # IOS XR prints the delimiter that was typed: `;` and `/` among the
    # commonest.
    for sentence in (xr_parse.UNENDED_BODY_MESSAGE, xr_parse.UNKNOWN_BANNER_MESSAGE, xr_parse.CARET_MESSAGE):
        assert ";" not in sentence and "/" not in sentence, sentence
    # Each sentence for a text that holds its end names the banner's line.
    for sentence in (ios_parse.ORPHAN_MESSAGE, os10_parse.ORPHAN_MESSAGE, aoss_parse.ORPHAN_MESSAGE):
        assert "{opened}" in sentence, sentence


# ---------------------------------------------------------------------------
# (d) Every committed input of the seven, as it was
# ---------------------------------------------------------------------------

#: The committed inputs of each parser.
_DIRS = {
    "aruba_aoscx": ("real/aruba_aoscx", "synthetic/aruba_aoscx"),
    "aruba_aoss": ("real/aruba_aoss", "synthetic/aruba_aoss", "aruba_aoss"),
    "cisco_iosxe_cli": ("real/cisco_iosxe", "synthetic/cisco_iosxe_cli", "iosxe"),
    "cisco_nxos": ("real/cisco_nxos", "synthetic/cisco_nxos"),
    "dell_os10": ("real/dell_os10", "synthetic/dell_os10"),
    "arista_eos": ("real/arista_eos", "synthetic/arista_eos"),
    "cisco_iosxr": ("real/cisco_iosxr", "synthetic/cisco_iosxr"),
}
_NOT_A_CAPTURE = {".md", ".py", ".pyc", ".xml", ".json", ".yaml", ".yml"}


def _committed() -> list[tuple[str, str]]:
    """``(codec, path under tests/fixtures)`` for every committed input."""
    found = []
    for codec, dirs in _DIRS.items():
        for name in dirs:
            for path in sorted((FIXTURES / name).iterdir()):
                if path.is_file() and path.suffix.lower() not in _NOT_A_CAPTURE:
                    found.append((codec, path.relative_to(FIXTURES).as_posix()))
    return found


COMMITTED = _committed()


def _read(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8", errors="replace")


def _digest(codec: str, path: str) -> str:
    """The tree of *path*, as a digest (its fields at their defaults left
    out, so that a new canonical field moves nothing here)."""
    tree = _parse(codec, _read(path)).model_dump(mode="json", exclude_defaults=True)
    return hashlib.sha256(json.dumps(tree, sort_keys=True).encode("utf-8")).hexdigest()[:12]


#: What :func:`_digest` gave for each committed input on the code as it
#: was before a banner was read as text (``8210c697``; IOS XR's on
#: ``efda1659``, before its parser read one).  A value changes
#: only when a parser's reading of that input is changed on purpose; the
#: failing assertion prints the new one.  Moved on purpose: every IOS XR
#: and OS10 input that states an ``mtu``, when the tree's MTU became the
#: payload (``MTU_BEYOND_THE_PAYLOAD`` in ``codecs/_helpers.py``); every
#: input that states an IP MTU apart from its MTU, and every AOS-CX input
#: that raises the MTU of an IPv4 interface and leaves its IP MTU at 1500,
#: when the tree gained an IP MTU of its own
#: (``CanonicalInterface.ip_mtu``).
BEFORE: dict[str, str] = {
    "real/aruba_aoscx/aoscx_dcn_arch3_ebgp_leaf1a.cfg": "ce2d0d8a21e9",
    "real/aruba_aoscx/aoscx_dcn_arch3_ibgp_leaf1a.cfg": "c04121960505",
    "real/aruba_aoscx/aoscx_dcn_arch4_core1_1.cfg": "ed95de985915",
    "real/aruba_aoscx/aoscx_dcn_arch4_core1_2.cfg": "272c7cdc2be8",
    "real/aruba_aoscx/canu_csm17_spine001_ipv6_vrf.cfg": "46ec779d1ff1",
    "real/aruba_aoscx/netutils_aoscx_snmpv3_glcx1009.cfg": "23ea36b661bf",
    "synthetic/aruba_aoscx/kitchen_sink.cfg": "1c1097aeb766",
    "real/aruba_aoss/aruba_central_5memberstack_rendered.cfg": "834fc796df65",
    "real/aruba_aoss/hpe_community_2920_wb1608_dhcp_snooping.cfg": "12aa29d82a17",
    "real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg": "06c7aeab8a24",
    "real/aruba_aoss/hpe_community_2930f_wc1610_dhcp_server.cfg": "dd1030133a7a",
    "real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg": "a4e275c2c670",
    "real/aruba_aoss/user_contrib_2930m_wc1611.cfg": "fa27e0f87457",
    "synthetic/aruba_aoss/kitchen_sink.cfg": "0b36d8988e79",
    "aruba_aoss/show_run_simple.txt": "8a4bc3fe9e9d",
    "real/cisco_iosxe/batfish_cisco_aaa.txt": "e25af909db82",
    "real/cisco_iosxe/batfish_cisco_interface.txt": "ac89fc3d7159",
    "real/cisco_iosxe/batfish_cisco_ip_route.txt": "ab1f0cce8811",
    "real/cisco_iosxe/batfish_cisco_logging.txt": "b1aad8f82e94",
    "real/cisco_iosxe/batfish_cisco_snmp.txt": "ec27664e753c",
    "real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt": "516d7c944062",
    "real/cisco_iosxe/ciscolive_brkops1104_evpn_leaf_iosxe1715.txt": "9aab4d223d04",
    # The IOSv capture whose every line is at column 0 was here: the
    # IOS-XE CLI parser refuses it, and it is kept under ``refused/``
    # (``test_a_flat_text_is_refused.py``).
    "real/cisco_iosxe/cml_saumur_iosxe1712_pvrstp.txt": "2425f79888f2",
    "real/cisco_iosxe/ntc_carrier_interfaces.txt": "3c1760c9d5cd",
    "real/cisco_iosxe/racc_cat8000v_iosxe179_netconf.txt": "0bd80061c03b",
    "real/cisco_iosxe/racc_csr1000v_iosxe169_bgp_ospf.txt": "bcdfaa8ebcef",
    "real/cisco_iosxe/racc_csr1_iosxe173_umbrella_sig.txt": "454f509eaaf8",
    "real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt": "7192fbc5fd5e",
    "synthetic/cisco_iosxe_cli/kitchen_sink.txt": "c2f10d43a64e",
    "iosxe/show_run_simple.txt": "fba5436f7b17",
    "real/cisco_nxos/akarneliuk_evpn_vxlan_mcast_leaf_c1l1_nxos939.txt": "b5ee504e06f3",
    "real/cisco_nxos/batfish_nxos_bgp_redist_d1.txt": "ed872f066b0f",
    "real/cisco_nxos/batfish_nxos_evpn_l2vni_nx1.txt": "305bb98e00bf",
    "real/cisco_nxos/batfish_nxos_evpn_l3vni_nx1.txt": "7822cd4c7d39",
    "real/cisco_nxos/batfish_nxos_evpn_l3vni_nx2.txt": "62020aba49e9",
    "real/cisco_nxos/batfish_nxos_hsrp_nxos1.txt": "bb10e8a95a2d",
    "real/cisco_nxos/batfish_nxos_hsrp_nxos2.txt": "811a7b6f87eb",
    "real/cisco_nxos/batfish_nxos_n9kv_ebgp_r1.txt": "563911b052c0",
    "real/cisco_nxos/busterswt_spine_leaf_xk32_1_nxos9312.txt": "d0775abcee6e",
    "real/cisco_nxos/nautobot_gc_nxos_snmp_spine01_nxos933.txt": "1729a6024e35",
    "real/cisco_nxos/networklessons_clab_dag_symmetric_irb_leaf1_nxos1027.cfg": "34109f2ee06c",
    "real/cisco_nxos/networklessons_clab_vxlan_mcast_leaf2_nxos.cfg": "a473a68a8205",
    "synthetic/cisco_nxos/kitchen_sink.cfg": "f3cb7a5a89f3",
    "real/dell_os10/azlocal_tor1.txt": "254896e1a85a",
    "real/dell_os10/azlocal_tor2.txt": "88bb0da08716",
    "real/dell_os10/azsupport_TOR1_Sample.cfg": "4751d5837437",
    "real/dell_os10/azsupport_TOR2_Sample.cfg": "c67c68101040",
    "real/dell_os10/canu_sw-leaf-bmc-001.cfg": "048abe38dae0",
    "real/dell_os10/dellgeos_S5212F-TOR1-Advanced.cfg": "34857fa6db7b",
    "real/dell_os10/dellgeos_S5212F-TOR1-Universal.cfg": "621b35863c2d",
    "real/dell_os10/dellgeos_S5212F-TOR2-Advanced.cfg": "a115f3940371",
    "real/dell_os10/dellgeos_S5212F-TOR2-Universal.cfg": "c6abd209a7bc",
    "synthetic/dell_os10/kitchen_sink.cfg": "2afb408e4714",
    "real/arista_eos/batfish_duplicateprivate_eos4211.txt": "92358f840447",
    "real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt": "0760df6623db",
    "real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt": "06ce2c081564",
    "real/arista_eos/karneliuk_a_eos1_eos4260.txt": "0b4c4b217747",
    "real/arista_eos/ksator_dcs_7150s64_eos4224.txt": "1b74762ebc5b",
    "synthetic/arista_eos/kitchen_sink.txt": "5f8ca989330b",
    "real/cisco_iosxr/batfish_ebgp_border01.txt": "d17cfb52335f",
    "real/cisco_iosxr/batfish_ebgp_border02.txt": "eb970a141bb2",
    "real/cisco_iosxr/batfish_ibgp_border01.txt": "639b6fd2954a",
    "real/cisco_iosxr/batfish_ibgp_rr.txt": "0432b72eff4e",
    "real/cisco_iosxr/batfish_vpnv4_pe1.txt": "d3c44fa0bb3b",
    "real/cisco_iosxr/batfish_vpnv4_pe2.txt": "fa0c9f8fddb3",
    "real/cisco_iosxr/batfish_vpnv4_pe3.txt": "63fcc6d7a988",
    "real/cisco_iosxr/iosxr_design_cst_pa3_xr752.cfg": "700193459777",
    "real/cisco_iosxr/xrdtools_isis_r1.cfg": "178d0314da43",
    "real/cisco_iosxr/xrdtools_sr_xrd1.cfg": "74c70c975078",
    "real/cisco_iosxr/xrdtools_srv6_pe1.cfg": "0e4e6ddc0250",
    "synthetic/cisco_iosxr/kitchen_sink.cfg": "75b5a4a7443e",
}

#: The committed inputs that hold a banner: the body pass changes their
#: text, and nothing else's.
HOLD_A_BANNER = {
    # `aaa authentication banner ^C...^C`, on one line.
    "real/cisco_iosxe/batfish_cisco_aaa.txt",
    "real/aruba_aoscx/canu_csm17_spine001_ipv6_vrf.cfg",
    "real/aruba_aoscx/netutils_aoscx_snmpv3_glcx1009.cfg",
    "real/aruba_aoss/aruba_central_5memberstack_rendered.cfg",
    "real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt",
    "real/cisco_iosxe/racc_cat8000v_iosxe179_netconf.txt",
    "real/cisco_iosxe/racc_csr1000v_iosxe169_bgp_ospf.txt",
    "real/cisco_nxos/busterswt_spine_leaf_xk32_1_nxos9312.txt",
    "real/dell_os10/canu_sw-leaf-bmc-001.cfg",
}


def _body_pass(codec: str) -> Callable[[str], str]:
    """The parser's body pass, looked up when asked (a test may have put
    a defect in its place)."""
    return eos_parse.without_bodies if codec == "arista_eos" else MODULES[codec][0].without_banner_bodies


def _check_committed() -> None:
    moved = {}
    for codec, path in COMMITTED:
        try:
            now = _digest(codec, path)
        except ParseError as refused:
            pytest.fail(f"{path} is refused: {refused}")
        if path in BEFORE and now != BEFORE[path]:
            moved[path] = now
    assert moved == {}


def test_every_committed_input_parses_to_the_tree_it_gave() -> None:
    """No committed input of the seven is refused, and each pinned one
    parses to the tree it gave before a banner was read as text: no
    committed banner's body holds a line a reader takes, and none ends
    a line where a device would not."""
    # A capture committed later is held to no digest, only to not being
    # refused.
    assert BEFORE and set(BEFORE) <= {path for _, path in COMMITTED}
    assert {codec for codec, _ in COMMITTED} == set(_DIRS)
    _check_committed()


def _check_which_hold_a_banner() -> None:
    changed = {path for codec, path in COMMITTED if _body_pass(codec)(_read(path)) != _read(path)}
    assert changed == HOLD_A_BANNER


def test_the_body_pass_changes_the_inputs_that_hold_a_banner() -> None:
    _check_which_hold_a_banner()


# ---------------------------------------------------------------------------
# (e) A line end the device does not count
# ---------------------------------------------------------------------------

#: The characters ``str.splitlines`` ends a line at, a line feed and
#: ``\r\n`` aside.  A device ends a line at a line feed: a body line that
#: ends in one of these is, to the device, one line with the next.
OTHER_LINE_ENDS = {
    "CR": "\r", "VT": "\x0b", "FF": "\x0c", "FS": "\x1c", "GS": "\x1d", "RS": "\x1e",
    "NEL": "\x85", "LS": "\u2028", "PS": "\u2029",
}
#: Per parser: the text before the banner, and a banner with ``{LE}``
#: where a line ends -- on the line that opens it, a line in it and the
#: line that ends it -- with the number of that line.  Each is followed
#: by an account line: were the banner cut there, it would be read.
_EOS_HEAD = "! device: sw1 (DCS-7050, EOS-4.28.0F)\n!\nhostname sw1\n"
LINE_END_PLACES: dict[str, tuple[str, dict[str, tuple[str, int]]]] = {
    "cisco_iosxe_cli": (HEAD["cisco_iosxe_cli"], {
        "the line that opens it": ("banner motd ^C{LE}" + ACCOUNT["cisco_iosxe_cli"] + "\n^C\n", 4),
        "a line in it": ("banner motd ^C\nhi{LE}^C\n" + ACCOUNT["cisco_iosxe_cli"] + "\n^C\n", 5),
        "the line that ends it": ("banner motd ^C\nhi\nx^C{LE}" + ACCOUNT["cisco_iosxe_cli"] + "\n", 6),
    }),
    "cisco_nxos": (HEAD["cisco_nxos"], {
        "the line that opens it": ("scheduler job name J{LE}" + ACCOUNT["cisco_nxos"] + "\nend-job\n", 4),
        "a line in it": ("scheduler job name J\nx{LE}end-job\n" + ACCOUNT["cisco_nxos"] + "\nend-job\n", 5),
        "the line that ends it": ("banner motd #\nhi\nx#{LE}" + ACCOUNT["cisco_nxos"] + "\n", 6),
    }),
    "aruba_aoscx": (HEAD["aruba_aoscx"], {
        "the line that opens it": ("banner motd !{LE}" + ACCOUNT["aruba_aoscx"] + "\n!\n", 3),
        "a line in it": ("banner motd !\nWARNING!{LE}" + ACCOUNT["aruba_aoscx"] + "\n!\n", 4),
        "the line that ends it": ("banner motd !\nhi\n!{LE}" + ACCOUNT["aruba_aoscx"] + "\n", 5),
    }),
    "dell_os10": (HEAD["dell_os10"], {
        "the line that opens it": ("banner motd ^C{LE}" + ACCOUNT["dell_os10"] + "\n^C\n", 3),
        "a line in it": ("banner motd ^C\nHello{LE}^C\n" + ACCOUNT["dell_os10"] + "\n^C\n", 4),
        "the line that ends it": ("banner motd ^C\nhi\n^C{LE}" + ACCOUNT["dell_os10"] + "\n", 5),
    }),
    "aruba_aoss": (HEAD["aruba_aoss"], {
        "the line that opens it": ('banner motd "hi{LE}' + ACCOUNT["aruba_aoss"] + '\n"\n', 2),
        "a line in it": ('banner motd "hi\nWelcome"{LE}' + ACCOUNT["aruba_aoss"] + '\n"\n', 3),
        "the line that ends it": ('banner motd "hi\nbye"{LE}' + ACCOUNT["aruba_aoss"] + "\n", 3),
    }),
    "arista_eos": (_EOS_HEAD, {
        "the line that opens it": ("banner motd{LE}hi\nEOF\n" + "username intruder privilege 15 nopassword\n", 4),
        "a line in it": ("banner motd\nHello{LE}EOF\nusername intruder privilege 15 nopassword\nEOF\n", 5),
        "the line that ends it": ("banner motd\nhi\nEOF{LE}username intruder privilege 15 nopassword\n", 6),
    }),
    "cisco_iosxr": (HEAD["cisco_iosxr"], {
        "the line that opens it": ("banner motd ;{LE}" + ACCOUNT["cisco_iosxr"] + "\n;\n", 3),
        "a line in it": ("banner motd ;\nhi{LE};\n" + ACCOUNT["cisco_iosxr"] + "\n;\n", 4),
        "the line that ends it": ("banner motd ;\nhi\nx;{LE}" + ACCOUNT["cisco_iosxr"] + "\n", 5),
    }),
}
LINE_END_IDS = [
    (codec, place, name)
    for codec, (_, places) in LINE_END_PLACES.items() for place in places for name in OTHER_LINE_ENDS
]


def _check_line_end(codec: str, place: str, name: str) -> None:
    head, places = LINE_END_PLACES[codec]
    body, line = places[place]
    text = head + body.replace("{LE}", OTHER_LINE_ENDS[name])
    error = _refusal(codec, text)
    assert str(error) == _line_end_sentence(codec).format(line=line), (codec, place, name)
    assert (error.path, error.snippet) == (f"line {line}", ""), (codec, place, name)


@pytest.mark.parametrize(("codec", "place", "name"), LINE_END_IDS, ids=[" / ".join(i) for i in LINE_END_IDS])
def test_a_body_line_that_ends_where_a_device_does_not_is_refused(codec: str, place: str, name: str) -> None:
    """Each of those characters ended a banner early, or slipped past a
    refusal, and the account line after it was read: a banner was an
    account again, in jobs that said ``completed``."""
    _check_line_end(codec, place, name)


def test_the_same_texts_with_a_line_feed_are_not_refused_so() -> None:
    """The refusal is the line end's: with a line feed in its place,
    no text above is refused for its line ends."""
    for codec, (head, places) in LINE_END_PLACES.items():
        for place, (body, _) in places.items():
            try:
                _parse(codec, head + body.replace("{LE}", "\n"))
            except ParseError as error:
                assert "ends in a character" not in str(error), (codec, place)


def test_a_line_end_outside_a_body_is_the_parsers_own() -> None:
    """A form feed between two lines of the configuration ends no body,
    and is not refused here."""
    for codec in CODECS:
        text = HEAD[codec] + "\x0c\n" + AFTER[codec]
        assert _holds(codec, text) == AFTER_HOLDS, codec


# ---------------------------------------------------------------------------
# (f) Each check, handed the defect it is for, fails
# ---------------------------------------------------------------------------


def _with_a_defect(module: ModuleType, name: str, old: str, new: str) -> Callable:
    """*module*'s function *name* with *old*, one fragment of its source,
    written as *new*: a defect put back, in this process only.  A
    fragment that is no longer in the source fails here, not in
    silence."""
    source = textwrap.dedent(inspect.getsource(getattr(module, name)))
    assert source.count(old) == 1, old
    space = dict(vars(module))
    exec(compile(source.replace(old, new), "<a defect put back>", "exec"), space)
    return space[name]


def _bodies_by(monkeypatch: pytest.MonkeyPatch, defect: Callable[[str], str]) -> None:
    """The body pass as *defect*, in every place that calls it."""
    for parse_module, codec_module in MODULES.values():
        monkeypatch.setattr(parse_module, "without_banner_bodies", defect)
        monkeypatch.setattr(codec_module, "without_banner_bodies", defect)
    monkeypatch.setattr(aoss_detect, "without_banner_bodies", defect)


def _scanner_by(monkeypatch: pytest.MonkeyPatch, old: str, new: str) -> None:
    """The shared loop with a defect, in each of the parsers that call it."""
    defect = _with_a_defect(_scanner, "without_text_bodies", old, new)
    for parse_module, _ in MODULES.values():
        monkeypatch.setattr(parse_module, "without_text_bodies", defect)


def test_the_checks_fail_when_a_banner_is_read_as_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    _bodies_by(monkeypatch, lambda raw: raw)
    for codec in CODECS:
        with pytest.raises(AssertionError):
            _check_banner_tree(codec)
        with pytest.raises(AssertionError):
            _check_banner_outputs(codec)
    for codec, name in FORM_IDS:
        if name in _HIDES_NOTHING:
            continue
        with pytest.raises((AssertionError, ParseError)):
            _check_form(codec, name)
    for name in REFUSED:
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            _check_refused(name)
    with pytest.raises(AssertionError):
        _check_which_hold_a_banner()
    with pytest.raises(AssertionError):
        _check_the_release()


@pytest.mark.parametrize("codec", CODECS)
def test_the_tier3_check_fails_when_the_rows_are_read_from_the_banner(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Tier-3 rows are read from the text the parser read."""
    monkeypatch.setattr(MODULES[codec][1], "without_banner_bodies", lambda raw: raw)
    with pytest.raises(AssertionError):
        _check_banner_tree(codec)


@pytest.mark.parametrize("codec", CODECS)
def test_the_json_check_fails_when_the_shape_is_read_before_the_banners(
    codec: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    parse_module, codec_module = MODULES[codec]
    source = textwrap.dedent(inspect.getsource(parse_module.parse_intent))
    found = re.search(r"raw = without_banner_bodies\(raw\)\n(.*?)shape = detect_input_shape\(raw\)", source, re.S)
    assert found is not None
    swapped = "shape = detect_input_shape(raw)\n" + found.group(1) + "raw = without_banner_bodies(raw)"
    monkeypatch.setattr(codec_module, "parse_intent", _with_a_defect(
        parse_module, "parse_intent", found.group(0), swapped,
    ))
    with pytest.raises(ParseError):
        _check_form(codec, "a banner whose text begins as JSON does")


def test_the_committed_check_fails_when_a_banner_ends_only_alone_on_a_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IOS-XE ends a banner at its delimiter ANYWHERE: an IOSv capture
    prints the closing ``^C`` after the text of the body's last line, and
    with a rule of "alone on a line" its banners never end -- two
    committed captures are refused."""
    monkeypatch.setattr(ios_parse, "ends_anywhere", lambda delimiter: lambda text, number: text.strip() == delimiter)
    with pytest.raises(pytest.fail.Exception, match="is refused"):
        _check_committed()


def test_the_caret_check_fails_when_a_caret_alone_ends_a_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Batfish and ciscoconfparse2 end a printed banner at a ``^`` alone;
    what the device holds ends at ``^C``."""
    monkeypatch.setattr(ios_parse, "_PRINTED_DELIMITER", "^")
    with pytest.raises(AssertionError):
        _check_form("cisco_iosxe_cli", "a caret alone in the body")


def test_the_unended_checks_fail_when_a_body_may_run_to_the_end(monkeypatch: pytest.MonkeyPatch) -> None:
    _scanner_by(monkeypatch, "if ends is not None:\n        raise ParseError(", "if False:\n        raise ParseError(")
    assert len(UNENDED) >= len(CODECS)
    for name in UNENDED:
        with pytest.raises(pytest.fail.Exception):
            _check_refused(name)


def test_the_case_checks_fail_when_a_delimiter_is_compared_without_its_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ios_parse, "ends_anywhere", lambda delimiter: lambda text, number: delimiter.lower() in text.lower(),
    )
    monkeypatch.setattr(
        aoscx_parse, "_ends_at_the_end_of_a_line",
        lambda delimiter: lambda text, number: text.rstrip().lower().endswith(delimiter.lower()),
    )
    for codec in ("cisco_iosxe_cli", "aruba_aoscx"):
        with pytest.raises(AssertionError):
            _check_form(codec, "a delimiter compared by its case")


def test_the_aoscx_checks_fail_when_a_delimiter_anywhere_ends_a_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    """AOS-CX prints the delimiter after the stored text: one with text
    after it on its line is the text's, and a banner such as ``WARNING!
    Authorised access only`` runs on past it."""
    monkeypatch.setattr(aoscx_parse, "_ends_at_the_end_of_a_line", _scanner.ends_anywhere)
    with pytest.raises(AssertionError):
        _check_form("aruba_aoscx", "the delimiter with text after it, in the text")
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _check_refused("aruba_aoscx: a banner whose delimiter has text after it, and no other")


def test_the_macro_check_fails_when_an_at_sign_anywhere_ends_a_macro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ios_parse, "_is_the_macros_end", lambda text, number: "@" in text)
    with pytest.raises(AssertionError):
        _check_form("cisco_iosxe_cli", "a macro whose lines hold an @")


@pytest.mark.parametrize("defect", [
    lambda text, number: text.strip() == "end-job",
    lambda text, number: text.startswith("end-job"),
], ids=["indented", "a longer word"])
def test_the_job_check_fails_when_end_job_ends_a_job_otherwise(
    defect: Callable[[str, int], bool], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nxos_parse, "_is_the_jobs_end", defect)
    with pytest.raises(AssertionError):
        _check_form("cisco_nxos", "a scheduler job whose lines hold end-job otherwise")


def test_the_column_0_checks_fail_when_a_line_message_opens_only_indented(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = ios_parse._OPENS_A_DELIMITED_BODY_RE
    old = r"|[ \t]*(?:vacant-message"
    assert pattern.pattern.count(old) == 1
    monkeypatch.setattr(ios_parse, "_OPENS_A_DELIMITED_BODY_RE", re.compile(
        pattern.pattern.replace(old, r"|[ \t]+(?:vacant-message"), pattern.flags,
    ))
    for name in ("a line's vacant and refuse messages, in column 0", "a web authentication banner, in column 0"):
        with pytest.raises(AssertionError):
            _check_form("cisco_iosxe_cli", name)


def test_the_busy_message_check_fails_when_it_opens_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = ios_parse._OPENS_A_DELIMITED_BODY_RE
    old = r"|busy-message[ \t]+[^ \t]+[ \t]+"
    assert pattern.pattern.count(old) == 1
    monkeypatch.setattr(ios_parse, "_OPENS_A_DELIMITED_BODY_RE", re.compile(
        pattern.pattern.replace(old, ""), pattern.flags,
    ))
    with pytest.raises(AssertionError):
        _check_form("cisco_iosxe_cli", "a busy message")


def test_the_release_check_fails_when_the_opening_line_is_left_as_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """A line that opens a body and goes on with its text, left for the
    readers: the release pattern reads the banner's release."""
    _scanner_by(
        monkeypatch,
        "            if not body.ended:\n                ends = body.ends\n",
        "            if not body.ended:\n                ends = body.ends\n                continue\n",
    )
    with pytest.raises(AssertionError):
        _check_the_release()


#: Per parser: the orphan check removed from its openers.
_NO_ORPHAN_CHECK = {
    "cisco_iosxe_cli": (ios_parse, "if delimiter in text:", "if False:"),
    "dell_os10": (os10_parse, "if alone in opened and alone != _COMMENT_MARK:", "if False:"),
    "aruba_aoss": (aoss_parse, "if quoted_at and '\"' in text and _quotes_in(text) % 2:", "if False:"),
}


@pytest.mark.parametrize("codec", list(_NO_ORPHAN_CHECK))
def test_the_orphan_checks_fail_when_a_text_may_hold_its_end(codec: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real end the device printed is left on a line outside every
    body; not refused, the lines between were configuration -- the
    account among them."""
    module, old, new = _NO_ORPHAN_CHECK[codec]
    monkeypatch.setattr(module, "_openers", _with_a_defect(module, "_openers", old, new))
    assert ORPHANS[codec]
    for name in ORPHANS[codec]:
        with pytest.raises(pytest.fail.Exception):
            _check_refused(name)


def test_the_indented_orphan_check_fails_when_only_column_0_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ^C the device printed follows the text's last line, which may
    be indented."""
    monkeypatch.setattr(ios_parse, "_openers", _with_a_defect(
        ios_parse, "_openers", "if delimiter in text:", "if delimiter in text and not text[:1].isspace():",
    ))
    with pytest.raises(pytest.fail.Exception):
        _check_refused("cisco_iosxe_cli: the text of a banner holds its printed end, its last line indented")


def test_the_before_any_banner_checks_fail_when_an_end_is_looked_for_everywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What a device prints to end a banner is the end of a banner's text
    only after a banner it ends: before one, or after a banner typed
    with another delimiter, it is the configuration's."""
    monkeypatch.setattr(ios_parse, "_openers", _with_a_defect(
        ios_parse, "_openers", "for delimiter, at in opened.items():",
        "for delimiter, at in dict.fromkeys(_DEVICE_DELIMITERS, 0).items():",
    ))
    monkeypatch.setattr(aoss_parse, "_openers", _with_a_defect(
        aoss_parse, "_openers", "if quoted_at and '\"' in text", "if '\"' in text",
    ))
    with pytest.raises(ParseError):
        _check_form("cisco_iosxe_cli", "^C in a line outside a banner a device printed")
    with pytest.raises(ParseError):
        _check_form("aruba_aoss", "an odd number of quotes before any banner")


def test_the_comment_check_fails_when_a_bang_after_a_bang_banner_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os10_parse, "_openers", _with_a_defect(
        os10_parse, "_openers", "if alone in opened and alone != _COMMENT_MARK:", "if alone in opened:",
    ))
    with pytest.raises(ParseError):
        _check_form("dell_os10", "a line that is ! after a banner delimited by it")


def test_the_escape_check_fails_when_an_escaped_quote_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aoss_parse, "_quotes_in", lambda text: text.count('"'))
    with pytest.raises(ParseError):
        _check_form("aruba_aoss", "an escaped quote in a line after a banner")


@pytest.mark.parametrize("new", [
    "caret = None", 'caret = rest[:2] if rest[:2] == "^C" else None',
], ids=["a caret alone ends it", "only a capital C is the printed form"])
def test_the_ios_xr_caret_checks_fail_when_a_caret_alone_ends_a_caret_c_banner(
    new: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read as one character, ``^C`` ends at a caret alone and the
    account after it is configuration; whether the router reads it so is
    not established, and the line is refused."""
    old = 'caret = rest[:2] if rest[:2] in ("^C", "^c") else None'
    monkeypatch.setattr(xr_parse, "_openers", _with_a_defect(xr_parse, "_openers", old, new))
    names = [name for name, (_, _, sentence, _, _) in REFUSED.items() if sentence is xr_parse.CARET_MESSAGE]
    assert len(names) == 2
    with pytest.raises(pytest.fail.Exception):
        for name in names:
            _check_refused(name)


def test_the_ios_xr_caret_check_fails_when_both_readings_ending_on_one_line_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where the two readings end the banner on the same line, nothing is
    in doubt, and nothing is refused."""
    monkeypatch.setattr(xr_parse, "_openers", _with_a_defect(
        xr_parse, "_openers", "if caret and caret not in line:", "if caret and line.count('^') != line.count(caret):",
    ))
    for name in ("^C, a caret alone and the end on one line", "^C on one line, a caret alone before its end"):
        with pytest.raises(ParseError):
            _check_form("cisco_iosxr", name)


def test_the_ios_xr_one_line_check_fails_when_the_opening_line_ends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xr_parse, "_openers", _with_a_defect(
        xr_parse, "_openers", "ended=_end_in(after, number)", "ended=False",
    ))
    # (Two banners ``cc`` hide it: the first, left open, ends at the second.)
    for name in ("a banner on one line, spaces after its end", "a banner on one line, text after its end"):
        with pytest.raises((AssertionError, ParseError)):
            _check_form("cisco_iosxr", name)


def test_the_ios_xr_checks_fail_when_a_banner_xr_does_not_print_opens_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xr_parse, "_NAMES_A_BANNER_RE", re.compile(r"(?!)"))
    names = [name for name, (_, _, sentence, _, _) in REFUSED.items() if sentence is xr_parse.UNKNOWN_BANNER_MESSAGE]
    assert len(names) == 4
    for name in names:
        with pytest.raises(pytest.fail.Exception):
            _check_refused(name)


def test_the_ios_xr_case_check_fails_when_a_delimiter_is_compared_without_its_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xr_parse, "_openers", _with_a_defect(
        xr_parse, "_openers", "if delimiter not in line:", "if delimiter.lower() not in line.lower():",
    ))
    with pytest.raises(AssertionError):
        _check_form("cisco_iosxr", "a delimiter compared by its case")


@pytest.mark.parametrize(("old", "new"), [
    ("span[2] = at", "pass"),
    ("lines[what] = lines.get(what, 0) + end - start + 1", "lines[what] = end - start + 1"),
    ("first.setdefault(what, start)", "first[what] = start"),
], ids=["no line counted", "the last banner of a kind only", "the last first line"])
def test_the_ios_xr_row_checks_fail_when_lines_are_miscounted(
    old: str, new: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    function = "_openers" if old == "span[2] = at" else "banner_rows"
    monkeypatch.setattr(xr_parse, function, _with_a_defect(xr_parse, function, old, new))
    with pytest.raises(AssertionError):
        _check_xr_rows()


def test_the_line_end_checks_fail_when_any_line_end_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_scanner, "_ends_as_a_device_ends", lambda *args: None)
    monkeypatch.setattr(eos_parse, "_ends_as_the_switch_ends", lambda line, number: None)
    for codec, place, name in LINE_END_IDS:
        with pytest.raises((AssertionError, pytest.fail.Exception)):
            _check_line_end(codec, place, name)
