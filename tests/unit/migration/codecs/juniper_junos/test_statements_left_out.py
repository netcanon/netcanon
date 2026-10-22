"""What a Junos config holds and does not run, and how a job says so.

``deactivate <path>`` (``inactive:`` in the hierarchical form) marks a
statement the device ignores, with everything under it.  It is left
out of the translation and named in the list of what was not
translated.  Each form has its twin typed out in
``test_two_forms_one_tree.py``; what is here is what a pair does not
show:

* which line decides when a script says ``deactivate`` and
  ``activate`` both;
* what an applied group or an interface-range gives to a path that is
  deactivated where it is filled;
* what the row shows, and that it shows no secret;
* that a row for a statement left out is not taken for a sign that
  the parser recognised the text.
"""

from __future__ import annotations

import logging

import pytest

from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    is_left_out_row,
    left_out_row,
    left_out_rows,
)
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.juniper_junos import parse as junos_parse
from netcanon.migration.codecs.juniper_junos.parse import _blockform_to_setform, parse_intent
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

_WHY = " (deactivated in the source; not translated)"


def _parse(text: str):
    return get_codec("juniper_junos").parse(text)


def _plan(text: str, target: str = "arista_eos"):
    return run_plan_with_overrides(
        get_codec("juniper_junos"), get_codec(target), text, port_rename_map={}, force=True,
    )


def _addresses(tree) -> set[str]:
    return {address.ip for iface in tree.interfaces for address in iface.ipv4_addresses}


