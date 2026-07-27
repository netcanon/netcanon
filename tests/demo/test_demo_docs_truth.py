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
import subprocess
import sys
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


# Claim 9 is "the published deployment is exactly reproducible". That holds only
# if EVERY image the stack pins appears in the reproducibility block. For
# demo-v0.1.0 the authz-shim did not: the workflow computed its digest and wrote
# it to demo.env, but never emitted it into whitepaper-values.json, and the block
# had no line for it — while VERIFY.md called it Trusted Computing Base and gave
# readers a cosign command for it. Five of six digests were verifiable.
PINNED_IMAGE_TO_WHITEPAPER_TOKEN = {
    "NETCANON_INSTANCE_IMAGE": "NETCANON_IMAGE_DIGEST",
    "WARDEN_IMAGE": "WARDEN_IMAGE_DIGEST",
    "WARDEN_SHIM_IMAGE": "SHIM_IMAGE_DIGEST",
    "SOCKET_PROXY_IMAGE": "SOCKET_PROXY_IMAGE_DIGEST",
    "CADDY_IMAGE": "CADDY_IMAGE_DIGEST",
}


def test_every_pinned_image_is_reproducible_from_the_whitepaper():
    """Three-way: the env template pins it, the whitepaper has a token for it,
    and the workflow actually emits that token's value."""
    env_keys = set(
        re.findall(r"^([A-Z_]*IMAGE)=", read("deploy/demo.env.example"), re.MULTILINE)
    )
    assert env_keys == set(PINNED_IMAGE_TO_WHITEPAPER_TOKEN), (
        "deploy/demo.env.example pins a different set of images than this map "
        f"knows about: {sorted(env_keys ^ set(PINNED_IMAGE_TO_WHITEPAPER_TOKEN))}. "
        "A new pinned image must also become publicly verifiable."
    )

    whitepaper = read("docs/DEMO_WHITEPAPER.md")
    workflow = read(".github/workflows/demo-publish.yml")
    for env_key, token in PINNED_IMAGE_TO_WHITEPAPER_TOKEN.items():
        assert f"<{token}>" in whitepaper, (
            f"{env_key} is pinned in the stack but <{token}> is absent from the "
            "whitepaper's reproducibility block — readers cannot verify it"
        )
        assert f'"{token}"' in workflow, (
            f"the whitepaper asks for <{token}> but demo-publish.yml never emits it "
            "into whitepaper-values.json, so it renders as an unfilled placeholder"
        )


# ── The release is immutable, so its completeness is a build-time property ───
def release_attach_list() -> list[str]:
    match = re.search(
        r"files: \|\n((?:\s+bundle/\S+\n)+)", read(".github/workflows/demo-publish.yml")
    )
    assert match, "could not find the release attach list in demo-publish.yml"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def test_release_asset_count_gate_matches_the_attach_list():
    """The pre-publish gate refuses to freeze a draft that does not hold exactly
    EXPECTED_ASSETS files. Add an asset and forget the counter and the gate either
    blocks every release or, worse, stops being able to notice a missing one."""
    workflow = read(".github/workflows/demo-publish.yml")
    expected = re.search(r'EXPECTED_ASSETS: "(\d+)"', workflow)
    assert expected, "the pre-publish asset-count gate is gone"
    attached = release_attach_list()
    assert len(attached) == int(expected.group(1)), (
        f"{len(attached)} assets are attached but the gate expects "
        f"{expected.group(1)} — these two move together"
    )


def test_every_published_asset_is_covered_by_sha256sums():
    """An asset attached to the release but missing from SHA256SUMS ships
    *unverifiable*: the cosign signature vouches for the manifest, and the
    manifest for everything it lists. Since the release is immutable, an asset
    that slips out uncovered can never be brought under the signature.

    SHA256SUMS and its own signature bundle are the two that cannot cover
    themselves.
    """
    workflow = read(".github/workflows/demo-publish.yml")
    block = re.search(r"sha256sum \\\n(.*?)> SHA256SUMS", workflow, re.DOTALL)
    assert block, "could not find the SHA256SUMS manifest generation"
    manifest = {
        line.strip().rstrip(" \\")
        for line in block.group(1).splitlines()
        if line.strip().rstrip(" \\")
    }
    attached = {Path(name).name for name in release_attach_list()}
    self_covering = {"SHA256SUMS", "SHA256SUMS.cosign.bundle"}
    uncovered = attached - manifest - self_covering
    assert not uncovered, (
        f"attached but not in SHA256SUMS, so published unverifiable: {sorted(uncovered)}"
    )
    orphaned = manifest - attached
    assert not orphaned, (
        f"in SHA256SUMS but never attached, so `sha256sum -c` fails for the "
        f"operator: {sorted(orphaned)}"
    )


