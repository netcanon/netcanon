"""Every config limit a document prints is the code's.

The limits are numbers (``netcanon.migration.limits.PROFILES``), and
documents print them: an operator reads ``docs/CAPABILITIES.md`` to
learn what a refusal means, and ``SECURITY.md`` to learn what a server
is protected from.  A number changed in the module and not in a
document is a document that lies -- about a security control.

Three things are held together here:

* **the tables.**  Any Markdown table row whose first cell is a limit's
  name has, in its last three cells, that limit under ``small``,
  ``standard`` and ``large``.  Every document is searched for such
  rows, so a table added somewhere else is found too.
* **the sentences that follow from a number** -- "4,096 ports that each
  allow every VLAN", "refused at the ninth range", "256 trunks ... 193
  VLANs" -- written here FROM the numbers, and looked for in the
  document.  Change a number and the sentence this test looks for
  changes with it.
* **the words.**  What a refusal calls each kind is what the
  troubleshooting page explains, and the example a document quotes is
  the sentence the code gives for that text.
* **requests at once.**  How many requests a server works on at once
  under each set, and how many may wait, are numbers too; and the
  sentence a busy server gives is quoted.
* **a place, and an answer's time.**  How many places there are for
  requests that have arrived, how long an answer has to be read in,
  how much of an answer is handed over at a time, and the sentences
  for a request that waited and ran out of time and for a body that
  did not arrive -- all from the code.
* **the proofs.**  The documents that say how many live proofs there
  are say the number `deploy/VERIFY.md` has, and a proof a document
  names by its number exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.api.routes import _migration_helpers as helpers
from netcanon.migration import limits as L
from netcanon.migration.codecs.aruba_aoss.parse import _MAX_PORT_RANGE_SPAN
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.codecs.vyos.parse import _MAX_SET_DEPTH
from netcanon_desktop.preferences_dialog import LIMITS_OFFERED

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]

#: The documents that print the table of limits.
TABLES = ("SECURITY.md", "docs/CAPABILITIES.md")

#: Never read: working notes that are not part of what ships.
_NOT_READ = ("docs/reviews/", "docs/codebase-review/", "docs/project-review/", "docs/docs-audit/",
             "docs/security-triage/", "local/", "node_modules/", ".git/")

_ROW = re.compile(
    r"^\|\s*`(" + "|".join(L.KINDS) + r")`\s*\|.*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|\s*$",
    re.MULTILINE,
)


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _words(text: str) -> str:
    """*text* with every run of white space as one space, and with the
    marks a quoted block or a list puts at the start of its lines
    taken off: what a sentence says, however it is wrapped."""
    return " ".join(re.sub(r"^\s*(?:>|[*-])\s?", "", line) for line in text.splitlines()).replace("  ", " ")


def _flat(rel: str) -> str:
    return " ".join(_words(_read(rel)).split())


def _documents() -> list[str]:
    found = []
    for path in sorted(REPO.rglob("*.md")):
        rel = path.relative_to(REPO).as_posix()
        if not any(rel.startswith(skipped) or f"/{skipped}" in f"/{rel}" for skipped in _NOT_READ):
            found.append(rel)
    return found


def _number(value: float) -> str:
    return f"{int(value):,}"


class TestTheTables:
    @pytest.mark.parametrize("rel", TABLES)
    def test_every_limit_in_the_table_is_the_codes(self, rel: str) -> None:
        rows = {match[1]: match.groups()[1:] for match in _ROW.finditer(_read(rel))}
        assert set(rows) == set(L.KINDS), f"{rel}: the table has no row for {sorted(set(L.KINDS) - set(rows))}"
        for kind, printed in rows.items():
            expected = tuple(_number(getattr(limits, kind)) for limits in (L.SMALL, L.STANDARD, L.LARGE))
            assert printed == expected, f"{rel}: `{kind}` is printed as {printed}; the code has {expected}"

    def test_no_other_document_prints_a_table_of_limits(self) -> None:
        """A second table somewhere else would be a second place to
        forget.  One that is wanted goes in ``TABLES``, and is then
        held to the code like the others."""
        documents = _documents()
        assert len(documents) > 40 and "README.md" in documents and "docs/TROUBLESHOOTING.md" in documents
        printing = [rel for rel in documents if _ROW.search(_read(rel))]
        assert sorted(printing) == sorted(TABLES)

    def test_the_search_finds_a_row_that_is_wrong(self) -> None:
        row = "| `memberships` | one port in one VLAN | 50,000 | 999,999 | 4,000,000 |\n"
        (match,) = _ROW.finditer(row)
        assert match.groups() == ("memberships", "50,000", "999,999", "4,000,000")
        assert match[3] != _number(L.STANDARD.memberships)


#: Sentences that follow from a number, written from the number.
def _sentences() -> dict[str, list[str]]:
    small, standard = L.SMALL, L.STANDARD
    every = 4096  # the ids one port that allows every VLAN is counted as, rounded up
    per_range = 1001
    ninth = standard.ports // per_range + 1
    trunk = small.vlan_ids // 3999 + 1
    # The most trunks that say `all`, and the most VLANs a config of
    # them may declare.  Each trunk states no native VLAN, which is
    # native VLAN 1 where a trunk says `all`: it is on VLAN 1 too --
    # a VLAN more than the config declares -- and its untagged place
    # there is counted beside the tagged one it replaces.  Two fewer
    # declared VLANs fit than the limit divided by the trunks.
    worst = (small.vlan_ids // every, small.memberships // (small.vlan_ids // every) - 2)
    ordinal = {9: "ninth"}[ninth]
    # A trunk that states no allowed list is every VLAN on four
    # platforms, and is counted as the 4,094 ids it is.
    unlisted = (small.vlan_ids // 4094, standard.vlan_ids // 4094)
    return {
        "docs/CAPABILITIES.md": [
            f"`vlan_ids`: {_number(standard.vlan_ids // every)} ports that each allow every VLAN.",
            f"more than {_number(standard.vlan_ids // every)} ports that each state `all`",
            f"an output of more than {standard.text // 1_000_000} million characters",
            f"more than {_number(small.vlan_ids // every)} ports that each state `all`, "
            f"or more than {_number(small.memberships)} memberships",
            "`unlimited` is no limit and no time limit.",
        ],
        "SECURITY.md": [
            f"refused at the {ordinal} range",
            f"Under `small` it is refused at the {trunk}rd trunk.",
            f"Under `standard` the {_number(unlisted[1] + 1)}th is refused",
            f"under `small` a config of such trunks is refused at the {unlisted[0] + 1}th",
            "a million memberships, which is the `standard` limit exactly",
            "Under `small` the largest answer is 38 MB, for the text that reaches every limit at once",
            f"its {_number(small.memberships)} memberships are 9.5 MB of that",
            f"a set line nested more than {_MAX_SET_DEPTH} levels deep is a parse failure",
            "The default is `standard` on both platforms.",
        ],
        "docs/demo-plan/07-budget.md": [
            f"{worst[0]} trunks that allow every VLAN, {worst[1]} VLANs, "
            f"{_number(small.interfaces - worst[0])} one-line interfaces",
            "`NETCANON_CONFIG_LIMITS=small`",
        ],
        "docs/demo-plan/04-container-hardening.md": ['"NETCANON_CONFIG_LIMITS": "small"'],
        "docs/vendors/aruba_aoss.md": [f"One range is read up to {_number(_MAX_PORT_RANGE_SPAN + 1)} ports"],
        "docs/vendors/vyos.md": [f"A set line nested more than {_MAX_SET_DEPTH} levels deep is a parse failure."],
        "docs/TROUBLESHOOTING.md": ["`NETCANON_CONFIG_LIMITS=large` (or `unlimited`)"],
        "README.md": ["`standard` (the default), `large`, `unlimited`, or `small`, which is what the public demo runs"],
        "netcanon_desktop/README.md": [
            " or ".join(", ".join(f"`{name}`" for name in LIMITS_OFFERED).rsplit(", ", 1)).replace(
                "`standard`", "`standard` (default)"),
        ],
        ".env.example": [f"# NETCANON_CONFIG_LIMITS={standard.name}"],
    }


class TestTheSentences:
    @pytest.mark.parametrize("rel", sorted(_sentences()))
    def test_what_follows_from_a_number_is_said(self, rel: str) -> None:
        said = _flat(rel)
        for sentence in _sentences()[rel]:
            assert " ".join(sentence.split()) in said, f"{rel} does not say: {sentence}"

    def test_the_numbers_the_sentences_rest_on(self) -> None:
        assert L.STANDARD.vlan_ids == 4096 * 4096 and L.SMALL.vlan_ids == 256 * 4096
        assert L.STANDARD.memberships == 1_000_000
        assert L.STANDARD.seconds == 120 and L.SMALL.seconds == 20
        assert tuple(L.PROFILES) == ("small", "standard", "large", "unlimited")
        assert LIMITS_OFFERED == ("standard", "large", "unlimited")

    def test_every_profile_is_named_with_the_setting(self) -> None:
        for rel in (".env.example", "docs/CAPABILITIES.md", "SECURITY.md", "README.md"):
            text = _read(rel)
            for name in L.PROFILES:
                assert name in text, f"{rel} does not name `{name}`"


class TestTheWords:
    def test_the_troubleshooting_page_has_every_kind(self) -> None:
        page = _flat("docs/TROUBLESHOOTING.md")
        for kind, (noun, _units) in L.KINDS.items():
            if kind == "seconds":
                assert "the request passed the N seconds it may take" in page
                continue
            short = noun.split(" (")[0]
            assert short in page, f"the page has no line for what a refusal calls `{kind}`: {short}"
        for kind, noun in L._HELD.items():
            assert noun.split(" (")[0] in page, f"the page has no line for a finished tree's `{kind}`: {noun}"
        assert "characters of nested blocks written out from set lines" in page
        assert "words of set commands written out from a bracket list" in page

    def test_the_quoted_example_is_what_the_code_says(self) -> None:
        """One AOS-S line of 800 ranges of 1,001 ports, as the page
        has it: the sentence is produced here and looked for there."""
        ranges = ",".join(f"{1 + n * 1001}-{(n + 1) * 1001}" for n in range(800))
        text = f'hostname "T"\nvlan 10\n   name "V10"\n   tagged {ranges}\n   exit\n'
        with L.limits_scope("standard"), pytest.raises(L.LimitExceeded) as caught:
            get_codec("aruba_aoss").parse(text)
        sentence = " ".join(f"refused: {caught.value}".split())
        assert sentence in _flat("docs/CAPABILITIES.md")
        assert "8009-9009" in sentence and "9,009 or more" in sentence

    def test_a_trunk_with_no_list_is_quoted_as_the_code_says_it(self) -> None:
        """A trunk that states no allowed list is counted as every
        VLAN where that is what it carries.  What the documents
        quote of that refusal is produced here and looked for
        there, and so is the trunk it is said to stop at."""
        text = "hostname T\n" + "".join(
            f"interface GigabitEthernet1/0/{n}\n switchport mode trunk\n!\n" for n in range(1, 301)
        )
        with L.limits_scope("small"), pytest.raises(L.LimitExceeded) as caught:
            get_codec("cisco_iosxe_cli").parse(text)
        assert (caught.value.kind, caught.value.lists) == ("vlan_ids", L.SMALL.vlan_ids // 4094 + 1)
        quoted = "the last one read: a trunk with no allowed list, which is every VLAN: GigabitEthernet1/0/257"
        assert quoted in str(caught.value)
        assert quoted in _flat("docs/CAPABILITIES.md")
        assert "the last one read: a trunk with no allowed list, which is every VLAN: ..." in _flat(
            "docs/TROUBLESHOOTING.md")
        for rel in TABLES:
            assert "the 4,094 of a trunk that states no allowed list, where that is every VLAN" in _flat(rel), rel

    def test_what_each_surface_is_told_is_documented(self) -> None:
        server = L.how_to_raise(L.STANDARD, "ports")
        assert " ".join(server.split()) in _flat("docs/CAPABILITIES.md")
        assert "Preferences... -> Config size limit" in server
        for rel in ("SECURITY.md", "docs/TROUBLESHOOTING.md", "netcanon_desktop/README.md"):
            assert "Config size limit" in _flat(rel), rel
        assert "--limits" in _read("SECURITY.md") and "--limits large" in _read("docs/TROUBLESHOOTING.md")


class TestRequestsAtOnce:
    """Under ``small`` a server works on one request that reads config
    text at a time, and a set number wait.  Documents say so in
    figures and in words; both are written here from the code."""

    def test_the_numbers_the_documents_rest_on(self) -> None:
        assert {name: limits.at_once for name, limits in L.PROFILES.items()} == {
            "small": 1, "standard": None, "large": None, "unlimited": None,
        }
        assert (L.MOST_WAITING, L.SMALL.seconds) == (2, 20.0)

    def test_how_many_work_and_how_many_wait(self) -> None:
        waiting, seconds = L.MOST_WAITING, int(L.SMALL.seconds)
        said = {
            "docs/CAPABILITIES.md": [
                f"Under `small` the server also works on {L.SMALL.at_once} request that reads config text at a time",
                f"at most {waiting} wait, and one more is refused at once as busy",
                f"(inside its own {seconds} seconds)",
                "`standard`, `large` and `unlimited` limit no requests at once.",
            ],
            "SECURITY.md": [
                "a server works on one request that reads config text at a time",
                f"At most {waiting} requests wait.",
                "`standard`, `large` and `unlimited` limit no requests at once.",
                f"one request that reads config text works at a time and {waiting} may wait",
            ],
            "docs/demo-plan/07-budget.md": [
                f"waits its turn inside its own {seconds} seconds, at most {waiting} wait",
            ],
            "docs/demo-plan/04-container-hardening.md": [f"a request that waited out its {seconds} seconds"],
            "deploy/README.md": [f"waited its whole {seconds} seconds"],
            "README.md": ["`small` also makes a server work on one such request at a time"],
            ".env.example": ["(one works at a time, a second waits)"],
            "ARCHITECTURE.md": ["one under `small`, no limit under the others"],
        }
        for rel, sentences in said.items():
            text = _flat(rel)
            for sentence in sentences:
                assert " ".join(sentence.split()) in text, f"{rel} does not say: {sentence}"

    def test_the_busy_sentence_quoted_is_the_codes(self) -> None:
        sentence = " ".join(f"refused: {L._busy(L.SMALL, 2, L.SMALL.seconds)}".split())
        assert sentence in _flat("docs/CAPABILITIES.md")
        page = _flat("docs/TROUBLESHOOTING.md")
        waited, full = str(L._busy(L.SMALL, 2, L.SMALL.seconds)), str(L._busy(L.SMALL, 4, None))
        assert waited.startswith("the server works on one config at a time, and was busy with another")
        assert "the server works on one config at a time, and was busy with another" in page
        assert f"{L.MOST_WAITING} more were already waiting their turn" in full
        assert "more were already waiting their turn" in page
        for rel in ("docs/CAPABILITIES.md", "docs/TROUBLESHOOTING.md", "SECURITY.md"):
            assert "503" in _read(rel) and "Retry-After" in _read(rel), rel


class TestAPlaceAndAnAnswersTime:
    """Under ``small`` a request is counted when its headers arrive,
    has one deadline from then, and its answer has that long to be
    read.  The documents say so in figures; the figures are the
    code's."""

    def test_the_numbers_the_documents_rest_on(self) -> None:
        assert (L.SMALL.at_once, L.MOST_WAITING, L.SMALL.seconds, helpers.WRITE) == (1, 2, 20.0, 65_536)
        assert len(helpers.READS_CONFIG_TEXT) == 10

    def test_how_many_places_and_how_long_an_answer_has(self) -> None:
        places, seconds = L.SMALL.at_once + L.MOST_WAITING, int(L.SMALL.seconds)
        word = {1: "one", 2: "two", 3: "three"}
        handed = f"handed to the server {helpers.WRITE // 1024} KiB at a time"
        said = {
            "SECURITY.md": [
                "A request is counted when its headers arrive, before its body is read.",
                f"There are {places} places: as many as may work and wait.",
                f"under `small` an answer has the request's {seconds} seconds to be read in",
                "a body that has not arrived by then is answered 408",
                handed,
            ],
            "docs/CAPABILITIES.md": [
                f"its {seconds} seconds run from then",
                "Under `small` an answer has the request's seconds to be read in",
                "**503 with `Retry-After`**, at once, to a request that arrives while as many are in flight as "
                "may work and wait.",
                "**408**, to a request whose body has not arrived inside the time a request may take",
            ],
            "docs/TROUBLESHOOTING.md": [
                f"has the request's {seconds} seconds to be read in",
                "this request waited N seconds for its turn",
                "while its body was still arriving",
            ],
            "deploy/README.md": [
                f"arrives while {word[places]} are in flight ({word[L.SMALL.at_once]} at work, "
                f"{word[L.MOST_WAITING]} waiting)",
                f"An answer has the request's {seconds} seconds to be read in",
            ],
            "deploy/VERIFY.md": [
                f"one that finds the {word[places]} places taken is answered 503 at once, its body unread",
                f"At the deadline of a request ({seconds} seconds from its arrival)",
            ],
            "docs/demo-plan/07-budget.md": [
                f"counted when its headers arrive; there are {places} places",
                f"an answer has the request's {seconds} seconds to be read in",
            ],
            "ARCHITECTURE.md": [handed],
        }
        for rel, sentences in said.items():
            text = _flat(rel)
            for sentence in sentences:
                assert " ".join(sentence.split()) in text, f"{rel} does not say: {sentence}"

    def test_the_sentences_quoted_are_the_codes(self) -> None:
        """A request that got its turn after 17.5 seconds and ran out
        of its 20 while a parse was starting, as the capabilities page
        quotes it; and what the middleware says of a body that did not
        come and of a request it had no place for."""
        late = L._out_of_time(L.SMALL, "server", 0.5, 17.5, 2, "parse", "cisco_iosxe_cli", True)
        assert late.kind == "at_once"
        page = _flat("docs/CAPABILITIES.md")
        assert " ".join(f"refused: {late}".split()) in page
        body = " ".join(str(L.body_late(L.SMALL, 20.0)).split())
        assert body.startswith(
            "the request passed the 20 seconds it may take while its body was still arriving, and was stopped."
        )
        assert body.split(".")[0] in page
        full = " ".join(str(L._busy(L.SMALL, L.SMALL.at_once + L.MOST_WAITING + 1, None)).split())
        quoted = (
            f"and {L.MOST_WAITING} more were already waiting their turn; this request was not started and its "
            "config was not read. Send it again."
        )
        assert quoted in full and quoted in page

    def test_the_search_for_a_sentence_can_fail(self) -> None:
        assert "There are 4 places: as many as may work and wait." not in _flat("SECURITY.md")
        assert "an answer has the request's 120 seconds to be read in" not in _flat("SECURITY.md")