def _config(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Which line decides
# ---------------------------------------------------------------------------

_PORTS = (
    "set system host-name r1",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24",
    "set interfaces ge-0/0/2 description second",
    "set interfaces ge-0/0/2 mtu 9000",
    "set interfaces ge-0/0/2 unit 0 family inet address 10.2.2.1/24",
    "set interfaces ge-0/0/20 unit 0 family inet address 10.20.20.1/24",
)


def test_the_later_line_decides() -> None:
    """``activate`` takes back a ``deactivate`` that came before it,
    and not one that comes after."""
    tree = _parse(_config(
        *_PORTS,
        "deactivate interfaces ge-0/0/1", "activate interfaces ge-0/0/1",
        "activate interfaces ge-0/0/2", "deactivate interfaces ge-0/0/2",
    ))
    assert _addresses(tree) == {"10.1.1.1", "10.20.20.1"}
    assert tree.dropped_tier3_sections == ["inactive: interfaces ge-0/0/2" + _WHY]


def test_a_path_has_one_row() -> None:
    tree = _parse(_config(*_PORTS, "deactivate interfaces ge-0/0/2"))
    assert tree.dropped_tier3_sections == ["inactive: interfaces ge-0/0/2" + _WHY]


@pytest.mark.parametrize("first", [True, False])
def test_where_deactivate_stands_is_all_one(first: bool) -> None:
    """``display set`` prints it after the statement's own lines; a
    hand may put it anywhere."""
    line = "deactivate interfaces ge-0/0/2"
    tree = _parse(_config(line, *_PORTS) if first else _config(*_PORTS, line))
    assert _addresses(tree) == {"10.1.1.1", "10.20.20.1"}


def test_rows_are_in_the_order_of_the_text() -> None:
    tree = _parse(_config(
        *_PORTS, "deactivate system", "deactivate interfaces ge-0/0/20", "deactivate interfaces ge-0/0/1",
    ))
    assert tree.dropped_tier3_sections == [
        "inactive: system" + _WHY,
        "inactive: interfaces ge-0/0/1" + _WHY,
        "inactive: interfaces ge-0/0/20" + _WHY,
    ]


def test_a_path_with_no_lines_is_not_a_row() -> None:
    tree = _parse(_config(*_PORTS, "deactivate interfaces ge-0/0/9"))
    assert tree.dropped_tier3_sections == []
    assert _addresses(tree) == {"10.1.1.1", "10.2.2.1", "10.20.20.1"}


# ---------------------------------------------------------------------------
# What a group or a range gives to a deactivated path
# ---------------------------------------------------------------------------

_GROUP = (
    "set system host-name r1",
    "set groups G interfaces ge-0/0/1 description from-the-group",
    "set groups G interfaces ge-0/0/1 unit 0 family inet address 10.9.9.1/24",
    "set groups G interfaces ge-0/0/3 unit 0 family inet address 10.9.3.1/24",
)


def test_a_group_fills_no_deactivated_unit() -> None:
    """Deactivated where it is filled, a path takes nothing from a
    group either.  The unit is; the port is not, and its description
    comes from the group as before."""
    tree = _parse(_config(
        *_GROUP, "set apply-groups G",
        "set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/24",
        "deactivate interfaces ge-0/0/1 unit 0",
    ))
    assert _addresses(tree) == {"10.9.3.1"}
    port = next(iface for iface in tree.interfaces if iface.name == "ge-0/0/1")
    assert port.description == "from-the-group"
    assert tree.dropped_tier3_sections == ["inactive: interfaces ge-0/0/1 unit 0" + _WHY]
    # And the group that is written to a Junos target does not have
    # the line: applied there, it would fill the unit after all.
    assert tree.group_content == {"G": [
        ["interfaces", "ge-0/0/1", "description", "from-the-group"],
        ["interfaces", "ge-0/0/3", "unit", "0", "family", "inet", "address", "10.9.3.1/24"],
    ]}


def test_a_job_agrees_with_its_own_row() -> None:
    """The row said the port was not translated, and the output
    configured it from the group."""
    job = _plan(_config(
        *_GROUP, "set apply-groups G",
        "set interfaces ge-0/0/1 mtu 9000", "deactivate interfaces ge-0/0/1",
    ), target="juniper_junos")
    assert job.dropped_tier3_sections == ["inactive: interfaces ge-0/0/1" + _WHY]
    assert "ge-0/0/1" not in job.rendered
    assert "10.9.3.1/24" in job.rendered


def test_an_unapplied_group_makes_no_row() -> None:
    tree = _parse(_config(*_GROUP, "deactivate interfaces ge-0/0/1"))
    assert tree.dropped_tier3_sections == []
    assert tree.interfaces == []


def test_only_emptied_groups_are_dropped() -> None:
    """A group whose every line was left out is not applied: kept,
    ``set apply-groups G`` was written to a Junos target that was
    given no group ``G``.  A group that never had a line here stays,
    as it always did."""
    text = _config(
        "set system host-name r1",
        "set groups GONE interfaces ge-0/0/1 mtu 9000",
        "set groups HALF interfaces ge-0/0/2 mtu 9000",
        "set groups HALF interfaces ge-0/0/3 mtu 9000",
        "set apply-groups GONE", "set apply-groups HALF", "set apply-groups ELSEWHERE",
        "deactivate groups GONE", "deactivate groups HALF interfaces ge-0/0/2",
    )
    tree = _parse(text)
    assert tree.apply_groups == ["HALF", "ELSEWHERE"]
    rendered = _plan(text, target="juniper_junos").rendered.splitlines()
    assert "set apply-groups HALF" in rendered and "set apply-groups ELSEWHERE" in rendered
    assert not [line for line in rendered if "GONE" in line]


def test_a_group_under_a_port_left_out_is_gone() -> None:
    """The same for a group whose lines are all under a path that is
    deactivated at the TOP level: what it gave is left out with the
    port, nothing of it is left, and it is not applied."""
    text = _config(
        "set system host-name r1",
        "set groups G interfaces ge-0/0/1 unit 0 family inet address 10.9.9.1/24",
        "set apply-groups G",
        "deactivate interfaces ge-0/0/1",
    )
    tree = _parse(text)
    assert tree.apply_groups == [] and not tree.interfaces
    rendered = _plan(text, target="juniper_junos").rendered
    assert "apply-groups" not in rendered and "10.9.9.1" not in rendered


_RANGE = (
    "set system host-name r1",
    "set interfaces interface-range R member ge-0/0/1",
    "set interfaces interface-range R member ge-0/0/2",
    "set interfaces interface-range R description from-the-range",
    "set interfaces interface-range R mtu 9100",
    "set interfaces interface-range R disable",
    "set interfaces interface-range R unit 0 family inet address 10.50.0.1/24",
    "set interfaces interface-range R unit 0 family inet6 address 2001:db8::1/64",
)


def _port(tree, name: str) -> tuple:
    port = next(iface for iface in tree.interfaces if iface.name == name)
    return (
        port.description, port.mtu, port.enabled,
        [address.ip for address in port.ipv4_addresses], [address.ip for address in port.ipv6_addresses],
    )


# The range's ``mtu 9100`` is a media MTU; the tree's is the payload,
# 14 bytes less (``MTU_BEYOND_THE_PAYLOAD`` in ``codecs/_helpers.py``).
_ALL_OF_IT = ("from-the-range", 9086, False, ["10.50.0.1"], ["2001:db8::1"])


@pytest.mark.parametrize(
    ("deactivated", "first_port"),
    [
        ("interfaces ge-0/0/1 description", ("", 9086, False, ["10.50.0.1"], ["2001:db8::1"])),
        ("interfaces ge-0/0/1 mtu", ("from-the-range", None, False, ["10.50.0.1"], ["2001:db8::1"])),
        ("interfaces ge-0/0/1 disable", ("from-the-range", 9086, True, ["10.50.0.1"], ["2001:db8::1"])),
        ("interfaces ge-0/0/1 unit 0", ("from-the-range", 9086, False, [], [])),
        ("interfaces ge-0/0/1 unit 0 family inet", ("from-the-range", 9086, False, [], ["2001:db8::1"])),
        ("interfaces ge-0/0/1 unit 0 family inet6", ("from-the-range", 9086, False, ["10.50.0.1"], [])),
    ],
)
def test_a_range_fills_nothing_deactivated(deactivated: str, first_port: tuple) -> None:
    """What a range gives a member goes where the member's own
    statement would, so under a deactivated path it is not in force.
    The other member has all of it."""
    tree = _parse(_config(*_RANGE, "deactivate " + deactivated))
    assert _port(tree, "ge-0/0/1") == first_port
    assert _port(tree, "ge-0/0/2") == _ALL_OF_IT
    assert tree.dropped_tier3_sections == [f"inactive: {deactivated}" + _WHY]


def test_a_deactivated_member_gets_nothing() -> None:
    tree = _parse(_config(*_RANGE, "deactivate interfaces ge-0/0/1"))
    assert [iface.name for iface in tree.interfaces] == ["ge-0/0/2"]
    assert _port(tree, "ge-0/0/2") == _ALL_OF_IT
    assert tree.dropped_tier3_sections == ["inactive: interfaces ge-0/0/1" + _WHY]


def test_a_range_is_as_it_was_otherwise() -> None:
    tree = _parse(_config(*_RANGE))
    assert _port(tree, "ge-0/0/1") == _port(tree, "ge-0/0/2") == _ALL_OF_IT
    assert tree.dropped_tier3_sections == []


# ---------------------------------------------------------------------------
# The tags of the hierarchical form
# ---------------------------------------------------------------------------

_PORT = "system {\n    host-name r1;\n}\ninterfaces {\n    ge-0/0/1 {\n        mtu 9000;\n%s    }\n}\n"


@pytest.mark.parametrize("stray", ["        inactive:\n", "        inactive: ;\n", "        inactive: [ a b ];\n"])
def test_a_tag_naming_nothing_takes_nothing(stray: str) -> None:
    """A tag is on the statement after it.  With no statement there --
    or one that has no word to be named by -- nothing is deactivated,
    least of all the block the tag stands in."""
    lines = _blockform_to_setform(_PORT % stray).splitlines()
    assert lines == ["set system host-name r1", "set interfaces ge-0/0/1 mtu 9000"]
    tree = _parse(_PORT % stray)
    # The media MTU less the Ethernet header: the tree's MTU is the payload.
    assert [(iface.name, iface.mtu) for iface in tree.interfaces] == [("ge-0/0/1", 8986)]
    assert tree.dropped_tier3_sections == []


def test_a_tag_on_a_nameless_block_refused() -> None:
    """``inactive: {``: read on, what is in the braces was in force
    under the statement above them."""
    for nameless in ("inactive: {", "inactive: [ a b ] {", "delete: {"):
        with pytest.raises(ParseError, match="ahead of a block that has no name"):
            parse_intent(_PORT % f"        {nameless}\n            description x;\n        }}\n")


def test_a_tag_is_only_the_first_word() -> None:
    tree = _parse(_PORT % "        description inactive:;\n")
    assert tree.interfaces[0].description == "inactive:"
    assert tree.dropped_tier3_sections == []


@pytest.mark.parametrize("tags", ["inactive: delete:", "delete: inactive:"])
def test_delete_says_more_than_inactive(tags: str) -> None:
    """Both on one statement, in either order: it is marked for
    deletion."""
    text = _PORT.replace("    ge-0/0/1 {", f"    {tags} ge-0/0/1 {{") % ""
    tree = _parse(text)
    assert tree.interfaces == []
    assert tree.dropped_tier3_sections == [
        "delete: interfaces ge-0/0/1 (marked for deletion in a load file; not translated)",
    ]


# ---------------------------------------------------------------------------
# What a row shows
# ---------------------------------------------------------------------------


def test_a_leaf_is_named_by_its_first_word() -> None:
    """What follows the first word of a leaf is its value, and a
    value may be a secret under a word nobody thought to list.
    ``display set`` names a deactivated leaf the same way.  It is the
    whole statement that is left out, and only it: the other route
    stays."""
    text = "\n".join([
        "system {", "    host-name r1;", "}",
        "routing-options {", "    static {",
        "        inactive: route 0.0.0.0/0 next-hop 10.0.0.254;",
        "        route 10.9.0.0/16 next-hop 10.0.0.9;",
        "    }", "}", "",
    ])
    tree = _parse(text)
    assert [route.destination for route in tree.static_routes] == ["10.9.0.0/16"]
    assert tree.dropped_tier3_sections == ["inactive: routing-options static route" + _WHY]


_SECRETS = {
    "a community, set form": (
        "fakeCommunityString",
        _config(
            "set system host-name r1",
            "set snmp community fakeCommunityString authorization read-only",
            "deactivate snmp community fakeCommunityString",
        ),
        "inactive: snmp community ...",
    ),
    "a community, as printed": (
        "fakeCommunityString",
        "system {\n    host-name r1;\n}\nsnmp {\n    inactive: community fakeCommunityString {\n"
        "        authorization read-only;\n    }\n}\n",
        "inactive: snmp community ...",
    ),
    "a user's hash": (
        "$6$fake$notARealHash",
        "system {\n    host-name r1;\n    login {\n        user bob {\n            class super-user;\n"
        "            authentication {\n"
        '                inactive: encrypted-password "$6$fake$notARealHash"; ## SECRET-DATA\n'
        "            }\n        }\n    }\n}\n",
        "inactive: system login user bob authentication ...",
    ),
    "a user's hash, set form": (
        "$6$fake$notARealHash",
        _config(
            "set system host-name r1", "set system login user bob class super-user",
            'set system login user bob authentication encrypted-password "$6$fake$notARealHash"',
            'deactivate system login user bob authentication encrypted-password "$6$fake$notARealHash"',
        ),
        "inactive: system login user bob authentication ...",
    ),
    "a BGP key": (
        "$9$fakeNotAKey",
        "system {\n    host-name r1;\n}\nprotocols {\n    bgp {\n        group X {\n"
        '            inactive: authentication-key "$9$fakeNotAKey"; ## SECRET-DATA\n'
        "        }\n    }\n}\n",
        "inactive: protocols bgp group X authentication-key",
    ),
    "a RADIUS secret": (
        "$9$fakeSharedSecret",
        "system {\n    host-name r1;\n    radius-server {\n        192.0.2.9 {\n"
        '            inactive: secret "$9$fakeSharedSecret"; ## SECRET-DATA\n'
        "        }\n    }\n}\n",
        "inactive: system radius-server 192.0.2.9 secret",
    ),
    "a pre-shared key": (
        "$9$fakePreSharedKey",
        "system {\n    host-name r1;\n}\nsecurity {\n    ike {\n        policy P {\n"
        '            inactive: pre-shared-key ascii-text "$9$fakePreSharedKey"; ## SECRET-DATA\n'
        "        }\n    }\n}\n",
        "inactive: security ike policy P pre-shared-key",
    ),
    "a value under a word nobody lists": (
        "fakeValueNobodyLists",
        "system {\n    host-name r1;\n    inactive: frobnicate fakeValueNobodyLists;\n}\n",
        "inactive: system frobnicate",
    ),
    "a key that names its own statement": (
        "fakeLicenceKey",
        _config(
            "set system host-name r1", "set system license keys key fakeLicenceKey",
            "deactivate system license keys key fakeLicenceKey",
        ),
        "inactive: system license keys ...",
    ),
}


@pytest.mark.parametrize("case", sorted(_SECRETS))
def test_a_row_names_no_secret(case: str, caplog: pytest.LogCaptureFixture) -> None:
    """The row was the path, and a path is keyed by its secret often
    enough.  The value is in no field of the job, and in no log."""
    secret, text, row = _SECRETS[case]
    assert secret in text
    with caplog.at_level(logging.DEBUG):
        tree = _parse(text)
        job = _plan(text)
    assert tree.dropped_tier3_sections == [row + _WHY]
    assert job.dropped_tier3_sections == [row + _WHY]
    assert secret not in job.model_dump_json()
    assert secret not in " ".join([*job.dropped_tier3_sections, *job.warnings, job.error or ""])
    assert not [record for record in caplog.records if secret in record.getMessage()]
    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        (("interfaces", "ge-0/0/2"), "interfaces ge-0/0/2"),
        (("snmp", "community", "fakeCommunity"), "snmp community ..."),
        # Nothing follows the word: nothing to cut.
        (("snmp", "community"), "snmp community"),
        (("system", "login", "user", "bob", "authentication", "encrypted-password", "$6$fake$hash"),
         "system login user bob authentication ..."),
        (("system", "radius-server", "192.0.2.9", "secret", "$9$fakeSecret"),
         "system radius-server 192.0.2.9 secret ..."),
        (("security", "ike", "policy", "P", "pre-shared-key", "ascii-text", "$9$fakePsk"),
         "security ike policy P pre-shared-key ..."),
        (("access", "profile", "P", "client", "c", "chap-secret", "$9$fakeChap"),
         "access profile P client c chap-secret ..."),
        (("wlan", "PSK", "fakePassphrase"), "wlan PSK ..."),
        (("system", "ntp", "authentication-key", "1", "value", "$9$fakeNtp"), "system ntp authentication-key ..."),
        (("policy-options", "policy-statement", "direct routes"), 'policy-options policy-statement "direct routes"'),
        (("system", "login", "message", ""), 'system login message ""'),
    ],
)
def test_the_row_of_a_path(path: tuple[str, ...], shown: str) -> None:
    assert left_out_row("inactive", path) == f"inactive: {shown}" + _WHY


