"""A value the target does not read as one value holds the job
``partial``, and the job says it.

A renderer of a word-at-a-time CLI writes a review line where a value of
the tree holds white space or a quote (:mod:`netcanon.migration._one_value`):
a record it leaves out (a local user, an SNMP community, an address, a
static route whose gateway it is), or a value it writes otherwise (a
name with ``_`` for each run of white space, a ``"`` written ``'``).
The validation report is made from the tree before the renderer
decides, so such a job said ``completed`` with nothing in its warnings
whenever nothing else held it.  Each such line is now a warning of the
job, made where the line is made (``said_while_rendering``), and the
job is ``partial``.

A text written as it stands where no page says its place reads to the
end of the line is a review line that asks for a check ("check it on
the device") and changes nothing: it is not a warning, and does not
hold the job.

The guard reads the output and the job, and asks the renderer nothing:
every review line of the rule that says a change, found by its words
typed below, has one warning that restates it, and every such warning
has its line; a job with one is ``partial``; a warning about a secret
never holds the secret.  It puts each value the rule knows, with white
space and with a quote, into a tree parsed from a synthetic config,
and sends it onto every public codec.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from netcanon.migration._one_value import left_out, said_while_rendering
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalSNMP
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan
from tests.unit.migration.test_a_name_is_one_word import FIELDS as _NAME_FIELDS
from tests.unit.migration.test_a_name_is_one_word import _sources, _tree
from tests.unit.migration.test_a_secret_is_one_value import FIELDS as _SECRET_FIELDS

pytestmark = pytest.mark.unit

_SPACED = "zq1 zq2"
_QUOTED = 'zq1"zq2'

#: The words of a review line of the rule that says a change, typed
#: here from what each line says, never imported: a value left out
#: (a record, an address, a route whole), a name written as one word,
#: a quote written ``'``.
_CHANGED = (
    "does not read as one value; it is left out, re-create it on the device",
    "does not read as one value; the route is left out whole, re-create it on the device",
    "does not read as one word; each run of white space is written _ and each double quote '",
    "is not documented to read in this place; each is written '",
    "cannot write between its quotes; each is written '",
)

#: The words of the line that asks for a check and changes nothing.
_DOUBT = "it is written as it stands, check it on the device"

#: field -> (setter, whether the value is a secret).
_SETTERS: dict[str, tuple[Callable[[Any, str], bool], bool]] = {
    **{f: (setter, False) for f, (_kind, setter) in _NAME_FIELDS.items()},
    **{f: (setter, secret) for f, (secret, setter) in _SECRET_FIELDS.items()},
}


class _Gives:
    """A source that gives *tree* for any text, and is otherwise the
    codec it stands in front of."""

    def __init__(self, codec: Any, tree: CanonicalIntent) -> None:
        self._codec = codec
        self._tree = tree

    def __getattr__(self, name: str) -> Any:
        return getattr(self._codec, name)

    def parse(self, text: str) -> CanonicalIntent:
        return self._tree.model_copy(deep=True)


_GIVEN: dict[tuple[str, str], tuple[str, Any] | None] = {}


def _given(field: str, value: str) -> tuple[str, Any] | None:
    """(source, tree) with *value* in *field*: the first source whose
    synthetic config has a record to put it in."""
    if (field, value) not in _GIVEN:
        _GIVEN[field, value] = None
        for source in sorted(_sources()):
            tree = _tree(source)
            if _SETTERS[field][0](tree, value):
                _GIVEN[field, value] = (source, tree)
                break
    found = _GIVEN[field, value]
    return None if found is None else (found[0], copy.deepcopy(found[1]))


def _run(target: Any, source: str, tree: CanonicalIntent) -> MigrationJob:
    return run_plan(_Gives(get_codec(source), tree), target, "x\n")


def _changed_lines(job: Any) -> list[str]:
    return [
        line for line in (job.rendered or "").splitlines()
        if " -- review: " in line and any(words in line for words in _CHANGED)
    ]


def _restated(warning: str) -> str:
    """The text of the review line a warning restates: ``Review: P --
    W.`` is the line ``P -- review: W``, behind its comment marker."""
    return warning.removeprefix("Review: ").removesuffix(".").replace(
        " -- ", " -- review: ", 1)


def _disagreements(job: Any, secret: str | None = None) -> list[str]:
    """What is wrong between the output and the job's warnings."""
    lines = _changed_lines(job)
    warnings = [w for w in job.warnings if w.startswith("Review: ")]
    unmatched = list(warnings)
    wrong = []
    for line in lines:
        match = next((w for w in unmatched if _restated(w) in line), None)
        if match is None:
            wrong.append(f"a review line and no warning: {line.strip()[:80]}")
        else:
            unmatched.remove(match)
    wrong += [f"a warning and no review line: {w[:80]}" for w in unmatched]
    if lines and job.status is not MigrationJobStatus.partial:
        wrong.append(f"a review line and the job is {job.status.value}")
    if secret:
        wrong += [f"a warning holds the secret: {w[:40]}" for w in warnings if secret in w]
    return wrong


_JOBS: dict[str, list[tuple[str, str, Any]]] = {}


def _jobs(target: str) -> list[tuple[str, str, Any]]:
    """(field, value, job) for each value the rule knows, onto *target*."""
    if target not in _JOBS:
        _JOBS[target] = [
            (field, value, _run(get_codec(target), *given))
            for field in _SETTERS
            for value in (_SPACED, _QUOTED)
            if (given := _given(field, value)) is not None
        ]
    return _JOBS[target]