class TestTheProofs:
    """``deploy/VERIFY.md`` numbers its live proofs, and three
    documents say how many there are."""

    @staticmethod
    def _numbered() -> list[int]:
        return [int(n) for n in re.findall(r"^### (\d+)\. ", _read("deploy/VERIFY.md"), re.MULTILINE)]

    def test_the_proofs_are_numbered_from_one_with_none_missing(self) -> None:
        numbered = self._numbered()
        assert numbered == list(range(1, len(numbered) + 1)) and len(numbered) >= 17

    def test_every_document_that_counts_them_counts_them_all(self) -> None:
        last = self._numbered()[-1]
        counted = {
            "deploy/VERIFY.md": 1, "docs/demo-plan/08-testing-verification.md": 2,
            "docs/demo-plan/09-implementation-order.md": 2,
        }
        for rel, times in counted.items():
            found = re.findall(r"[Pp]roofs 1\u2013(\d+)", _read(rel).replace("**", ""))
            assert len(found) == times, f"{rel}: 'proofs 1\u2013N' is said {len(found)} times"
            assert set(found) == {str(last)}, f"{rel} counts proofs 1\u2013{sorted(set(found))}; there are {last}"

    def test_a_proof_named_by_its_number_exists(self) -> None:
        numbered = set(self._numbered())
        named = 0
        for rel in ("SECURITY.md", "CHANGELOG.md", "deploy/README.md", "docs/demo-plan/04-container-hardening.md",
                    "docs/demo-plan/07-budget.md", "docs/demo-plan/08-testing-verification.md"):
            # Only what this work wrote: the changelog's older entries name proofs of documents long gone.
            text = _read(rel)
            if rel == "CHANGELOG.md":
                text = text[:text.index("\n## [", text.index("## [Unreleased]") + 1)]
            for n in re.findall(r"`deploy/VERIFY\.md`,? proofs? (\d+)|[Pp]roofs? (1[4-9]|[2-9]\d)\b", text):
                number = int(n[0] or n[1])
                named += 1
                assert number in numbered, f"{rel} names proof {number}, and deploy/VERIFY.md has no such proof"
        assert named >= 6