def test_statements_that_read_alike_share_a_row() -> None:
    """The value of a leaf is left out of its row, so two deactivated
    servers gave one row twice.  One row, and it says how many."""
    text = _config(
        "system {", "    host-name r1;", "    ntp {",
        "        inactive: server 10.0.0.1;", "        inactive: server 10.0.0.2;",
        "        server 10.0.0.3;", "    }", "}",
    )
    tree = _parse(text)
    assert tree.dropped_tier3_sections == [
        "inactive: system ntp server (deactivated in the source; not translated; 2 statements)",
    ]
    assert tree.ntp_servers == ["10.0.0.3"]


def test_the_rows_are_bounded() -> None:
    """The list is in every answer.  Past the bound one row counts
    what is not listed, and it is a row like the others to every
    reader of the list."""
    more = 50
    ports = [f"ge-0/0/{number}" for number in range(LEFT_OUT_ROWS_SHOWN + more)]
    tree = _parse(_config(
        "set system host-name r1",
        *(f"set interfaces {port} mtu 9000" for port in ports),
        *(f"deactivate interfaces {port}" for port in ports),
    ))
    rows = tree.dropped_tier3_sections
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 1
    assert rows[0] == "inactive: interfaces ge-0/0/0" + _WHY
    assert rows[-1] == f"inactive: ... ({more} more statements left out; not listed)"
    assert all(is_left_out_row(row) for row in rows) and not tree.interfaces


