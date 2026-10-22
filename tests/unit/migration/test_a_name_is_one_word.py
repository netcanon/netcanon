"""A name, an address or a text is written as one value of its place.

The rule of :mod:`netcanon.migration._one_value`, for the values that
are not secrets.  A CLI that reads a line a word at a time reads a VLAN
name ``zq1 zq2`` as the name ``zq1`` and a word ``zq2`` that the place
takes for whatever comes next there; ``ntp server a b`` is a server
``a`` and a keyword.  What each place of each grammar reads is a fact
about the vendor; the references are in
``docs/reviews/2026-10-20-values-with-white-space/``.  Three kinds:

* a NAME that labels (host name, VLAN name, VRF name, route name) may be
  written with ``_`` for each run of white space and ``'`` for a ``"``
  (:func:`~netcanon.migration._one_value.one_word`) -- at EVERY place it
  goes, so that a VRF and the interfaces in it still agree -- and the
  output says so in a review line;
* an ADDRESS (NTP, syslog and DNS servers, a domain, a gateway, a DHCP
  pool's domain, gateway and DNS servers) is not altered: it is left
  out and said, and a static route whose gateway is left out goes WHOLE
  (a route that keeps its destination without its next hop is another
  route);
* a TEXT (a description, an SNMP location or contact) is written to the
  end of the line where the vendor documents that place so (a table
  typed by hand below, from the references), and elsewhere as it stands
  with a review line beside it -- or, where the target quotes with no
  escape, with ``'`` for each ``"`` and a review line.

A VLAN's description is its label, and a target whose VLAN has only
a name (``CodecBase.vlans_have_only_a_name``) writes the label of a
VLAN that has no name of its own AS its name: there it is judged as
a name.

Where the target's grammar quotes, any of the three may be written
between its quotes, with the escape it documents.

For each synthetic kitchen sink each field is set, one at a time, to a
value with white space and to a value with a quote, and the tree is
rendered onto every public codec that writes lines.  The output is read
as TEXT, by a reader this test owns, against the render of the same tree
with a one-word value: a field the target does not write at all is not
judged.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs

_SYNTHETIC = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"

#: Targets whose output is XML: element text holds any value as one.
_XML = {"opnsense", "cisco_iosxe"}

#: Targets whose grammar quotes a value, and the escape each documents
#: for a ``"`` inside one (None: none).
_QUOTES: dict[str, str | None] = {
    "juniper_junos": "\\",
    "fortigate_cli": "\\",
    "mikrotik_routeros": "\\",
    "aruba_aoss": None,
    "vyos": None,
}

#: Targets this guard does not judge yet, and why.  RouterOS writes its
#: values bare on this base; PR #530 quotes every RouterOS value and has
#: a guard of its own.  Whichever of the two merges second takes this
#: entry out.
_NOT_YET = {"mikrotik_routeros"}

#: Targets that quote in some places only: how such a line begins.
#: Dell documents a quoted description, location and contact, and no
#: escape for a ``"`` in one.
_QUOTED_PLACES: dict[str, tuple[str, ...]] = {
    "dell_os10": (
        "description ", "snmp-server location ", "snmp-server contact "),
}

#: Places that read the rest of the line, by target: (the stanza the
#: line is in, or "" for any; how the line begins).  Typed from the
#: vendor references, or from a committed capture whose device prints
#: such a value whole (ruling 1), never from the renderers.
_REST_OF_LINE: dict[str, tuple[tuple[str, str], ...]] = {
    "cisco_iosxe_cli": (
        ("interface ", "description "), ("vrf definition ", "description "),
        ("", "snmp-server contact "), ("", "snmp-server location "),
    ),
    "cisco_nxos": (
        ("interface ", "description "), ("vrf context ", "description "),
        ("", "snmp-server location "),
    ),
    "arista_eos": (
        ("interface ", "description "), ("", "snmp-server contact "),
    ),
    "aruba_aoscx": (
        ("interface ", "description "), ("vlan ", "description "),
        # aoscx_dcn_arch3_ebgp_leaf1a.cfg prints ``name VLAN 11``.
        ("vlan ", "name "),
        ("", "snmp-server system-contact "),
        ("", "snmp-server system-location "),
    ),
    "cisco_iosxr": (("interface ", "description "),),
}

#: The comment markers of the line grammars.
_COMMENT = ("!", "#", "/*", "//", ";")

_ONE_WORD = "zq1"
_SPACED = "zq1 zq2"
_QUOTED = 'zq1"zq2'

#: The destination a route whose gateway is under test is given, so
#: that the route can be found in the output whatever else it holds.
_DEST = "198.51.100.77"


def _first(records: list[Any], field: str, value: str) -> bool:
    if not records:
        return False
    setattr(records[0], field, value)
    return True


def _set(field: str) -> Callable[[Any, str], bool]:
    def setter(tree: Any, value: str) -> bool:
        setattr(tree, field, value)
        return True
    return setter


def _as_list(field: str) -> Callable[[Any, str], bool]:
    def setter(tree: Any, value: str) -> bool:
        setattr(tree, field, [value])
        return True
    return setter


def _named_first(records: list[Any]) -> list[Any]:
    return sorted(records, key=lambda r: not getattr(r, "name", ""))


def _vrf(tree: Any, value: str) -> bool:
    """Rename the first VRF and every reference to it, at once."""
    if not tree.routing_instances:
        return False
    old = tree.routing_instances[0].name
    tree.routing_instances[0].name = value
    for record in (
        *tree.interfaces, *tree.static_routes, *tree.evpn_type5_routes,
    ):
        if record.vrf == old:
            record.vrf = value
    return True


def _gateway(tree: Any, value: str) -> bool:
    routes = [r for r in tree.static_routes if r.gateway]
    if not routes:
        return False
    routes[0].destination = f"{_DEST}/32"
    routes[0].gateway = value
    return True


def _described(tree: Any, value: str) -> bool:
    interfaces = sorted(tree.interfaces, key=lambda i: not i.description)
    return _first(interfaces, "description", value)


def _snmp(field: str) -> Callable[[Any, str], bool]:
    def setter(tree: Any, value: str) -> bool:
        if tree.snmp is None:
            return False
        setattr(tree.snmp, field, value)
        return True
    return setter


def _pool(field: str, as_list: bool = False) -> Callable[[Any, str], bool]:
    def setter(tree: Any, value: str) -> bool:
        if not tree.dhcp_servers:
            return False
        setattr(tree.dhcp_servers[0], field, [value] if as_list else value)
        return True
    return setter


#: field -> (kind, setter).  A setter returns False when the tree has no
#: record to put the value in.
FIELDS: dict[str, tuple[str, Callable[[Any, str], bool]]] = {
    "hostname": ("name", _set("hostname")),
    "vlans[].name": (
        "name", lambda t, v: _first(_named_first(t.vlans), "name", v)),
    "routing_instances[].name": ("name", _vrf),
    "static_routes[].description": (
        "name", lambda t, v: _first(t.static_routes, "description", v)),
    "domain": ("address", _set("domain")),
    "ntp_servers": ("address", _as_list("ntp_servers")),
    "syslog_servers": ("address", _as_list("syslog_servers")),
    "dns_servers": ("address", _as_list("dns_servers")),
    "static_routes[].gateway": ("address", _gateway),
    "dhcp_servers[].domain_name": ("address", _pool("domain_name")),
    "dhcp_servers[].gateway": ("address", _pool("gateway")),
    "dhcp_servers[].dns_servers": ("address", _pool("dns_servers", True)),
    "interfaces[].description": ("text", _described),
    "vlans[].description": (
        "text", lambda t, v: _first(t.vlans, "description", v)),
    "routing_instances[].description": (
        "text", lambda t, v: _first(t.routing_instances, "description", v)),
    "snmp.location": ("text", _snmp("location")),
    "snmp.contact": ("text", _snmp("contact")),
}


def _sources() -> list[str]:
    return [
        name for name in list_public_codecs()
        if list((_SYNTHETIC / name).glob("kitchen_sink.*"))
    ]


_TREES: dict[str, Any] = {}


def _tree(source: str) -> Any:
    if source not in _TREES:
        path = sorted((_SYNTHETIC / source).glob("kitchen_sink.*"))[0]
        _TREES[source] = get_codec(source).parse(
            path.read_text(encoding="utf-8"))
    return copy.deepcopy(_TREES[source])


def _render(source: str, target: str, field: str, value: str) -> str | None:
    tree = _tree(source)
    if not FIELDS[field][1](tree, value):
        return None
    return get_codec(target).render(tree)


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith(_COMMENT)


def _reviews(text: str) -> int:
    return sum(
        1 for line in text.splitlines()
        if _is_comment(line) and "review" in line
    )


_UNQUOTED = object()


def _escape_here(target: str, line: str) -> Any:
    """The escape of the quotes this line's place reads (None: quotes
    with no escape), or ``_UNQUOTED``."""
    if target in _QUOTES:
        return _QUOTES[target]
    if line.strip().startswith(_QUOTED_PLACES.get(target, ())):
        return None
    return _UNQUOTED


def _quoted(escape: Any, value: str) -> list[str]:
    """*value* between quotes that have *escape* for a ``"``."""
    if escape is _UNQUOTED:
        return []
    if '"' in value and escape is None:
        return []
    inner = value
    if escape is not None:
        inner = value.replace(escape, escape * 2).replace('"', escape + '"')
    forms = [f'"{inner}"']
    if '"' not in value:
        forms.append(f"'{value}'")
    return forms


