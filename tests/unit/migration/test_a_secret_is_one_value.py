"""A credential is written as one value of the place it goes, or not at all.

Most CLIs read a line a word at a time, so a value that holds white
space is two words, and the second is read as whatever that place takes
next: NX-OS ``snmp-server community public rw`` is a READ-WRITE
community ``public``.  A grammar that quotes with no escape (AOS-S) has
the same hole one character over: a ``"`` ends the value.  The vendor
references are in ``docs/reviews/2026-10-20-values-with-white-space/``;
the policy is :mod:`netcanon.migration._one_value`.

For each synthetic kitchen sink, each credential field (and each name
of an account) is set, one field at a time, to a value with white space
and to a value with a quote, and the tree is rendered onto every public
codec that writes lines.  The output is read as TEXT, by a reader this
test owns:

* where the value is written outside a comment, it is written whole,
  between quotes, on a target whose grammar quotes it -- with the
  escape that target documents for a ``"``, and never on a target that
  documents none;
* where it is not written, the output says so: the render has more
  review lines than the render of the same tree with a one-word value;
* a secret is in no comment line, ever -- whether or not the target
  writes the field.

A field the target does not write at all (its one-word value is not in
the output outside a comment) is judged for that last point only.  RADIUS keys are not here yet (their
lines are being rewritten for the stored forms of a key).
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

#: Targets whose grammar takes a quoted string where a credential goes,
#: and the escape each documents for a ``"`` inside one (None: none).
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

#: The comment markers of the line grammars.
_COMMENT = ("!", "#", "/*", "//", ";")

_ONE_WORD = "zq1"
_SPACED = "zq1 zq2"
_QUOTED = 'zq1"zq2'


def _each(records: list[Any], field: str, value: str, **extra: Any) -> bool:
    for record in records:
        setattr(record, field, value)
        for key, also in extra.items():
            setattr(record, key, also)
    return bool(records)


def _v3(tree: Any) -> list[Any]:
    return list(tree.snmp.v3_users) if tree.snmp else []


def _v3_auth(tree: Any) -> list[Any]:
    return [u for u in _v3(tree) if u.auth_protocol]


def _v3_priv(tree: Any) -> list[Any]:
    return [u for u in _v3(tree) if u.priv_protocol]


def _groups(tree: Any) -> list[Any]:
    return [g for i in tree.interfaces for g in i.vrrp_groups]


def _community(tree: Any, value: str) -> bool:
    if tree.snmp is None or not tree.snmp.community:
        return False
    tree.snmp.community = value
    return True


#: field -> (is a secret, setter).  A setter returns False when the
#: tree has no record to put the value in.
FIELDS: dict[str, tuple[bool, Callable[[Any, str], bool]]] = {
    "local_users[].name": (
        False, lambda t, v: _each(t.local_users, "name", v)),
    "local_users[].hashed_password": (
        True, lambda t, v: _each(t.local_users, "hashed_password", v)),
    "local_users[].role": (
        False, lambda t, v: _each(t.local_users, "role", v)),
    "snmp.community": (True, _community),
    "snmp.v3_users[].name": (
        False, lambda t, v: _each(_v3(t), "name", v)),
    "snmp.v3_users[].group": (
        False, lambda t, v: _each(_v3(t), "group", v)),
    "snmp.v3_users[].auth_passphrase": (
        True, lambda t, v: _each(
            _v3_auth(t), "auth_passphrase", v, auth_kind="plaintext")),
    "snmp.v3_users[].priv_passphrase": (
        True, lambda t, v: _each(
            _v3_priv(t), "priv_passphrase", v, priv_kind="plaintext")),
    "vrrp_groups[].authentication (plain)": (
        True, lambda t, v: _each(_groups(t), "authentication", f"plain:{v}")),
    "vrrp_groups[].authentication (md5)": (
        True, lambda t, v: _each(_groups(t), "authentication", f"md5:{v}")),
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


def _written_forms(target: str, value: str) -> list[str]:
    """How *value* may stand in a line of *target*: between quotes,
    with the target's own escape -- or nowhere."""
    if target not in _QUOTES:
        return []
    escape = _QUOTES[target]
    if '"' in value and escape is None:
        return []
    inner = value
    if escape is not None:
        inner = value.replace(escape, escape * 2).replace('"', escape + '"')
    forms = [f'"{inner}"']
    if '"' not in value:
        forms.append(f"'{value}'")
    return forms


def _writes(text: str) -> bool:
    """Whether a one-word value is written outside a comment."""
    return any(
        _ONE_WORD in line and not _is_comment(line)
        for line in text.splitlines()
    )


def _judge(source: str, target: str, field: str, value: str) -> list[str]:
    """What is wrong with the render of *value* in *field*, as text."""
    secret = FIELDS[field][0]
    base = _render(source, target, field, _ONE_WORD)
    if base is None:
        return []
    out = _render(source, target, field, value)
    assert out is not None
    wrong: list[str] = []
    if secret:
        wrong += [
            f"a secret in a comment: {line.strip()[:100]}"
            for text in (base, out) for line in text.splitlines()
            if _ONE_WORD in line and _is_comment(line)
        ]
    if not _writes(base):
        return wrong
    forms = _written_forms(target, value)
    written = False
    for line in out.splitlines():
        if _ONE_WORD not in line:
            continue
        if _is_comment(line):
            continue
        written = True
        rest = line
        for form in forms:
            rest = rest.replace(form, "")
        if _ONE_WORD in rest:
            wrong.append(f"not one value: {line.strip()[:100]}")
    if not written and _reviews(out) <= _reviews(base):
        wrong.append("left out with no review line")
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
    """A target that writes the community in a shape it is handed."""

    def __init__(self, shape: str) -> None:
        self.shape = shape

    def render(self, tree: Any) -> str:
        value = tree.snmp.community
        if value == _ONE_WORD:
            return f"snmp-server community {value}\n"
        return {
            "bare": f"snmp-server community {value}\n",
            "in a comment": f"! review: community {value} left out\n",
            "left out": "\n",
            "quoted, no escape": f'snmp-server community "{value}"\n',
        }[self.shape]


@pytest.mark.parametrize(
    ("shape", "target", "value", "said"),
    [
        ("bare", "cisco_nxos", _SPACED, "not one value"),
        ("in a comment", "cisco_nxos", _SPACED, "a secret in a comment"),
        ("left out", "cisco_nxos", _SPACED, "left out with no review line"),
        ("quoted, no escape", "aruba_aoss", _QUOTED, "not one value"),
        ("quoted, no escape", "fortigate_cli", _QUOTED, "not one value"),
    ],
)
def test_the_judge_sees_each_defect(
    monkeypatch: pytest.MonkeyPatch, shape: str, target: str, value: str,
    said: str,
) -> None:
    """A check nobody has seen fail is not known to check anything: the
    judge is handed a target that makes each defect, and must say so."""
    real = get_codec

    def fake(name: str) -> Any:
        return _Writes(shape) if name == target else real(name)

    monkeypatch.setattr(sys.modules[__name__], "get_codec", fake)
    source = next(
        s for s in _sources()
        if _tree(s).snmp is not None and _tree(s).snmp.community
    )
    wrong = _judge(source, target, "snmp.community", value)
    assert any(w.startswith(said) for w in wrong), wrong
