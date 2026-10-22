"""A tunnel that is shut is written ``disabled=yes`` on RouterOS.

The RouterOS parser reads ``disabled=`` on an ``/interface gre``,
``eoip`` or ``ipip`` line, and every other section the renderer writes
a shut item in says so.  The tunnel lines did not: an ``add`` with no
``disabled=`` makes an enabled tunnel, so a tunnel that was shut on the
source -- a RouterOS ``disabled=yes``, an IOS-XE ``shutdown`` -- came
out up, in a job that reported nothing.

MikroTik's GRE and EoIP pages list ``disabled (yes | no; Default:
no)``; the IPIP page lists no such row but prints the ``X - disabled``
flag in its example, so an IPIP item takes it too (inferred).

Each output is read twice: by a key=value reader of this module's own,
a character at a time (not the codec's tokenizer), and by the codec's
parser.  The checks are handed the defect they are for.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan

_KINDS = ("gre", "eoip", "ipip")


def _pairs(text: str) -> dict[str, str]:
    """The ``key=value`` words of one ``add`` line; a quoted value is
    read up to its closing quote, a backslash taking the next character."""
    pairs: dict[str, str] = {}
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] == " ":
            i += 1
        start = i
        while i < n and text[i] not in "= ":
            i += 1
        key = text[start:i]
        value = ""
        if i < n and text[i] == "=":
            i += 1
            if i < n and text[i] == '"':
                i += 1
                chars = []
                while i < n and text[i] != '"':
                    if text[i] == "\\" and i + 1 < n:
                        i += 1
                    chars.append(text[i])
                    i += 1
                i += 1
                value = "".join(chars)
            else:
                start = i
                while i < n and text[i] != " ":
                    i += 1
                value = text[start:i]
        if key:
            pairs[key] = value
    return pairs


def _items(text: str, section: str) -> list[dict[str, str]]:
    """Every ``add`` line under the section header ``section``."""
    items: list[dict[str, str]] = []
    current = None
    for line in text.splitlines():
        if line.startswith("/"):
            current = line.strip()
        elif current == section and line.startswith("add "):
            items.append(_pairs(line[len("add "):]))
    return items


def _check(text: str, kind: str, name: str, enabled: bool) -> None:
    """``name`` is one ``add`` line under ``/interface <kind>``, written
    shut exactly when it is meant to be, and the parser reads it so."""
    items = [i for i in _items(text, f"/interface {kind}") if i.get("name") == name]
    assert len(items) == 1, (kind, name, text)
    if enabled:
        assert "disabled" not in items[0], items[0]
    else:
        assert items[0].get("disabled") == "yes", items[0]
    back = [i for i in get_codec("mikrotik_routeros").parse(text).interfaces
            if i.name == name]
    assert [i.enabled for i in back] == [enabled], (name, back)


def _tunnel(kind: str, enabled: bool) -> CanonicalIntent:
    return CanonicalIntent(interfaces=[CanonicalInterface(
        name=f"{kind}-t1", interface_type="ianaift:tunnel", tunnel_type=kind,
        enabled=enabled, description="to site b")])


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("enabled", [True, False])
def test_a_tunnel_is_written_as_shut_as_it_is(kind: str, enabled: bool) -> None:
    text = get_codec("mikrotik_routeros").render(_tunnel(kind, enabled))
    _check(text, kind, f"{kind}-t1", enabled)


@pytest.mark.parametrize("kind", _KINDS)
def test_a_routeros_tunnel_that_is_disabled_stays_disabled(kind: str) -> None:
    source = (
        f"/interface {kind}\n"
        f"add name={kind}-off remote-address=192.0.2.2 disabled=yes\n"
        f"add name={kind}-on remote-address=192.0.2.6\n"
    )
    ros = get_codec("mikrotik_routeros")
    text = run_plan(ros, ros, source).rendered
    _check(text, kind, f"{kind}-off", False)
    _check(text, kind, f"{kind}-on", True)


_IOSXE = """hostname r1
!
interface Tunnel0
 description to site b
 ip address 192.0.2.1 255.255.255.252
{shut}
 tunnel source GigabitEthernet1
 tunnel destination 198.51.100.2
!
interface GigabitEthernet1
 ip address 203.0.113.1 255.255.255.0
!
end
"""


@pytest.mark.parametrize("enabled", [True, False])
def test_a_shut_iosxe_tunnel_arrives_shut(enabled: bool) -> None:
    source = _IOSXE.format(shut=" no shutdown" if enabled else " shutdown")
    text = run_plan(get_codec("cisco_iosxe_cli"),
                    get_codec("mikrotik_routeros"), source).rendered
    _check(text, "gre", "Tunnel0", enabled)


@pytest.mark.parametrize("kind", _KINDS)
def test_the_check_fails_on_a_tunnel_written_up(kind: str) -> None:
    text = get_codec("mikrotik_routeros").render(_tunnel(kind, False))
    assert " disabled=yes" in text
    with pytest.raises(AssertionError):
        _check(text.replace(" disabled=yes", ""), kind, f"{kind}-t1", False)


@pytest.mark.parametrize("kind", _KINDS)
def test_the_check_fails_on_a_tunnel_written_shut(kind: str) -> None:
    text = get_codec("mikrotik_routeros").render(_tunnel(kind, True))
    shut = text.replace(f"name={kind}-t1", f"name={kind}-t1 disabled=yes")
    with pytest.raises(AssertionError):
        _check(shut, kind, f"{kind}-t1", True)
