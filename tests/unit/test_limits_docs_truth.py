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
  allow every VLAN", "refused at the ninth range", "256 trunks ... 195
  VLANs" -- written here FROM the numbers, and looked for in the
  document.  Change a number and the sentence this test looks for
  changes with it.
* **the words.**  What a refusal calls each kind is what the
  troubleshooting page explains, and the example a document quotes is
  the sentence the code gives for that text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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
    worst = (small.vlan_ids // every, small.memberships // (small.vlan_ids // every))
    ordinal = {9: "ninth"}[ninth]
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
            "a million memberships, which is the `standard` limit exactly",
            f"{_number(small.memberships)} are 38 MB under `small`",
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

    def test_what_each_surface_is_told_is_documented(self) -> None:
        server = L.how_to_raise(L.STANDARD, "ports")
        assert " ".join(server.split()) in _flat("docs/CAPABILITIES.md")
        assert "Preferences... -> Config size limit" in server
        for rel in ("SECURITY.md", "docs/TROUBLESHOOTING.md", "netcanon_desktop/README.md"):
            assert "Config size limit" in _flat(rel), rel
        assert "--limits" in _read("SECURITY.md") and "--limits large" in _read("docs/TROUBLESHOOTING.md")