def test_the_rest_is_counted_in_statements() -> None:
    alike = [("inactive", ("system", "ntp", "server"))] * 3
    others = [("inactive", ("interfaces", f"ge-0/0/{number}")) for number in range(LEFT_OUT_ROWS_SHOWN)]
    rows = left_out_rows([*others, *alike, ("delete", ("protocols", "bgp"))])
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 1
    assert rows[-1] == "inactive: ... (4 more statements left out; not listed)"
    assert left_out_rows([]) == []


def test_a_left_out_row_is_told_apart() -> None:
    assert is_left_out_row(left_out_row("inactive", ("interfaces", "ge-0/0/2")))
    assert is_left_out_row(left_out_row("delete", ("snmp",)))
    assert is_left_out_row(left_out_row("preconfigure", ("interface", "TenGigE0/0/0/12")))
    assert not is_left_out_row("set firewall family inet filter PROTECT")
    assert not is_left_out_row("ip access-list extended INACTIVE")


# ---------------------------------------------------------------------------
# A row is not a sign that the text was recognised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "hello world\nset foo bar\ndeactivate foo\n",
        # Statements the model does not have.
        "set chassis cluster reth-count 2\ndeactivate chassis cluster\n",
    ],
)
def test_no_config_is_not_completed(text: str) -> None:
    """The parser names a deactivated path whether or not any handler
    would have read a line under it, and one such row said the text
    had been recognised: ``completed``, with nothing in it."""
    job = _plan(text)
    assert job.status.value == "partial"
    assert job.error is not None and job.error.startswith("No source constructs were recognized")
    assert "statements the source held and did not run" in job.error
    assert len(job.dropped_tier3_sections) == 1 and is_left_out_row(job.dropped_tier3_sections[0])