def _relabelled(value: str) -> str:
    """The one word a name is written as, typed here rather than taken
    from the helper the renderers call."""
    return "_".join(value.replace('"', "'").split())


def _lines(text: str) -> list[tuple[str, str]]:
    """Each line that is not a comment, with the stanza it is in."""
    out, stanza = [], ""
    for line in text.splitlines():
        if _is_comment(line) or not line.strip():
            continue
        if not line[:1].isspace():
            stanza = line
        out.append((stanza, line))
    return out


def _rest_of_line(target: str, stanza: str, line: str, value: str) -> bool:
    body = line.strip()
    return body.endswith(value) and any(
        stanza.startswith(where) and body.startswith(begins)
        for where, begins in _REST_OF_LINE.get(target, ())
    )


def _judge(source: str, target: str, field: str, value: str) -> list[str]:
    """What is wrong with the render of *value* in *field*, as text."""
    kind = FIELDS[field][0]
    base = _render(source, target, field, _ONE_WORD)
    if base is None:
        return []
    named = [ln for ln in _lines(base) if _ONE_WORD in ln[1]]
    if not named:
        return []
    out = _render(source, target, field, value)
    assert out is not None
    wrong: list[str] = []
    said = _reviews(out) > _reviews(base)
    apostrophe = value.replace('"', "'")
    written, altered, bare = 0, False, False
    for stanza, line in _lines(out):
        if _ONE_WORD not in line:
            continue
        written += 1
        escape = _escape_here(target, line)
        forms = _quoted(escape, value)
        altered_forms: list[str] = []
        if kind == "name" or (
            field == "vlans[].description"
            and get_codec(target).vlans_have_only_a_name
        ):
            altered_forms = [
                *_quoted(escape, _relabelled(value)), _relabelled(value)]
        elif kind == "text" and '"' in value and escape is _UNQUOTED:
            altered_forms = [apostrophe]
        elif kind == "text" and '"' in value and escape is None:
            # Between the quotes, or bare where it is then one word.
            altered_forms = _quoted(None, apostrophe) + (
                [] if any(ch.isspace() for ch in apostrophe) else [apostrophe])
        rest = line
        for form in forms:
            rest = rest.replace(form, "")
        if _ONE_WORD in rest and kind in ("text", "name") and _rest_of_line(
            target, stanza, rest, value,
        ):
            rest = rest.strip()[: -len(value)]
        for form in altered_forms:
            if form in rest:
                altered = True
                rest = rest.replace(form, "")
        if _ONE_WORD not in rest:
            continue
        if kind == "text" and value in rest and '"' not in value:
            bare = True
            continue
        wrong.append(f"not one value: {line.strip()[:100]}")
    if not written:
        if not said:
            wrong.append("left out with no review line")
        if field == "static_routes[].gateway" and any(
            _DEST in line for _stanza, line in _lines(out)
        ):
            wrong.append("a route kept without its gateway")
    elif kind == "name" and written != len(named):
        wrong.append(
            f"written at {written} places of the {len(named)} it goes")
    if (altered or bare) and not said:
        wrong.append(
            "altered with no review line" if altered
            else "written where one value is not documented, with no review line")
    return wrong


