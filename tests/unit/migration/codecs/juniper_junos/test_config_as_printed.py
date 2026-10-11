"""A Junos config as ``show configuration`` prints it.

The hierarchical form was read -- if it was typed.  What a device
prints begins ``## Last commit: ...`` and ``version 21.4R3.15;``, and
ends its secrets ``## SECRET-DATA``.  The first two made the parser
take the text for set-form, where no line of it is a statement: an
empty config, a job that rendered nothing and said nothing.  The third
was read as a statement, and put every block after it one level out.
And no probe knew the form, so a paste was offered no codec at all.

Each printed form here is compared with the same config written bare,
which is the form the parser has always read.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.juniper_junos.parse import (
    _blockform_to_setform,
    _looks_like_blockform,
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
    assert tree.dropped_tier3_sections[:2] == [
        "inactive: interfaces ge-0/0/2 (deactivated in the source; not translated)",
        'inactive: interfaces ge-0/0/4 description fourth (deactivated in the source; not translated)',
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


def test_the_last_commit_line_alone_is_enough_for_detection() -> None:
    """A capture cut down to one block: no ``version``, no ``system``."""
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
