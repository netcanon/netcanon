"""Docs-truth ratchet: the whitepaper must describe the code, not an old draft.

The demo's whole premise is that every claim maps to a control you can read in
one file (``demo/warden/constants.py``). That only holds if the prose and the
constants cannot drift apart — and they already had: the adversarial-review
remediation raised the systemd backstop ceiling to
``HARD_TTL + POOL_MAX_AGE + 120`` so it can never fire *before* a live session's
assignment-relative deadline, but four documents kept quoting the superseded
``= 1200 s`` formula and an understated "~20 minutes" worst case.

Module 09's standing rule 2 is explicit: *the whitepaper must describe reality*.
These tests enforce that mechanically, so the next constant change fails CI
instead of quietly making the published trust argument false.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from demo.warden import constants as C

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every document that states the hard-TTL enforcement numbers to a reader.
# deploy/README.md is in here because it drifted the same way the others did —
# it kept quoting the pre-remediation 1200 s long after the ceiling moved.
CLAIM_DOCS = (
    "docs/DEMO_WHITEPAPER.md",
    "deploy/VERIFY.md",
    "docs/demo-architecture.md",
    "deploy/README.md",
)


def read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


@pytest.mark.parametrize("relpath", CLAIM_DOCS)
def test_docs_quote_the_real_backstop_ceiling(relpath):
    """The published ceiling must be the constant the backstop actually uses."""
    text = read(relpath)
    assert str(C.HARD_TTL_BACKSTOP) in text, (
        f"{relpath} never states the real backstop ceiling "
        f"({C.HARD_TTL_BACKSTOP}s = HARD_TTL + POOL_MAX_AGE + slack)"
    )


@pytest.mark.parametrize("relpath", CLAIM_DOCS)
def test_docs_do_not_quote_the_superseded_backstop_formula(relpath):
    """``HARD_TTL + POOL_MAX_AGE`` alone is no longer the ceiling.

    Presenting it as such under-states the worst case by the 120 s slack, i.e.
    promises the visitor a tighter guarantee than the code delivers.
    """
    stale = f"POOL_MAX_AGE = {C.HARD_TTL + C.POOL_MAX_AGE}"
    text = read(relpath)
    assert stale not in text, f"{relpath} still quotes the superseded '{stale}'"


def test_backstop_ceiling_matches_the_systemd_unit():
    """The shell backstop is a second enforcement domain — it must agree."""
    script = read("deploy/systemd/demo-ttl-backstop.sh")
    match = re.search(r"^CEILING=(\d+)", script, re.MULTILINE)
    assert match, "demo-ttl-backstop.sh has no CEILING assignment"
    assert int(match.group(1)) == C.HARD_TTL_BACKSTOP, (
        "the host backstop and the warden constants disagree on the ceiling"
    )


def test_backstop_cannot_fire_before_a_live_session_deadline():
    """The invariant behind the slack: a pool instance assigned at the last
    possible moment must still get its full session before the host sweep."""
    worst_case_live_age = C.POOL_MAX_AGE + C.HARD_TTL
    assert worst_case_live_age < C.HARD_TTL_BACKSTOP, (
        "the systemd backstop could kill a session inside its 900 s window"
    )


def test_warden_stays_under_the_audited_line_count():
    """The whitepaper asks for trust on the grounds that the warden is small
    enough to read end to end (<=500 lines). Keep that claim true."""
    lines = (REPO_ROOT / "demo/warden/app.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 500, (
        f"demo/warden/app.py is {len(lines)} lines; the whitepaper and module 09 "
        "standing rule 4 both promise <=500 — simplify rather than raise this"
    )


@pytest.mark.parametrize(
    "constant,label",
    [
        (C.HARD_TTL, "hard TTL"),
        (C.IDLE_TTL, "idle TTL"),
        (C.MAX_ACTIVE, "instance cap"),
        (C.PER_IP_MAX_CONCURRENT, "per-IP concurrent cap"),
    ],
)
def test_whitepaper_states_the_real_lifecycle_numbers(constant, label):
    """Each headline number in the claim table must come from constants.py."""
    text = read("docs/DEMO_WHITEPAPER.md")
    assert str(constant) in text, f"whitepaper never states the real {label}"


# ── Frontend claim 10: "no tracking on the demo page" ────────────────────────
# Claim 10 is one of only two visitor-verifiable rows: anyone can open devtools
# and check it. That makes it the cheapest claim to falsify by accident, so it is
# pinned to the source rather than to a promise.
FRONTEND = "frontend/index.html"


def strip_comments(text: str) -> str:
    """Drop HTML/JS comments so a comment *documenting* the claim ("sets NO
    localStorage") is not mistaken for a violation of it."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(?<!:)//[^\n]*", "", text)  # keep https:// intact


def frontend_code() -> str:
    return strip_comments(read(FRONTEND))


@pytest.mark.parametrize(
    "api",
    ["localStorage", "sessionStorage", "document.cookie", "indexedDB"],
)
def test_frontend_uses_no_client_side_storage(api):
    assert api not in frontend_code(), (
        f"{FRONTEND} touches {api}; whitepaper claim 10 says the page stores nothing"
    )


def test_frontend_makes_no_third_party_requests():
    """No off-origin subresource may appear: the page must stay self-contained
    (all CSS/JS inline) so view-source corroborates the claim."""
    code = frontend_code()
    for pattern in ("src=\"http", "src='http", "@import", "cdn.",
                    "googleapis", "fonts.g"):
        assert pattern not in code, f"{FRONTEND} references off-origin asset: {pattern}"


def test_frontend_offsite_links_are_only_the_documented_ones():
    """Anchor links off-origin are fine (GitHub/PyPI) — but only those."""
    hosts = set(re.findall(r"https://([a-z0-9.\-]+)", frontend_code()))
    assert hosts <= {"github.com", "pypi.org"}, f"unexpected off-origin hosts: {hosts}"


def test_frontend_stays_within_the_weight_budget():
    """Module 05 budgets the page at <=50 KB excluding the iframed instance."""
    size = (REPO_ROOT / FRONTEND).stat().st_size
    assert size <= 50 * 1024, f"{FRONTEND} is {size} bytes; budget is 50 KB"


def test_frontend_targets_the_real_warden_endpoints():
    """A rename on either side must break here rather than in production."""
    text = read(FRONTEND)
    assert "/session/new" in text
    assert "/hb" in text and "/end" in text
    assert "/i/" in text and "/migrate" in text


def test_frontend_ends_sessions_on_pagehide_not_visibilitychange():
    """Ending on visibilitychange would destroy the instance on a mere tab
    switch — killing the demo's own copy-a-config-from-another-tab flow."""
    text = read(FRONTEND)
    assert "sendBeacon" in text
    beacon_line = next(line for line in text.splitlines() if "sendBeacon" in line)
    assert "visibilitychange" not in beacon_line