def test_nor_is_all_of_it_deactivated() -> None:
    job = _plan(_config(*_PORTS, "deactivate system", "deactivate interfaces"))
    assert job.status.value == "partial"
    assert job.error is not None and "statements the source held and did not run" in job.error
    assert len(job.dropped_tier3_sections) == 2


def test_a_config_in_force_is_completed() -> None:
    job = _plan(_config(*_PORTS, "deactivate interfaces ge-0/0/2"))
    assert job.status.value == "completed" and job.error is None


def test_sections_beside_a_row_say_it_was_read() -> None:
    """A section the tool does not translate says the text was read,
    and a row for a statement left out beside it does not unsay
    that: asked whether ANY row is such a row, where the question
    is whether ALL are, a firewall's config with one deactivated
    statement was "not recognized"."""
    job = _plan(_config(
        "set firewall family inet filter F term 1 then accept",
        "set security nat source rule-set R from zone trust",
        "deactivate security nat",
    ))
    assert job.status.value == "completed" and job.error is None
    assert [is_left_out_row(row) for row in job.dropped_tier3_sections] == [True, False]


def test_sections_alone_say_it_was_read() -> None:
    """A config that is all firewall: nothing translated, and rows
    that say why."""
    job = _plan("set firewall family inet filter F term 1 then accept\n")
    assert job.status.value == "completed"
    assert job.dropped_tier3_sections == ["set firewall family inet filter F"]