def test_rendered_whitepaper_is_regenerated_from_the_markdown():
    """Every other ratchet in this file reads the MARKDOWN — but Caddy serves
    ``frontend/whitepaper.html``, and demo-publish.yml ships it as
    ``whitepaper-template.html``. That gap is not theoretical: when the backstop
    ceiling moved to 1320 s the markdown was corrected and this rendered copy was
    not, so the live demo spent weeks promising ``HARD_TTL + POOL_MAX_AGE =
    1200 s`` and "~20 min" — a *tighter* guarantee than the code delivers, which
    is the exact failure the ceiling fix existed to prevent.
    """
    result = subprocess.run(
        [sys.executable, "tools/render_whitepaper.py",
         "--in", "docs/DEMO_WHITEPAPER.md", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "frontend/whitepaper.html is stale relative to docs/DEMO_WHITEPAPER.md. "
        "Regenerate it:\n"
        "  python tools/render_whitepaper.py --in docs/DEMO_WHITEPAPER.md "
        "--out frontend/whitepaper.html\n\n" + result.stdout + result.stderr
    )


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


def test_deploying_does_not_write_into_the_tracked_tree():
    """`make whitepaper` renders the DEPLOY-specific copy — real digests, real
    deploy date. It used to write that over the tracked `frontend/whitepaper.html`,
    leaving the host's git tree permanently dirty: `git status` stopped being
    useful for spotting real drift, and a `git checkout` was blocked mid-deploy.

    Caddy now serves `deploy/site/`, which is gitignored. Pin all three halves —
    where the render goes, what Caddy mounts, and that the mount is ignored —
    because any one of them silently reverting reintroduces the dirty tree.
    """
    makefile = (REPO_ROOT / "deploy/Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("whitepaper:", 1)[1].split("\n\n", 1)[0]
    # Assert on the RENDER TARGET only. Matching the recipe text wholesale
    # false-positives on the target's own `@echo` explaining that the tracked
    # copy is left alone — the same prose-vs-code trap as the claim-10 guard.
    out = [ln.strip() for ln in recipe.splitlines() if "--out" in ln]
    assert out, "make whitepaper no longer passes --out"
    assert all("$(SITE)/whitepaper.html" in ln for ln in out), (
        f"make whitepaper renders to {out} — it must write into $(SITE); "
        "rendering over the tracked frontend copy is what dirties the host tree"
    )

    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "../frontend:/srv/frontend" not in compose, (
        "Caddy mounts the tracked frontend/ again — the served copy and the "
        "repo copy are the same file, so rendering dirties the tree"
    )
    assert "./site:/srv/frontend" in compose, "Caddy no longer serves deploy/site"

    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/site/" in ignored, "deploy/site is not gitignored — it IS the dirt"


def test_site_assembly_never_deletes_the_bind_mounted_directory():
    """`deploy/site` is bind-mounted into a RUNNING Caddy. Replacing it (rm -rf
    then recreate) leaves the container's mount pointing at a deleted inode, so
    Caddy keeps serving a directory nothing can write to and every static path
    breaks until the stack is recreated. Copy into it; never unlink it.
    """
    makefile = (REPO_ROOT / "deploy/Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nsite:", 1)[1].split("\n\n", 1)[0]
    for destructive in ("rm -rf $(SITE)", "rm -rf site"):
        assert destructive not in recipe, (
            f"`make site` runs `{destructive}` on a directory bind-mounted into a "
            "live Caddy — that orphans the mount and blanks the site"
        )


def test_ci_lints_the_warden():
    """`demo/` is the demo's trusted computing base — the session manager and the
    authz shim standing between a visitor and the docker socket — and for its
    whole life it sat outside CI's ruff scope. It happened to be clean, which is
    luck, not a property. Pin the scope so narrowing it fails here.
    """
    data = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = [s for job in data["jobs"].values() for s in (job.get("steps") or [])]
    ruff = [s for s in steps if "ruff check" in str(s.get("run", ""))]
    assert ruff, "ci.yml no longer runs `ruff check` at all"
    for step in ruff:
        # Compare tokens, not a substring: "demo" appears inside other words.
        targets = str(step["run"]).split("ruff check", 1)[1].split()
        assert "demo" in targets, (
            f"ci.yml lints {targets} — `demo` is missing, so the warden (the TCB, "
            "and the one file the whitepaper asks people to read) is unlinted"
        )


@pytest.mark.parametrize(
    "doc", ("docs/demo-plan/03-warden-spec.md", "deploy/README.md")
)
def test_every_refusal_reason_is_documented(doc):
    """`/healthz` splits refusals by cause, and an operator reads those numbers
    to decide whether the box needs resizing. A reason that exists in the code
    but in no document is a number nobody can interpret.

    This is the exact drift that already happened here: deploy/README.md carried
    a caveat calling the split "open work" after it had shipped. Adding a fourth
    reason without saying what it means now fails instead.
    """
    import ast

    src = (REPO_ROOT / "demo/warden/app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Read the reasons out of the `_counters` literal rather than importing the
    # module: app.py imports the docker SDK, which CI deliberately does not have.
    reasons: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and ast.unparse(node.func) == "dict.fromkeys"):
            continue
        names = {n.value for n in ast.walk(node.args[0]) if isinstance(n, ast.Constant)}
        if "rate_limited" in names:
            reasons = sorted(names)
    assert reasons, "could not find the refusals_by_reason literal in app.py"

    text = (REPO_ROOT / doc).read_text(encoding="utf-8")
    missing = [r for r in reasons if r not in text]
    assert not missing, (
        f"{doc} never mentions refusal reason(s) {missing} — an operator reading "
        "these counters would have no way to know what they mean"
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


def test_cloud_init_installs_every_systemd_unit_in_the_repo():
    """`deploy/systemd/` is installed by an explicit, hand-maintained list in
    cloud-init — the same shape as the Dockerfile COPY list, and it rots the same
    way. A unit added to the repo but not to cloud-init simply never runs on the
    host, silently."""
    cloud_init = read("deploy/cloud-init.yaml")
    on_disk = {path.name for path in (REPO_ROOT / "deploy" / "systemd").iterdir()}
    assert on_disk, "found no systemd units — the glob has rotted"
    missing = {name for name in on_disk if name not in cloud_init}
    assert not missing, (
        f"deploy/systemd units never installed by cloud-init: {sorted(missing)}"
    )


def test_the_traffic_sampler_records_no_visitor_dimension():
    """The sampler is the one thing on this host that persists anything at all,
    so what it may collect is pinned rather than trusted to review. The whitepaper
    promises totals only; these are the fields that would break that promise."""
    # Strip comments first: the script's own comment promises "no user-agent, no
    # referrer", and a raw substring check reads that promise as a violation —
    # the same trap the claim-10 frontend guard hit.
    script = "\n".join(
        line.split("#", 1)[0]
        for line in read("deploy/systemd/demo-stats.sh").splitlines()
    )
    forbidden = (
        "remote_ip", "X-Forwarded-For", "x-forwarded-for", "client_ip",
        "user-agent", "User-Agent", "referer", "Referer", "_per_ip",
    )
    for field in forbidden:
        assert field not in script, (
            f"demo-stats.sh references {field!r} — the whitepaper says the sampler "
            "records no visitor dimension"
        )
    assert "healthz" in script, "the sampler no longer reads the aggregate counters"


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


def test_bundle_assets_are_read_through_the_bundle_variable():
    """Twice now the deploy flow reached for a bundle asset in the wrong place:
    ``deploy`` read ``demo.env`` from deploy/ after verifying the bundle's copy,
    and ``whitepaper`` looked for ``whitepaper-values.json`` in the cwd while the
    unpacked bundle put it in ./bundle. Both only surfaced by running the real
    Gate-4 flow. Any recipe naming a bundle-only asset must reach it via
    ``$(BUNDLE)``.
    """
    text = read("deploy/Makefile")
    recipes: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^([a-z][a-z0-9-]*):", line)
        if match:
            current = match.group(1)
            recipes[current] = []
        elif current and line.startswith("\t"):
            recipes[current].append(line)
        elif line.strip() and not line.startswith((" ", "\t")):
            current = None

    assert recipes, "no Makefile recipes parsed — the parser has rotted"
    for name, body in recipes.items():
        joined = "\n".join(body)
        for asset in ("whitepaper-values.json", "SHA256SUMS"):
            if asset in joined:
                assert "$(BUNDLE)" in joined, (
                    f"`make {name}` reads {asset} but never mentions $(BUNDLE) — it "
                    "will look in deploy/ while the unpacked bundle put it elsewhere"
                )


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