_CASES = [
    pytest.param(source, target, field, id=f"{source}->{target}:{field}")
    for source in _sources()
    for target in list_public_codecs()
    if target not in _XML and target not in _NOT_YET
    for field in FIELDS
]


@pytest.mark.parametrize(("source", "target", "field"), _CASES)
def test_a_value_with_white_space(source: str, target: str, field: str) -> None:
    assert _judge(source, target, field, _SPACED) == []


@pytest.mark.parametrize(("source", "target", "field"), _CASES)
def test_a_value_with_a_quote(source: str, target: str, field: str) -> None:
    assert _judge(source, target, field, _QUOTED) == []


class _Writes:
    """A target that writes a field in a shape it is handed."""

    def __init__(self, shape: str) -> None:
        self.shape = shape

    def render(self, tree: Any) -> str:
        host = tree.hostname
        route = next(r for r in tree.static_routes if r.destination.startswith(_DEST))
        if host == _ONE_WORD and route.gateway == _ONE_WORD:
            return (
                f"hostname {host}\nsnmp-server location {host}\n"
                f"ip route {_DEST} 255.255.255.255 {route.gateway}\n"
            )
        relabelled = _relabelled(host)
        return {
            "bare": f"hostname {host}\nsnmp-server location {host}\n",
            "relabelled, unsaid": (
                f"hostname {relabelled}\nsnmp-server location {relabelled}\n"),
            "relabelled at one place": (
                f"! review: host name relabelled\nhostname {relabelled}\n"),
            "left out, unsaid": "\n",
            "route without its gateway": (
                f"! review: gateway left out\nip route {_DEST} 255.255.255.255\n"),
            "quoted": f'hostname "{host}"\nsnmp-server location "{host}"\n',
        }[self.shape]