# ---------------------------------------------------------------------------
# The paths, asked directly
# ---------------------------------------------------------------------------

_HELD = {("interfaces", "ge-0/0/2"), ("interfaces", "ge-0/0/3", "unit", "0"), ("system",), ("system", "login")}


def _asked(paths) -> None:
    assert paths.over(["interfaces", "ge-0/0/2", "mtu", "9000"]) == ("interfaces", "ge-0/0/2")
    assert paths.over(["interfaces", "ge-0/0/2"]) == ("interfaces", "ge-0/0/2")
    assert paths.over(["interfaces", "ge-0/0/3", "unit", "0", "family"]) == ("interfaces", "ge-0/0/3", "unit", "0")
    # By whole words, and all of them.
    assert paths.over(["interfaces", "ge-0/0/20", "mtu", "9000"]) is None
    assert paths.over(["interfaces", "ge-0/0/3", "unit", "1"]) is None
    assert paths.over(["interfaces"]) is None
    assert paths.over(["vlans", "ge-0/0/2"]) is None
    assert paths.over([]) is None
    # The shortest: what is under it is under the longer one too.
    assert paths.over(["system", "login", "user", "bob"]) == ("system",)
    assert paths.over(("system",)) == ("system",)


def test_the_shortest_path_is_the_one() -> None:
    paths = junos_parse._Paths(_HELD)
    assert paths
    _asked(paths)
    assert not junos_parse._Paths(set())
    assert not junos_parse._Paths({()})


def test_two_paths_on_one_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """A path is found by a number folded from its words, and two
    paths may fold to one number.  Here every path does: a path that
    is found is compared word for word before it is believed."""
    monkeypatch.setattr(junos_parse, "hash", lambda _folded: 7, raising=False)
    _asked(junos_parse._Paths(_HELD))
