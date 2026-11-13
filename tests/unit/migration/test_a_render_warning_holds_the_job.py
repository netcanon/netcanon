"""A record the target leaves out, or writes otherwise than the source
states it, holds the job ``partial``.

A target says what it leaves out for a reason of its own in
``render_warnings``: a local user that holds no password, an account past
the one AOS-S has for its role, a DHCP pool it can be given no range for.
The validation report is made from the tree before the renderer decides,
so it does not list such a record, and the status was the report's
alone: a job that left an account out said ``completed`` whenever
nothing else held it.  Over the committed inputs, onto every public codec
with no port map, two dozen jobs did, half of them between two configs
of one codec, each for an account the target left out.  A warning is not
a status (AGENTS.md).

Not held yet: a ``review:`` line with no warning beside it (a password
hash the target does not take, a RADIUS secret it cannot carry).
"""
from __future__ import annotations

from typing import Any

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan, run_plan_with_checked_names

pytestmark = pytest.mark.unit

_LEFT_OUT = "The target left out"

# An account the source gives no password: written without one it could
# log in with none, so no target writes it.
_NO_PASSWORD = {
    "arista_eos": "hostname s1\nusername ops nopassword\n",
    "cisco_iosxe_cli": "hostname s1\nusername ops privilege 15 nopassword\n",
}


def _plan(source: str, target: Any, text: str) -> MigrationJob:
    return run_plan_with_checked_names(get_codec(source), target, text, port_rename_map={})


class _Said:
    """A target that says *said* for every tree, and is otherwise the
    codec it stands in front of."""

    def __init__(self, codec: Any, said: list[str]) -> None:
        self._codec = codec
        self._said = said

    def __getattr__(self, name: str) -> Any:
        return getattr(self._codec, name)

    def render_warnings(self, tree: Any) -> list[str]:
        return list(self._said)


@pytest.mark.parametrize(("source", "target"), [
    ("arista_eos", "arista_eos"),
    ("arista_eos", "cisco_iosxe_cli"),
    ("cisco_iosxe_cli", "cisco_iosxe_cli"),
    ("cisco_iosxe_cli", "juniper_junos"),
])
def test_an_account_with_no_password_holds_it(source: str, target: str) -> None:
    job = _plan(source, get_codec(target), _NO_PASSWORD[source])
    said = [w for w in job.warnings if w.startswith('Local user "ops" is not written for ')]
    assert len(said) == 1, job.warnings
    # Nothing else holds it: the report is clean.
    assert job.validation is not None and job.validation.severity == "ok"
    assert job.status is MigrationJobStatus.partial
    assert job.error is not None and job.error.startswith(f"{_LEFT_OUT} 1 record(s)")


def test_a_job_with_nothing_left_out_is_completed() -> None:
    job = _plan("arista_eos", get_codec("arista_eos"), "hostname s1\n")
    assert job.warnings == []
    assert job.status is MigrationJobStatus.completed
    assert job.error is None


class TestTheStatusIsTheTargets:
    """The status follows what the target says, and nothing else: the
    same text is ``completed`` when the target says nothing, and
    ``partial`` when it says something."""

    def test_said_nothing(self) -> None:
        target = _Said(get_codec("arista_eos"), [])
        job = run_plan(get_codec("arista_eos"), target, "hostname s1\n")
        assert job.status is MigrationJobStatus.completed

    def test_said_two(self) -> None:
        target = _Said(get_codec("arista_eos"), ["one thing", "another"])
        job = run_plan(get_codec("arista_eos"), target, "hostname s1\n")
        assert job.status is MigrationJobStatus.partial
        assert job.error is not None and job.error.startswith(f"{_LEFT_OUT} 2 record(s)")
        assert job.warnings[-2:] == ["one thing", "another"]

    def test_the_account_is_completed_without_its_warning(self) -> None:
        """The account case is ``partial`` for its warning: taken away,
        the job that left the account out says ``completed`` again, as it
        did before."""
        target = _Said(get_codec("arista_eos"), [])
        job = run_plan(get_codec("arista_eos"), target, _NO_PASSWORD["arista_eos"])
        assert job.status is MigrationJobStatus.completed


def test_a_job_partial_for_another_reason_keeps_its_words_first() -> None:
    """Text nothing recognises is ``partial`` for that; what the target
    says is added after it."""
    target = _Said(get_codec("arista_eos"), ["one thing"])
    job = run_plan(get_codec("arista_eos"), target, "not a config at all\nnor this\n")
    assert job.status is MigrationJobStatus.partial
    assert job.error is not None
    assert job.error.startswith("No source constructs were recognized")
    assert f"{_LEFT_OUT} 1 record(s)" in job.error


def test_a_review_line_with_no_warning_does_not_hold_it_yet() -> None:
    """A known limitation, pinned so that closing it fails here until
    this is taken out (CHANGELOG, Known limitations): a RADIUS secret
    the target cannot carry is a ``review:`` line and no warning, and
    the job says ``completed``."""
    text = (
        "hostname s1\n"
        "radius server r1\n"
        " address ipv4 192.0.2.9 auth-port 1812 acct-port 1813\n"
        " key 7 0000FAKE\n"
    )
    job = _plan("cisco_iosxe_cli", get_codec("aruba_aoss"), text)
    assert any("review:" in line for line in (job.rendered or "").splitlines())
    assert job.warnings == []
    assert job.status is MigrationJobStatus.completed


def test_a_failed_job_is_not_made_partial() -> None:
    target = _Said(get_codec("arista_eos"), ["one thing"])
    job = run_plan(get_codec("arista_eos"), target, "hostname s1\n", transforms=[_raises])
    assert job.status is MigrationJobStatus.failed


def _raises(tree: Any) -> Any:
    raise ValueError("a transform that fails")
