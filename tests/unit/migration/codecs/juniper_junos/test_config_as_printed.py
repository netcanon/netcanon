"""A Junos config as ``show configuration`` prints it.

The hierarchical form was read -- if it was typed.  What a device
prints begins ``## Last commit: ...`` and ``version 21.4R3.15;``, and
ends its secrets ``## SECRET-DATA``.  The first two made the parser
take the text for set-form, where no line of it is a statement: an
empty config, a job that rendered nothing and said nothing.  The third
was read as a statement, and put every block after it one level out.
And no probe knew the form, so a paste was offered no codec at all.

Each printed form here is compared with the same config written bare,
which is the form the parser has always read.  That comparison goes
through one tokeniser twice; ``test_two_forms_one_tree.py`` has each
form beside its set form typed by hand.

A capture is also seldom only what the device printed: it is cut out
of a terminal session, with the prompt it was taken at, and saved by
an editor.  The second half of this module is those wrappings.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.juniper_junos.parse import (
    _blockform_to_setform,
    _looks_like_blockform,
    drop_session_lines,
    parse_intent,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_detect import detect_codec
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

_SYSTEM = (
    "system {",
    "    host-name r1;",
    "    root-authentication {",
    '        encrypted-password "$6$fake$roothash";{secret}',
    "    }",
    "    login {",
    "        user admin {",
    "            uid 2000;",
    "            class super-user;",
    "            authentication {",
    '                encrypted-password "$6$fake$adminhash";{secret}',
    "            }",
    "        }",
    "    }",
    "    name-server {",
    "        192.0.2.53;",
    "    }",
    "}",
    "interfaces {",
    "    ge-0/0/1 {",
    '        description "uplink # 1";',
    "        unit 0 {",
    "            family inet {",
    "                address 10.0.0.1/24;",
    "            }",
    "        }",
    "    }",
    "}",
    "snmp {",
    "    community fakeCommunity {{{secret}",
    "        authorization read-only;",
    "    }",
    "}",
)


def _config(*head: str, secret: str = "") -> str:
    return "\n".join([*head, *(line.replace("{secret}", secret) for line in _SYSTEM)]) + "\n"


BARE = _config().replace("{{", "{")
FORMS = {
    "version first": _config("version 21.4R3.15;").replace("{{", "{"),
    "a quoted version first": _config('version "21.4R3.15 [builder]";').replace("{{", "{"),
    "the last-commit line": _config(
        "## Last commit: 2024-01-01 00:00:00 UTC by admin", "version 21.4R3.15;",
    ).replace("{{", "{"),
    "secrets marked": _config(secret=" ## SECRET-DATA").replace("{{", "{"),
    "as printed": _config(
        "## Last commit: 2024-01-01 00:00:00 UTC by admin", "version 21.4R3.15;",
        secret=" ## SECRET-DATA",
    ).replace("{{", "{"),
    "a blank line and a comment first": _config("", "# saved by hand", "").replace("{{", "{"),
}


def _tree(text: str) -> dict:
    dump = parse_intent(text).model_dump()
    dump.pop("source_version")
    return dump


def test_the_bare_form_reads_what_it_says() -> None:
    """The control: the comparison below is against a config, not
    against another empty one."""
    tree = parse_intent(BARE)
    assert tree.hostname == "r1"
    assert [iface.name for iface in tree.interfaces] == ["ge-0/0/1"]
    assert tree.interfaces[0].description == "uplink # 1"
    assert [user.name for user in tree.local_users] == ["admin"]
    assert tree.dns_servers == ["192.0.2.53"]
    assert tree.snmp is not None and tree.snmp.community == "fakeCommunity"


@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_printed_form_is_the_config_it_prints(form: str) -> None:
    assert _looks_like_blockform(FORMS[form])
    assert _tree(FORMS[form]) == _tree(BARE)


@pytest.mark.parametrize("form", sorted(FORMS))
def test_no_annotation_is_left_in_a_statement(form: str) -> None:
    """``## SECRET-DATA`` was read as a statement
    (``set system root-authentication ## SECRET-DATA``), and every
    block after it came out one level off: the user after the first
    secret was outside ``login``, and ``snmp`` was not read."""
    lines = _blockform_to_setform(FORMS[form]).splitlines()
    # The bare form's statements, and the version where one is printed.
    assert [
        line for line in lines if not line.startswith("set version ")
    ] == _blockform_to_setform(BARE).splitlines()
    assert not [line for line in lines if "SECRET-DATA" in line or "Last commit" in line]
    # A ``#`` inside a quoted string is the string's.
    assert 'set interfaces ge-0/0/1 description "uplink # 1"' in lines


def test_the_version_is_read_from_a_printed_form() -> None:
    assert parse_intent(FORMS["as printed"]).source_version == "21.4R3.15"


@pytest.mark.parametrize(
    "text",
    [
        "set version 21.4R3.15\nset system host-name r1\n",
        "## Last commit: 2024-01-01 00:00:00 UTC by admin\nset system host-name r1\n",
        "delete system host-name\nset system host-name r1\n",
        # Set-form under a comment, with a stray ``;`` and a line that
        # ends in a brace: a ``set`` line is never a statement of the
        # top level to step over.
        "## saved\nset system host-name r1;\nset interfaces ge-0/0/1 description b{\n",
        # Nor the line that opens the first block, whichever of its
        # verbs the text begins with.
        "## saved\nset interfaces ge-0/0/1 description b{\nset system host-name r1;\n",
        "delete interfaces ge-0/0/1 description b{\nset system host-name r1;\n",
        "activate interfaces ge-0/0/1 description b{\nset system host-name r1;\n",
        "deactivate interfaces ge-0/0/1 description b{\nset system host-name r1;\n",
        # JSON without its first brace, and a line that is one brace.
        '"system": {\n  "host-name": "r1";\n}\n',
        "version 21.4R3.15;\n{\n    host-name r1;\n}\n",
        # Blocks, and no statement that ends in ``;`` anywhere: VyOS.
        "system {\n    host-name r1\n}\n",
        # Cisco: a version line with no ``;``, a banner with a brace.
        "version 17.12\nhostname sw1\nbanner motd {\n hello;\n}\n",
        '{\n  "system": {"host-name": "r1"};\n}\n',
    ],
)
def test_what_is_not_the_hierarchical_form_is_not_taken_for_it(text: str) -> None:
    assert not _looks_like_blockform(text)


def test_set_form_under_a_comment_is_still_read() -> None:
    tree = parse_intent("## Last commit: 2024-01-01 00:00:00 UTC by admin\nset system host-name r1\n")
    assert tree.hostname == "r1"


@pytest.mark.parametrize("form", ["bare", *sorted(FORMS)])
def test_detection_offers_the_junos_codec(form: str) -> None:
    text = BARE if form == "bare" else FORMS[form]
    found = detect_codec(text)
    assert [candidate.codec for candidate in found][:1] == ["juniper_junos"], found


def test_a_vyos_config_is_not_taken_for_junos() -> None:
    """VyOS writes ``system {`` too, and ends no statement with ``;``."""
    vyos = "\n".join([
        "interfaces {", "    ethernet eth0 {", "        address 10.0.0.1/24", "    }", "}",
        "system {", "    host-name r1", "}", "",
    ])
    assert get_codec("juniper_junos").probe(vyos) is None


def test_a_printed_capture_translates() -> None:
    """Through the plan path: it rendered nothing, and the job had no
    word about why."""
    job = run_plan_with_overrides(
        get_codec("juniper_junos"), get_codec("arista_eos"), FORMS["as printed"],
        port_rename_map={}, force=True,
    )
    assert "hostname r1" in job.rendered.splitlines()
    assert "interface Ethernet1" in job.rendered.splitlines()
    assert "   ip address 10.0.0.1/24" in job.rendered.splitlines()


# ---------------------------------------------------------------------------
# What a config holds and does not run
# ---------------------------------------------------------------------------

_TAGGED = "\n".join([
    "system {", "    host-name r1;", "}",
    "interfaces {",
    "    inactive: ge-0/0/2 {", "        unit 0 {", "            family inet {",
    "                address 10.0.2.1/24;", "            }", "        }", "    }",
    "    ge-0/0/1 {", "        unit 0 {", "            family inet {",
    "                address 10.0.0.1/24;", "            }", "        }", "    }",
    "    replace: ge-0/0/3 {", '        description "third";', "    }",
    "    ge-0/0/4 {", '        inactive: description "fourth";', "        mtu 9000;", "    }",
    "}",
    "protect: routing-options {", "    static {",
    "        route 0.0.0.0/0 next-hop 10.0.0.254;", "    }", "}", "",
])


def _names(tree) -> list[str]:
    return sorted(iface.name for iface in tree.interfaces)


def test_a_tag_is_not_the_name_of_what_follows_it() -> None:
    """``inactive: ge-0/0/2 {`` was an interface named ``inactive:``,
    ``replace: ge-0/0/3 {`` one named ``replace:``, and a route under
    ``protect: routing-options`` was under a path nothing reads."""
    tree = parse_intent(_TAGGED)
    assert _names(tree) == ["ge-0/0/1", "ge-0/0/3", "ge-0/0/4"]
    assert [route.gateway for route in tree.static_routes] == ["10.0.0.254"]
    third = next(iface for iface in tree.interfaces if iface.name == "ge-0/0/3")
    assert third.description == "third"


def test_what_is_inactive_is_not_in_the_tree_and_is_named() -> None:
    """A deactivated statement is not in force on the device.  Read as
    if it were, it was on the target: an interface with its address,
    a description the source did not show."""
    tree = get_codec("juniper_junos").parse(_TAGGED)
    assert "ge-0/0/2" not in _names(tree)
    assert not [
        iface for iface in tree.interfaces
        if any(address.ip == "10.0.2.1" for address in iface.ipv4_addresses)
    ]
    fourth = next(iface for iface in tree.interfaces if iface.name == "ge-0/0/4")
    assert fourth.description == "" and fourth.mtu == 9000
    # A leaf is named by its first word, as ``display set`` names
    # one: what follows is its value.
    assert tree.dropped_tier3_sections == [
        "inactive: interfaces ge-0/0/2 (deactivated in the source; not translated)",
        "inactive: interfaces ge-0/0/4 description (deactivated in the source; not translated)",
    ]


_SET_FORM = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24",
    "set interfaces ge-0/0/2 unit 0 family inet address 10.0.2.1/24",
    "set interfaces ge-0/0/2 unit 7 family inet address 10.0.7.1/24",
    "set interfaces ge-0/0/20 unit 0 family inet address 10.0.20.1/24",
    "set interfaces ge-0/0/3 description third",
    "set interfaces ge-0/0/3 mtu 9000",
    "{deactivate}",
    "",
])


@pytest.mark.parametrize(
    "deactivate,gone,kept",
    [
        ("deactivate interfaces ge-0/0/2", {"10.0.2.1", "10.0.7.1"}, {"10.0.0.1", "10.0.20.1"}),
        # A unit, and not the interface: by words, so ``ge-0/0/2`` is
        # not the beginning of ``ge-0/0/20``.
        ("deactivate interfaces ge-0/0/2 unit 7", {"10.0.7.1"}, {"10.0.0.1", "10.0.2.1", "10.0.20.1"}),
        ("deactivate interfaces", {"10.0.0.1", "10.0.2.1", "10.0.7.1", "10.0.20.1"}, set()),
        ("deactivate interfaces ge-0/0/9", set(), {"10.0.0.1", "10.0.2.1", "10.0.7.1", "10.0.20.1"}),
        # Taken back further down, as a pasted change would.
        (
            "deactivate interfaces ge-0/0/2\nactivate interfaces ge-0/0/2",
            set(), {"10.0.0.1", "10.0.2.1", "10.0.7.1", "10.0.20.1"},
        ),
    ],
)
def test_set_form_says_it_with_deactivate(deactivate: str, gone: set[str], kept: set[str]) -> None:
    tree = get_codec("juniper_junos").parse(_SET_FORM.replace("{deactivate}", deactivate))
    held = {address.ip for iface in tree.interfaces for address in iface.ipv4_addresses}
    assert held == kept
    assert not held & gone
    named = [label for label in tree.dropped_tier3_sections if label.startswith("inactive: ")]
    assert bool(named) == bool(gone)


def test_a_deactivated_leaf_takes_only_itself() -> None:
    tree = parse_intent(_SET_FORM.replace("{deactivate}", "deactivate interfaces ge-0/0/3 description"))
    third = next(iface for iface in tree.interfaces if iface.name == "ge-0/0/3")
    assert third.description == "" and third.mtu == 9000


def test_the_two_forms_say_the_same() -> None:
    """The hierarchical form is read by writing it as set-form, with a
    ``deactivate`` line where the device printed ``inactive:``."""
    lines = _blockform_to_setform(_TAGGED).splitlines()
    assert "deactivate interfaces ge-0/0/2" in lines
    assert 'deactivate interfaces ge-0/0/4 description "fourth"' in lines
    assert not [line for line in lines if "inactive:" in line or "protect:" in line or "replace:" in line]


def test_a_job_does_not_carry_what_was_inactive() -> None:
    job = run_plan_with_overrides(
        get_codec("juniper_junos"), get_codec("arista_eos"), _TAGGED, port_rename_map={}, force=True,
    )
    assert "10.0.2.1" not in job.rendered
    assert "10.0.0.1" in job.rendered
    assert job.dropped_tier3_sections[0] == (
        "inactive: interfaces ge-0/0/2 (deactivated in the source; not translated)"
    )


def test_a_group_wildcard_first_is_still_junos() -> None:
    """A group's wildcard in the first lines (``<ge-0/0/*> {``) is no XML
    element.  The parser read such a config and detection offered
    nothing for it: the probe asked about XML before the form."""
    text = "\n".join([
        "version 21.4R3.15;", "groups {", "    global {", "        interfaces {",
        "            <ge-0/0/*> {", "                mtu 9100;", "            }", "        }", "    }", "}",
        "system {", "    host-name r1;", "}", "",
    ])
    assert [candidate.codec for candidate in detect_codec(text)][:1] == ["juniper_junos"]
    assert get_codec("juniper_junos").parse(text).hostname == "r1"
    # What IS XML, or JSON, is still nobody's hierarchical config.
    for other in ("<configuration>\n<version>21.4R3.15</version>\n</configuration>\n",
                  "{\n  \"version\": \"21.4R3.15;\",\n  \"system\": {}\n}\n"):
        assert get_codec("juniper_junos").probe(other) is None


def test_the_last_commit_line_and_one_block() -> None:
    """A capture cut down to one block: no ``version``, no ``system``.
    The line counts beside the block's ``{`` and ``;``."""
    text = "\n".join([
        "## Last commit: 2024-01-01 00:00:00 UTC by admin",
        "interfaces {", "    ge-0/0/1 {", "        unit 0;", "    }", "}", "",
    ])
    assert [candidate.codec for candidate in detect_codec(text)][:1] == ["juniper_junos"]


def test_an_inactive_list_takes_every_value_of_it() -> None:
    """``inactive: name-server [ a b ];`` is two ``set`` lines and one
    deactivated statement: the path stops before the bracket."""
    text = "\n".join([
        "system {", "    host-name r1;",
        "    inactive: name-server [ 192.0.2.53 192.0.2.54 ];",
        "    ntp {", "        server 192.0.2.123;", "    }",
        "}", "",
    ])
    assert "deactivate system name-server" in _blockform_to_setform(text).splitlines()
    tree = parse_intent(text)
    assert tree.dns_servers == []
    assert tree.ntp_servers == ["192.0.2.123"]


def test_set_form_ending_in_a_brace_is_read() -> None:
    """Under a ``#`` header the first ``set`` line was the first line
    the form was judged by, and one that ended in ``{`` opened a
    block: a set-form file was refused for braces it does not have."""
    tree = parse_intent(
        "## saved from the lab\n"
        "set interfaces ge-0/0/1 description b{\n"
        "set system host-name r1\n"
        'set interfaces ge-0/0/2 description "a;b"\n'
    )
    assert tree.hostname == "r1"
    assert [(iface.name, iface.description) for iface in tree.interfaces] == [("ge-0/0/1", "b{"), ("ge-0/0/2", "a;b")]


# ---------------------------------------------------------------------------
# A capture as it leaves a terminal
# ---------------------------------------------------------------------------

_PRINTED = FORMS["as printed"]
_TRAILER = "\n{master:0}\nadmin@r1> \n"

#: What a session, a pager, an editor or a wiki page puts around what
#: the device printed.
WRAPPED = {
    "the prompt and the command": "admin@r1> show configuration\n" + _PRINTED,
    "the prompt, a longer command": "admin@r1> show configuration | display inheritance | no-more \n" + _PRINTED,
    "the command with no prompt": "show configuration\n" + _PRINTED,
    "the command and a pipe, no prompt": "show configuration | no-more\n" + _PRINTED,
    "a Virtual Chassis session": "\n\n{master:0}\nadmin@r1> show configuration\n" + _PRINTED + _TRAILER,
    "the trailing prompt only": _PRINTED + _TRAILER,
    "a second Routing Engine": "{backup}\nadmin@r1> show configuration\n" + _PRINTED + "\n{backup}\nadmin@r1>\n",
    "a chassis cluster": "{primary:node0}\nadmin@r1> show configuration\n" + _PRINTED,
    "a line card": "{linecard:2}\nadmin@r1> show configuration\n" + _PRINTED,
    "configuration mode": "[edit]\nadmin@r1# show\n" + _PRINTED + "\n[edit]\nadmin@r1# \n",
    "configuration mode on a Virtual Chassis": "{master:0}[edit]\nadmin@r1# show\n" + _PRINTED,
    "configuration mode, under a level": "[edit interfaces]\nadmin@r1# top show\n" + _PRINTED,
    "from the shell": "root@r1% cli\nroot@r1> show configuration\n" + _PRINTED,
    "a byte-order mark": chr(0xFEFF) + _PRINTED,
    "a byte-order mark and a prompt": chr(0xFEFF) + "admin@r1> show configuration\n" + _PRINTED,
    "blank lines first": "\n\n\n" + _PRINTED,
    "a carriage return on every line": _PRINTED.replace("\n", "\r\n"),
    "a session with carriage returns": ("{master:0}\nadmin@r1> show configuration\n" + _PRINTED + _TRAILER).replace(
        "\n", "\r\n",
    ),
    "a pager's prompt in it": _PRINTED.replace("    login {\n", "---(more)---\n    login {\n").replace(
        "interfaces {\n", "---(more 62%)---\ninterfaces {\n",
    ),
    "a Markdown fence": "```\n" + _PRINTED + "```\n",
    "a Markdown fence that names it": "```junos\n" + _PRINTED + "```\n",
    "tabs for the indent": _PRINTED.replace("    ", "\t"),
    "a space at the end of every line": _PRINTED.replace("\n", " \n"),
    "last changed, not last commit": _PRINTED.replace("## Last commit:", "## Last changed:"),
}


def test_every_wrapping_is_a_wrapping() -> None:
    """Each text differs from the capture, and the capture is in it."""
    for name, text in WRAPPED.items():
        assert text != _PRINTED, name
        assert "host-name r1;" in text and "address 10.0.0.1/24;" in text, name


@pytest.mark.parametrize("wrapping", sorted(WRAPPED))
def test_a_wrapped_capture_is_its_config(wrapping: str) -> None:
    """With its prompt line first the capture was read as nothing: a
    line that is no statement, ahead of the first block, and the text
    was taken for set-form.  With ``{master:0}`` first it was refused
    as JSON."""
    assert _tree(WRAPPED[wrapping]) == _tree(BARE)
    assert parse_intent(WRAPPED[wrapping]).source_version == "21.4R3.15"


@pytest.mark.parametrize("wrapping", sorted(WRAPPED))
def test_a_wrapped_capture_is_detected(wrapping: str) -> None:
    found = detect_codec(WRAPPED[wrapping])
    assert [candidate.codec for candidate in found][:1] == ["juniper_junos"], found
    assert found[0].confidence >= 86


@pytest.mark.parametrize("wrapping", ["the prompt and the command", "a Virtual Chassis session", "configuration mode"])
def test_set_form_in_a_session_is_read(wrapping: str) -> None:
    """The same lines around ``display set`` output: none of them
    begins ``set``, so they were never read as statements."""
    as_set = _blockform_to_setform(BARE)
    wrapped = WRAPPED[wrapping].replace(_PRINTED, as_set)
    assert as_set in wrapped
    assert not _looks_like_blockform(drop_session_lines(wrapped))
    assert _tree(wrapped) == _tree(BARE)


@pytest.mark.parametrize(
    "line",
    [
        "{master:0}", "{backup}", "{primary:node0}", "{secondary-hold:node1}", "{master:0}[edit]",
        "[edit]", "[edit interfaces ge-0/0/1]", "admin@r1>", "admin@r1> ", "admin@r1# show",
        "admin@r1> show configuration | no-more", "root@r1% cli", "show configuration",
        "show configuration | display set", "---(more)---", "---(more 45%)---", "```", "```junos",
    ],
)
def test_a_line_of_a_session_is_dropped(line: str) -> None:
    for end in ("\n", "\r\n", "  \n"):
        if line.endswith(" ") and end == "  \n":
            continue
        assert drop_session_lines("a;\n" + line + end + "b;\n").split() == ["a;", "b;"], (line, end)
    assert drop_session_lines(line) == ""


@pytest.mark.parametrize(
    "line",
    [
        # A statement, whatever it looks like.
        "    {master:0}", "set system host-name r1", "system {", "    admin@r1> show configuration",
        "show configuration {", "show configuration;", "{", "{master:0} {", "[edit", "{Master:0}",
        "admin@r1>show", "admin@ r1>", "--- (more) ---", "interfaces { ge-0/0/1 { unit 0; } }", "````",
        '{"master": 0}', "<*> {", "## Last commit: 2024-01-01 00:00:00 UTC by admin",
    ],
)
def test_what_is_no_session_line_stays(line: str) -> None:
    text = "a;\n" + line + "\nb;\n"
    assert drop_session_lines(text) == text


def test_a_prompt_and_a_long_line_stays() -> None:
    """A prompt and then more than a command's length of text is not
    a line this knows, and is left where it is."""
    line = "admin@r1> " + "x" * 401
    assert drop_session_lines(line + "\n") == line + "\n"
    assert drop_session_lines("admin@r1> " + "x" * 400 + "\n") == "\n"


def test_a_session_and_no_config_is_empty() -> None:
    with pytest.raises(ParseError, match="empty input"):
        parse_intent("{master:0}\nadmin@r1> show configuration\n\n{master:0}\nadmin@r1> \n")


def test_a_group_wildcard_is_not_xml() -> None:
    """``<ge-0/0/*> {`` among the first lines was taken for the root
    element of a document, and the config was refused."""
    tree = parse_intent(
        "version 21.4R3.15;\ngroups {\n    g {\n        interfaces {\n            <ge-0/0/*> {\n"
        "                mtu 9000;\n            }\n        }\n    }\n}\nsystem {\n    host-name r1;\n}\n"
    )
    assert tree.hostname == "r1"
    with pytest.raises(ParseError, match="looks like XML"):
        parse_intent("<config>\n  <system/>\n</config>\n")


# ---------------------------------------------------------------------------
# Braces that do not pair, comments that do not close
# ---------------------------------------------------------------------------


def test_a_stray_closing_brace_is_refused() -> None:
    """It was read as the end of the text, and everything after it
    was left out with no word said."""
    text = "system {\n    host-name r1;\n}\n}\ninterfaces {\n    ge-0/0/1 {\n        mtu 9000;\n    }\n}\n"
    with pytest.raises(ParseError, match="closes a block that was never opened"):
        parse_intent(text)


def test_no_semicolon_closes_one_block() -> None:
    """Before a ``}`` the ``;`` may be missing (two of the vendor's own
    samples print it so).  The brace then closed its block AND the one
    around it, and what followed was read a level out."""
    text = (
        "system {\n    login {\n        message \"hello\"\n    }\n    host-name r1;\n}\n"
        "interfaces {\n    ge-0/0/1 {\n        mtu 9000;\n    }\n}\n"
    )
    assert _blockform_to_setform(text).splitlines() == [
        'set system login message "hello"',
        "set system host-name r1",
        "set interfaces ge-0/0/1 mtu 9000",
    ]
    assert parse_intent(text).hostname == "r1"


def test_a_block_left_open_is_refused() -> None:
    with pytest.raises(ParseError, match="unbalanced braces"):
        parse_intent("system {\n    host-name r1;\ninterfaces {\n    ge-0/0/1 {\n        mtu 9000;\n    }\n}\n")


def test_an_unclosed_comment_is_refused() -> None:
    """Read as a comment to the end of the text, everything after it
    would be left out in silence."""
    text = "system {\n    host-name r1;\n}\n/* never closed\ninterfaces {\n    ge-0/0/1 {\n        mtu 9000;\n    }\n}"
    with pytest.raises(ParseError, match="opened and never closed"):
        parse_intent(text)


def test_an_open_comment_first_is_set_form() -> None:
    """Ahead of any block the text is not known to be hierarchical;
    set-form under such a line is read as it was."""
    assert not _looks_like_blockform("/* never closed\nsystem {\n    host-name r1;\n}\n")
    assert parse_intent("/* never closed\nset system host-name r1\nset system services ssh;\n# {\n").hostname == "r1"


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("a b; ## c d\ne;", ["a", "b", ";", "e", ";"]),
        ("a b; # c d\ne;", ["a", "b", ";", "e", ";"]),
        ("a { ## c; d\ne; }", ["a", "{", "e", ";", "}"]),
        ("a b; ## c /* d\ne; /* f */ g;", ["a", "b", ";", "e", ";", "g", ";"]),
        # Not where a statement could begin: a character of a value.
        ("a #1;\nb;", ["a", "#1", ";", "b", ";"]),
        ("a b#c;", ["a", "b#c", ";"]),
        ("a http://example.net/page#frag;", ["a", "http://example.net/page#frag", ";"]),
        ('a "b # c";', ["a", '"b # c"', ";"]),
        # ``/*`` only where a token could begin.
        ("member ge-0/*/*;\n/* c */ d;", ["member", "ge-0/*/*", ";", "d", ";"]),
        ("<*/*> { a; } /* c */", ["<*/*>", "{", "a", ";", "}"]),
        ('a "/* b */";', ["a", '"/* b */"', ";"]),
        ("a /* b */ c;", ["a", "c", ";"]),
        ("a/* b */c;", ["a/*", "b", "*/c", ";"]),
        ("/* a; { */ b;", ["b", ";"]),
        # The one comment that is kept: a value the viewer is not shown.
        ("a /* SECRET-DATA */;", ["a", "/*", "SECRET-DATA", "*/", ";"]),
        ("/* SECRET-DATA */ a;", ["a", ";"]),
        ("a; ##", ["a", ";"]),
    ],
)
def test_where_a_comment_begins(text: str, words: list[str]) -> None:
    from netcanon.migration.codecs.juniper_junos.parse import _tokenise_blockform

    assert _tokenise_blockform(text) == words


# ---------------------------------------------------------------------------
# What detection takes for the hierarchical form
# ---------------------------------------------------------------------------

_LAST_COMMIT = "## Last commit: 2024-01-01 00:00:00 UTC by admin\n"


def _probe(text: str):
    return get_codec("juniper_junos").probe(text)


def test_the_scores_are_above_every_floor() -> None:
    """The migrate page asks detection for 40 and over, and
    ``best_codec`` for 50: a score under either is a codec that is
    not offered.  The last-commit line is also above what set-form
    scores (88, 90), and under a RANCID header (97)."""
    with_line, without = _probe(_PRINTED), _probe(BARE)
    assert with_line is not None and with_line[0] == 92
    assert without is not None and without[0] == 86
    assert 50 < without[0] < 88 < 90 < with_line[0] < 97


@pytest.mark.parametrize(
    "text",
    [
        _LAST_COMMIT,
        _LAST_COMMIT + "This page shows what the first line of a capture looks like.\n",
        "```\n" + _LAST_COMMIT + "```\n",
        # Another vendor's config with the line put on it.
        _LAST_COMMIT + "hostname sw1\ninterface Ethernet1\n   description x\n!\n",
        # Blocks and no statement that ends in ``;``: VyOS.
        _LAST_COMMIT + "system {\n    host-name r1\n}\n",
        # Statements that end in ``;`` and no block.
        _LAST_COMMIT + "option domain-name \"example.net\";\n",
    ],
)
def test_last_commit_alone_is_no_junos(text: str) -> None:
    """The line is a comment.  It counted for 92 by itself, above
    every other codec's score for its own capture."""
    assert _probe(text) is None


def test_last_commit_over_set_form_counts() -> None:
    found = _probe(_LAST_COMMIT + "set system host-name r1\n")
    assert found is not None and found[0] == 92


@pytest.mark.parametrize(
    "text",
    [
        "version 21.4R3.15;\n",
        "    host-name r1;\n",
        "system {\n",
        # ``system {`` and no statement that ends in ``;``.
        "system {\n    host-name r1\n}\n",
    ],
)
def test_one_sign_is_not_enough(text: str) -> None:
    assert _probe(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "version 21.4R3.15;\nsystem {\n    services {\n        ssh;\n    }\n}\n",
        'version "8.2I0 [builder]";\nsystem {\n    services {\n        ssh;\n    }\n}\n',
        "groups {\n    re0 {\n        system {\n            host-name r1;\n        }\n    }\n}\nversion 21.4R3.15;\n",
    ],
)
def test_two_signs_are(text: str) -> None:
    for form in (text, text.replace("\n", "\r\n")):
        found = _probe(form)
        assert found is not None and found[0] == 86, form


def test_a_quoted_version_is_read() -> None:
    printed = 'version "8.2I0 [builder]";\nsystem {\n    host-name r1;\n}\n'
    assert parse_intent(printed).source_version == "8.2I0 [builder]"
    assert parse_intent('set version "8.2I0 [builder]"\nset system host-name r1\n').source_version == "8.2I0 [builder]"
    assert parse_intent("set version 21.4R3.15\nset system host-name r1\n").source_version == "21.4R3.15"