#: How many of the (field, value) cases each target writes a review line
#: of the rule for, that says a change, compared for equality: a check
#: that is never given a line passes, and a change of what a renderer
#: refuses is seen here.
_SAID: dict[str, int] = {
    "arista_eos": 39,
    "aruba_aoscx": 18,
    "aruba_aoss": 20,
    "cisco_iosxe": 0,
    "cisco_iosxe_cli": 42,
    "cisco_iosxr": 19,
    "cisco_nxos": 35,
    "dell_os10": 32,
    "fortigate_cli": 16,
    "juniper_junos": 16,
    "mikrotik_routeros": 0,
    "opnsense": 0,
    "vyos": 20,
}


def test_every_public_codec_is_counted() -> None:
    assert set(_SAID) == set(list_public_codecs())


@pytest.mark.parametrize("target", sorted(_SAID))
def test_a_review_line_of_the_rule_is_said(target: str) -> None:
    wrong: list[str] = []
    for field, value, job in _jobs(target):
        secret = "zq1" if _SETTERS[field][1] else None
        wrong += [f"{field} {value!r}: {w}" for w in _disagreements(job, secret)]
    assert wrong == []
    said = sum(bool(_changed_lines(job)) for _field, _value, job in _jobs(target))
    assert said == _SAID[target]


def test_a_line_that_asks_for_a_check_does_not_hold_it() -> None:
    """EOS writes an SNMP location as it stands, with a review line,
    since no Arista page found says the place reads to the end of the
    line: the output holds the value the source did."""
    tree = CanonicalIntent(
        hostname="s1", source_vendor="arista_eos",
        snmp=CanonicalSNMP(location=_SPACED),
    )
    job = _run(get_codec("arista_eos"), "arista_eos", tree)
    assert any(_DOUBT in line for line in (job.rendered or "").splitlines())
    assert _changed_lines(job) == []
    assert job.warnings == []
    assert job.status is MigrationJobStatus.completed


def test_the_line_and_its_warning() -> None:
    """A line made while a block is open is said in that block, and in
    no block around it; with no block open it is the same text."""
    with said_while_rendering() as outer, said_while_rendering() as said:
        line = left_out("an SNMP community", "EOS")
    assert said == [
        "Review: an SNMP community -- a value of it holds white space or a "
        "quote, which EOS does not read as one value; it is left out, "
        "re-create it on the device."
    ]
    assert outer == []
    assert left_out("an SNMP community", "EOS") == line
    assert line.startswith("an SNMP community -- review: a value of it ")


class _Unsaid:
    """A target whose render is said nowhere: each line it writes is
    collected into a list nobody reads."""

    def __init__(self, codec: Any) -> None:
        self._codec = codec

    def __getattr__(self, name: str) -> Any:
        return getattr(self._codec, name)

    def render(self, tree: Any) -> str:
        with said_while_rendering():
            return self._codec.render(tree)


def _a_job(rendered: str, warnings: list[str], status: str = "partial") -> Any:
    return SimpleNamespace(
        rendered=rendered, warnings=warnings,
        status=MigrationJobStatus(status),
    )


_LINE = (
    "! an NTP server -- review: an address that holds white space or a "
    "quote, which EOS does not read as one value; it is left out, "
    "re-create it on the device"
)
_WARNING = (
    "Review: an NTP server -- an address that holds white space or a "
    "quote, which EOS does not read as one value; it is left out, "
    "re-create it on the device."
)


class TestTheGuardCanFail:
    """Each check of :func:`_disagreements` is handed the defect it is
    for, and has to see it."""

    def test_a_review_line_with_no_warning(self) -> None:
        tree = CanonicalIntent(
            hostname="s1", source_vendor="arista_eos", ntp_servers=["192.0.2.1 x"])
        job = _run(_Unsaid(get_codec("arista_eos")), "arista_eos", tree)
        wrong = _disagreements(job)
        assert any(w.startswith("a review line and no warning") for w in wrong)
        assert "a review line and the job is completed" in wrong

    def test_a_warning_with_no_review_line(self) -> None:
        wrong = _disagreements(_a_job("hostname s1", [_WARNING]))
        assert wrong == [f"a warning and no review line: {_WARNING[:80]}"]

    def test_two_lines_and_one_warning(self) -> None:
        wrong = _disagreements(_a_job(f"{_LINE}\n{_LINE}", [_WARNING]))
        assert len(wrong) == 1 and wrong[0].startswith("a review line and no warning")

    def test_a_warning_for_a_line_that_asks_for_a_check(self) -> None:
        doubt = (
            "! the SNMP location -- review: it holds white space, and no EOS "
            f"page found says this place reads to the end of the line; {_DOUBT}"
        )
        warning = "Review: the SNMP location -- it holds white space, and no EOS"
        wrong = _disagreements(_a_job(doubt, [warning], "completed"))
        assert wrong == [f"a warning and no review line: {warning[:80]}"]

    def test_a_warning_that_holds_the_secret(self) -> None:
        warning = _WARNING.replace("an NTP server", "zq1")
        wrong = _disagreements(_a_job(_LINE.replace("an NTP server", "zq1"), [warning]), "zq1")
        assert wrong == [f"a warning holds the secret: {warning[:40]}"]

    def test_the_words_are_the_renderers(self) -> None:
        """Every typed phrase is in a line some target writes: a phrase
        no line holds would let its lines pass unread."""
        seen = {
            words
            for target in sorted(list_public_codecs())
            for _field, _value, job in _jobs(target)
            for line in _changed_lines(job)
            for words in _CHANGED if words in line
        }
        assert seen == set(_CHANGED)
