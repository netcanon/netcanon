"""A VyOS node with nothing under it is printed on one line, and read so.

VyOS prints a node that holds nothing as ``<head> { }``:
``server time1.vyos.net { }``, ``loopback lo { }``, ``disable { }``
(the committed ``houdev_vyos_dhcpv6_pd_client.conf`` has each).  The
parser opened a block only at a line that ENDS in ``{``, so it read
such a line as a leaf whose value ran to the end of the line: the NTP
server ``time1.vyos.net { }``, written with its braces onto every
target (``ntp server time1.vyos.net { }``); an empty ``loopback lo``
that was no interface; a ``vif`` or a ``next-hop`` with nothing under
it, nothing at all.

The reading this module holds the parser to is the one the set-form
reader gives the same path, typed here by hand in the other grammar:
a head of two words is a tag node that opens and closes, and a head of
one word is that leaf with no value where the word is a leaf
(``disable``), or else an empty container.

The output is read twice on every public codec: by the target's own
parser, and as text, for a name with a brace after it.  Each check is
handed what the parser made before the change, and fails.

See also:

* ``tests/unit/migration/test_vyos.py`` -- the codec's own tests.
* ``docs/vendors/vyos.md`` -- the operator page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit

_REAL = Path(__file__).resolve().parents[2] / "fixtures" / "real" / "vyos"
_SYNTHETIC = (
    Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "vyos"
)

_NAMES = ["time1.example.net", "time2.example.net"]

#: Each node with nothing under it, as the device prints it.
_PRINTED = """\
interfaces {
    ethernet eth0 {
        address "192.0.2.1/24"
        disable { }
        vif 100 { }
    }
    ethernet eth1 {
        address "198.51.100.1/24"
    }
    loopback     lo { }
}
protocols {
    static {
        route 203.0.113.0/24 {
            next-hop 192.0.2.254 { }
        }
    }
}
system {
    host-name "edge"
    ntp {
        server         time1.example.net { }
        server         time2.example.net { }
    }
}
"""

#: The same config in the other grammar VyOS prints, typed by hand.
_SET_FORM = """\
set interfaces ethernet eth0 address '192.0.2.1/24'
set interfaces ethernet eth0 disable
set interfaces ethernet eth0 vif 100
set interfaces ethernet eth1 address '198.51.100.1/24'
set interfaces loopback lo
set protocols static route 203.0.113.0/24 next-hop 192.0.2.254
set system host-name 'edge'
set system ntp server time1.example.net
set system ntp server time2.example.net
"""

#: Public codecs that render no NTP server at all (a capability gap of
#: the target, declared in its matrix), typed by hand.
_NO_NTP = {"aruba_aoscx", "cisco_iosxe", "dell_os10", "opnsense"}


def _parse(text: str) -> CanonicalIntent:
    return get_codec("vyos").parse(text)


def _shape(tree: CanonicalIntent) -> dict:
    return {
        "hostname": tree.hostname,
        "ntp": list(tree.ntp_servers),
        "interfaces": sorted(
            (i.name, i.enabled, i.dot1q_vlan,
             tuple(f"{a.ip}/{a.prefix_length}" for a in i.ipv4_addresses))
            for i in tree.interfaces
        ),
        "routes": sorted(
            (r.destination, r.gateway) for r in tree.static_routes
        ),
    }


#: What the parser made of ``_PRINTED`` before the change, typed by hand.
_BEFORE = {
    "hostname": "edge",
    "ntp": [f"{n} {{ }}" for n in _NAMES],
    "interfaces": [
        ("eth0", False, None, ("192.0.2.1/24",)),
        ("eth1", True, None, ("198.51.100.1/24",)),
    ],
    "routes": [],
}


def _strings(value, path="tree"):
    """Every string a tree holds, with where it is."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k, f"{path}[key]")
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _strings(v, f"{path}[{i}]")


