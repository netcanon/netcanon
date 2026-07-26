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
import yaml

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


def test_dockerfile_copies_every_warden_module():
    """The Dockerfile names the warden's modules explicitly, so a new one imports
    fine from the repo — green suite — and ImportErrors inside the container.
    That is exactly how pages.py first shipped: every test passed and the warden
    crash-looped on `cannot import name 'pages'`."""
    copied: set[str] = set()
    for line in read("demo/warden/Dockerfile").splitlines():
        if line.startswith("COPY ") and "/app/warden/" in line:
            copied.update(part for part in line.split()[1:] if part.endswith(".py"))
    on_disk = {
        path.name
        for path in (REPO_ROOT / "demo" / "warden").glob("*.py")
        if path.name != "__init__.py"
    }
    assert on_disk, "found no warden modules — the glob has rotted"
    missing = on_disk - copied
    assert not missing, f"demo/warden modules absent from the Dockerfile COPY: {sorted(missing)}"


def test_every_makefile_target_is_phony():
    """A same-line ``.PHONY`` edit is the merge conflict git resolves silently and
    wrongly: #396 and #397 each appended targets, one side won with no textual
    conflict, and three targets went missing. Assert the invariant, don't rely on
    catching it by eye at merge time."""
    text = read("deploy/Makefile")
    declared: set[str] = set()
    for line in text.splitlines():
        if line.startswith(".PHONY:"):
            declared.update(line.split(":", 1)[1].split())
    targets = {
        match.group(1)
        for match in re.finditer(r"^([a-z][a-z0-9-]*):(?!=)", text, re.MULTILINE)
    }
    assert targets, "no Makefile targets matched — the parser regex has rotted"
    missing = targets - declared
    assert not missing, f"deploy/Makefile targets missing from .PHONY: {sorted(missing)}"


# ── The socket-proxy tag is load-bearing, and it already shipped wrong ───────
# demo-publish.yml pinned :0.3, whose entrypoint renders haproxy.cfg into
# /usr/local/etc/haproxy/ — forbidden by that service's ``read_only: true``, so
# the socket-proxy crash-looped and took the whole privilege chain with it.
# Gate 1 passed only because it happened to run an untagged (latest) image that
# writes /tmp instead. Nothing could catch it: every document agreed with the
# workflow, and all of them disagreed with what had actually been tested. Only
# Gate 3 on a real host surfaced it. These tests make the constraint mechanical.
SOCKET_PROXY_TMPFS_SAFE = {"v0.4.0", "v0.4.1", "v0.4.2"}

TAG_DOCS = ("deploy/demo.env.example", "deploy/README.md")


def workflow_socket_proxy_tag() -> str:
    """The tag demo-publish.yml resolves to a digest for the deploy bundle.

    Read from the PARSED yaml rather than the raw text: the comment sitting above
    the key names the broken versions, so a regex over the file would happily
    match those and pass while the real pin was wrong.
    """
    document = yaml.safe_load(read(".github/workflows/demo-publish.yml"))
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "SOCKET_PROXY_TAG" and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    assert len(found) == 1, f"expected exactly one SOCKET_PROXY_TAG, found {found}"
    return found[0].rsplit(":", 1)[1]


def test_published_socket_proxy_tag_survives_a_read_only_rootfs():
    tag = workflow_socket_proxy_tag()
    assert tag in SOCKET_PROXY_TMPFS_SAFE, (
        f"demo-publish.yml pins socket-proxy {tag!r}, which is not known to render "
        "haproxy.cfg onto a tmpfs path. Versions <= 0.3 write it to "
        "/usr/local/etc/haproxy/ and crash-loop under `read_only: true`. Confirm "
        "the new tag writes /tmp, then add it to SOCKET_PROXY_TMPFS_SAFE."
    )


def test_socket_proxy_tmpfs_covers_where_the_config_is_written():
    """The hardening and the tag are one decision; assert them together."""
    compose = yaml.safe_load(read("deploy/docker-compose.yml"))
    proxy = compose["services"]["socket-proxy"]
    assert proxy.get("read_only") is True, "socket-proxy lost its read-only rootfs"
    assert "/tmp" in proxy.get("tmpfs", []), (
        "socket-proxy renders haproxy.cfg to /tmp at startup; without a /tmp tmpfs "
        "the read-only rootfs makes it crash-loop"
    )


@pytest.mark.parametrize("relpath", TAG_DOCS)
def test_docs_recommend_the_socket_proxy_tag_that_is_published(relpath):
    """A local stack built on a different version than the published one is how
    the crash-loop got past Gate 1 in the first place."""
    tag = workflow_socket_proxy_tag()
    assert tag in read(relpath), (
        f"{relpath} never mentions socket-proxy {tag!r} — the version it steers "
        "operators toward can drift from the one demo-publish.yml pins"
    )


def test_frontend_refuses_to_start_a_demo_from_inside_a_frame():
    """netcanon's own nav links Dashboard at "/", which inside the iframe loads
    this page into the instance frame. Minting from there destroys the cookie's
    existing session — the very instance hosting the frame — so a mis-click cost
    the visitor their pasted config with no warning.

    The guard has to live in ``startDemo`` and not only in the boot path, or the
    three retry buttons still reach the mint.
    """
    code = frontend_code()
    assert "window.self !== window.top" in code, "no frame detection"
    assert "s-nested" in code, "no dedicated section for the framed case"
    body = code.split("function startDemo()", 1)
    assert len(body) == 2, "startDemo() not found — has it been renamed?"
    assert "isNested()" in body[1][:400], (
        "startDemo must refuse when framed; guarding only the boot path leaves "
        "btn-retry-rl / btn-retry-err / btn-retry-cap able to mint"
    )


def test_frontend_ends_sessions_on_pagehide_not_visibilitychange():
    """Ending on visibilitychange would destroy the instance on a mere tab
    switch — killing the demo's own copy-a-config-from-another-tab flow."""
    text = read(FRONTEND)
    assert "sendBeacon" in text
    beacon_line = next(line for line in text.splitlines() if "sendBeacon" in line)
    assert "visibilitychange" not in beacon_line