@pytest.mark.parametrize(
    ("shape", "target", "field", "value", "said"),
    [
        ("bare", "cisco_nxos", "hostname", _SPACED, "not one value"),
        ("relabelled, unsaid", "cisco_nxos", "hostname", _SPACED,
         "altered with no review line"),
        ("relabelled at one place", "cisco_nxos", "hostname", _SPACED,
         "written at 1 places of the 3"),
        ("left out, unsaid", "cisco_nxos", "hostname", _SPACED,
         "left out with no review line"),
        ("route without its gateway", "cisco_nxos", "static_routes[].gateway",
         _SPACED, "a route kept without its gateway"),
        # Quotes are read only where the target's grammar reads them:
        # OS10 documents them for a description, not for a host name.
        ("quoted", "dell_os10", "hostname", _SPACED, "not one value"),
        # And a quote with no escape ends the value.
        ("quoted", "aruba_aoss", "hostname", _QUOTED, "not one value"),
    ],
)
def test_the_judge_sees_each_defect(
    monkeypatch: pytest.MonkeyPatch, shape: str, target: str, field: str,
    value: str, said: str,
) -> None:
    """A check nobody has seen fail is not known to check anything: the
    judge is handed a target that makes each defect, and must say so."""
    real = get_codec

    def fake(name: str) -> Any:
        return _Writes(shape) if name == target else real(name)

    def tree_with_route(source: str) -> Any:
        tree = real_tree(source)
        tree.hostname = _ONE_WORD
        _gateway(tree, _ONE_WORD)
        return tree

    real_tree = _tree
    monkeypatch.setattr(sys.modules[__name__], "get_codec", fake)
    monkeypatch.setattr(sys.modules[__name__], "_tree", tree_with_route)
    source = next(
        s for s in _sources()
        if real_tree(s).hostname and any(r.gateway for r in real_tree(s).static_routes)
    )
    wrong = _judge(source, target, field, value)
    assert any(w.startswith(said) for w in wrong), wrong