def _braced_strings(tree_dump: dict) -> list[str]:
    return [
        f"{where} = {text!r}"
        for where, text in _strings(tree_dump)
        if re.search(r"\{\s*\}", text)
    ]


def _check_names_in_output(target: str, rendered: str, names: list[str]) -> None:
    """The target's parser gives back *names* exactly, and no name is
    followed by a brace in the text."""
    back = list(get_codec(target).parse(rendered).ntp_servers)
    if target in _NO_NTP:
        assert back == [], f"{target}: an NTP server came back: {back}"
        return
    assert back == names, f"{target}: NTP servers read back {back}, not {names}"
    for line in rendered.splitlines():
        for name in names:
            assert not re.search(re.escape(name) + r"[^\S\n]*\{", line), (
                f"{target}: the name is written with a brace: {line!r}"
            )


class TestTheTwoForms:
    def test_the_printed_form_reads_as_the_set_form(self):
        assert _shape(_parse(_PRINTED)) == _shape(_parse(_SET_FORM))

    def test_what_the_set_form_gives(self):
        assert _shape(_parse(_SET_FORM)) == {
            "hostname": "edge",
            "ntp": _NAMES,
            "interfaces": [
                ("eth0", False, None, ("192.0.2.1/24",)),
                ("eth0.100", True, 100, ()),
                ("eth1", True, None, ("198.51.100.1/24",)),
                ("lo", True, None, ()),
            ],
            "routes": [("203.0.113.0/24", "192.0.2.254")],
        }

    def test_the_comparison_fails_on_the_old_reading(self):
        assert _shape(_parse(_SET_FORM)) != _BEFORE

    def test_braces_without_a_space(self):
        tight = _PRINTED.replace("{ }", "{}")
        assert _shape(_parse(tight)) == _shape(_parse(_SET_FORM))


class TestEveryCommittedInput:
    @pytest.mark.parametrize(
        "path",
        sorted(_REAL.glob("*.conf")) + sorted(_SYNTHETIC.glob("*.conf")),
        ids=lambda p: p.name,
    )
    def test_no_value_holds_a_brace_pair(self, path):
        tree = _parse(path.read_text(encoding="utf-8"))
        assert _braced_strings(tree.model_dump()) == []

    def test_the_capture_that_prints_them(self):
        text = (_REAL / "houdev_vyos_dhcpv6_pd_client.conf").read_text(
            encoding="utf-8",
        )
        tree = _parse(text)
        assert list(tree.ntp_servers) == [
            "time1.vyos.net", "time2.vyos.net", "time3.vyos.net",
        ]
        assert "lo" in {i.name for i in tree.interfaces}

    def test_the_check_finds_a_braced_value(self):
        tree = _parse(_SET_FORM)
        tree.ntp_servers = [f"{n} {{ }}" for n in _NAMES]
        assert len(_braced_strings(tree.model_dump())) == len(_NAMES)


@pytest.mark.parametrize("target", list_public_codecs())
class TestOntoEveryCodec:
    def test_the_names_reach_the_output(self, target):
        rendered = run_plan(get_codec("vyos"), get_codec(target), _PRINTED).rendered
        _check_names_in_output(target, rendered, _NAMES)

    def test_the_check_fails_on_the_old_tree(self, target):
        if target in _NO_NTP:
            pytest.skip("the target renders no NTP server")
        tree = _parse(_SET_FORM)
        tree.ntp_servers = [f"{n} {{ }}" for n in _NAMES]
        rendered = get_codec(target).render(tree)
        with pytest.raises(AssertionError):
            _check_names_in_output(target, rendered, _NAMES)


def test_the_no_ntp_set_is_what_the_targets_do():
    measured = {
        target
        for target in list_public_codecs()
        if not get_codec(target).parse(
            run_plan(get_codec("vyos"), get_codec(target), _SET_FORM).rendered,
        ).ntp_servers
    }
    assert measured == _NO_NTP
