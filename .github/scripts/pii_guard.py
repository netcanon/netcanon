#!/usr/bin/env python3
"""PII guard: fail when a tracked file, or a commit being merged, carries a maintainer identifier.

The guard must never itself be the leak. So it holds no identifier in readable form, and a finding
names the file, line and rule, never the matched text. Three layers:

  1. STRUCTURAL (built in, names nobody): an operator-machine user-profile path, in any spelling
     (drive-letter with single, doubled or forward slashes, and the Git-Bash /c/... form).
  2. DIGESTS (.github/pii-guard.hashes): sha256 digests of identifiers that must never ship, such
     as the maintainer's personal email address and its local part. Each alphanumeric run and each
     email-shaped string in the scanned text is hashed and looked up. The file publishes digests
     only: it can confirm a guess, never reveal a value.
  3. PRIVATE TOKENS (optional): regexes, one per line, from $PII_GUARD_TOKENS (CI injects a
     repository secret; it is absent on fork and Dependabot PRs) for the names that identify one
     deployment: hostnames, domains, cluster ids, LAN prefixes.

Layer 2 also checks each line with `[`, `]` and `\\` removed, because the usual way to keep a
grep pattern from matching itself (`ab[c]d`) still publishes the identifier it spells.

Escape hatch: a same-line `pii-guard: allow <reason>` marker exempts that line, visibly, in review.

Usage:
    pii_guard.py --tree                 every git-tracked text file
    pii_guard.py --range BASE HEAD      author/committer identities + messages of BASE..HEAD
                                        (CI: an empty or all-zero BASE means HEAD alone)
    pii_guard.py --commits REV...       the same, for any `git log` revision arguments
                                        (the pre-push hook: `<sha> --not --remotes`, `A..B`)
    --no-paths                          (with any scan) skip layer 1: for a PRIVATE repo
                                        whose working notes name operator paths; drop it before
                                        the repo goes public
    pii_guard.py --hash                 identifiers on stdin -> digest lines for the hashes file
    pii_guard.py --self-test            each layer fires on a synthetic canary; clean text passes
Exit 0 clean, 1 finding, 2 the scan could not run (fail closed).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

SALT = b"pii-guard/v1:"
ALLOW_MARK = "pii-guard: allow"
MAX_BYTES = 16_000_000
HASHES_REL = ".github/pii-guard.hashes"
# The canary's digest ships in every hashes file, so --self-test proves layer 2 fires on every
# checkout and a scan that finds nothing is never a scan that checked nothing.
CANARY = "piiguard" + "canary" + "7f3a"

# Layer 1. Character classes ([u]) keep this file from holding the contiguous literal it hunts.
_PROFILE_PATH = re.compile(
    r"(?i)(?<![a-z0-9])[a-z]:(?:\\|/)+[u]sers(?:\\|/)+"  # drive letter, any slash spelling
    r"|(?<![\w.])/[a-z]/[u]sers/"  # the Git-Bash /c/... form
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_WORD = re.compile(r"[A-Za-z0-9]{4,}")
_OBFUSCATION = re.compile(r"[\[\]\\]")


def digest(identifier: str) -> str:
    """sha256 over the salted, lower-cased identifier: the one digest form the hashes file holds."""
    return hashlib.sha256(SALT + identifier.strip().lower().encode("utf-8")).hexdigest()


def load_digests(root: Path) -> set[str]:
    """The digests in .github/pii-guard.hashes (first field per line). A missing file fails."""
    path = root / HASHES_REL
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        field = line.split("#", 1)[0].split()
        if field:
            if not re.fullmatch(r"[0-9a-f]{64}", field[0]):
                raise ValueError(f"{HASHES_REL}: not a sha256 digest: {field[0][:12]}...")
            out.add(field[0])
    return out


def load_tokens() -> list[re.Pattern[str]]:
    """Layer-3 regexes from $PII_GUARD_TOKENS, one per line. Unset means no layer 3."""
    raw = os.environ.get("PII_GUARD_TOKENS", "")
    lines = [t.strip() for t in raw.splitlines()]
    return [re.compile(t, re.IGNORECASE) for t in lines if t and not t.startswith("#")]


class Scanner:
    def __init__(self, digests: set[str], tokens: list[re.Pattern[str]], paths: bool = True):
        self.digests = digests
        self.tokens = tokens
        self.paths = paths
        self._seen: dict[str, bool] = {}

    def _listed(self, tok: str) -> bool:
        key = tok.lower()
        hit = self._seen.get(key)
        if hit is None:
            hit = self._seen[key] = digest(key) in self.digests
        return hit

    def _identifier(self, line: str) -> str | None:
        for m in _EMAIL.finditer(line):
            email = m.group(0)
            if self._listed(email) or self._listed(email.split("@", 1)[0]):
                return "listed identifier (email)"
        for m in _WORD.finditer(line):
            if self._listed(m.group(0)):
                return "listed identifier"
        return None

    def line_findings(self, line: str) -> list[str]:
        """Rule labels that fire on one line. Labels never include the matched text."""
        if ALLOW_MARK in line:
            return []
        out = []
        if self.paths and _PROFILE_PATH.search(line):
            out.append("user-profile path")
        hit = self._identifier(line)
        if hit is None:
            # A regex that spells an identifier with character classes or escapes (`ab[c]d`, `a\.b`)
            # to dodge matching itself still publishes it: check the line with those stripped too.
            squashed = _OBFUSCATION.sub("", line)
            if squashed != line:
                hit = self._identifier(squashed)
                if hit:
                    hit += ", spelled with [] or \\"
        if hit:
            out.append(hit)
        for n, pat in enumerate(self.tokens, 1):
            m = pat.search(line)
            if m:
                out.append(f"private token#{n} sha256:{digest(m.group(0))[:8]}")
        return out

    def text_findings(self, text: str) -> list[tuple[int, str]]:
        lines = enumerate(text.splitlines(), 1)
        return [(ln, rule) for ln, line in lines for rule in self.line_findings(line)]


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def scan_tree(root: Path, sc: Scanner) -> tuple[list[str], int]:
    findings, skipped = [], 0
    for rel in git(root, "ls-files", "-z").decode("utf-8").split("\0"):
        if not rel:
            continue
        path = root / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > MAX_BYTES or b"\0" in data[:8192]:
            skipped += 1
            continue
        text = data.decode("utf-8", errors="replace")
        findings += [f"{rel}:{ln}: {rule}" for ln, rule in sc.text_findings(text)]
    return findings, skipped


def range_revs(base: str, head: str) -> list[str]:
    """CI's BASE..HEAD. An empty or all-zero BASE (new branch, first push) means HEAD alone."""
    return ["-1", head] if not base or set(base) == {"0"} else [f"{base}..{head}"]


def scan_commits(root: Path, sc: Scanner, revs: list[str]) -> list[str]:
    """Author, committer and message of every commit `git log <revs>` lists."""
    findings = []
    out = git(root, "log", "--format=%H%x00%an <%ae>%x00%cn <%ce>%x00%B%x1e", *revs, "--")
    for rec in out.decode("utf-8", errors="replace").split("\x1e"):
        parts = rec.strip("\n").split("\0")
        if len(parts) < 4:
            continue
        sha, author, committer, body = parts[0][:10], parts[1], parts[2], parts[3]
        for field, text in (("author", author), ("committer", committer), ("message", body)):
            hits = sc.text_findings(text)
            findings += [f"commit {sha} {field}:{ln}: {rule}" for ln, rule in hits]
    return findings


def self_test(root: Path) -> list[str]:
    """Each layer must fire on a synthetic canary, and clean text must pass. Returns failures."""
    fails = []
    try:
        digests = load_digests(root)
    except (OSError, ValueError) as e:
        return [f"hashes file unreadable: {e}"]
    if digest(CANARY) not in digests:
        fails.append(f"{HASHES_REL} lacks the canary digest (layer 2 would be unproven)")
    sc = Scanner(digests, [re.compile("canary-lab" + r"\.invalid", re.I)])
    profile = "C:" + "\\" + "Us" + "ers" + "\\someone\\repo"
    cases = {
        "layer 1 (profile path)": (f"see {profile}", "user-profile path"),
        "layer 1 (git-bash path)": ("cd /c/" + "Us" + "ers/someone/x", "user-profile path"),
        "layer 2 (word)": (f"by {CANARY} today", "listed identifier"),
        "layer 2 (email)": (f"mail {CANARY}@example.invalid", "listed identifier (email)"),
        "layer 2 (char-class spelling)": (
            f"grep -E '{CANARY[:3]}[{CANARY[3]}]{CANARY[4:]}'",
            "listed identifier",
        ),
        "layer 3 (private token)": ("host.canary-lab.invalid", "private token#1"),
    }
    for name, (text, want) in cases.items():
        got = sc.line_findings(text)
        if not any(r.startswith(want) for r in got):
            fails.append(f"{name} did not fire")
    if sc.line_findings(f"{CANARY} {profile}  # {ALLOW_MARK} self-test"):
        fails.append("the allow marker did not exempt its line")
    if sc.line_findings("C:/Program Files/app and /usr/share/doc and user@example.com"):
        fails.append("clean text was flagged")
    return fails


def main(argv: list[str]) -> int:
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    if argv[:1] == ["--hash"]:
        for ident in sys.stdin.read().splitlines():
            if ident.strip():
                print(digest(ident))
        return 0
    if argv[:1] == ["--self-test"]:
        fails = self_test(root)
        for f in fails:
            print(f"::error::pii-guard self-test: {f}")
        ok = "every layer fires on its canary; clean text passes"
        print("pii-guard self-test: " + ("FAILED" if fails else ok))
        return 1 if fails else 0
    paths = "--no-paths" not in argv
    argv = [a for a in argv if a != "--no-paths"]
    sc = Scanner(load_digests(root), load_tokens(), paths=paths)
    layer3 = (
        f"{len(sc.tokens)} private token(s)"
        if sc.tokens
        else "no private tokens (secret unset, fork or Dependabot PR)"
    )
    if not paths:
        layer3 += "; user-profile path layer OFF (--no-paths)"
    if argv[:1] == ["--tree"]:
        findings, skipped = scan_tree(root, sc)
        what = f"tracked files ({skipped} binary/oversize skipped)"
    elif argv[:1] == ["--range"] and len(argv) == 3:
        revs = range_revs(argv[1], argv[2])
        findings, what = scan_commits(root, sc, revs), "commits " + " ".join(r[:21] for r in revs)
    elif argv[:1] == ["--commits"] and len(argv) > 1:
        findings, what = scan_commits(root, sc, argv[1:]), "commits " + " ".join(argv[1:])
    else:
        print(__doc__)
        return 2
    for f in findings:
        print(f"::error::{f}")
    print(f"pii-guard: {len(findings)} finding(s) in {what}; {len(sc.digests)} digest(s), {layer3}")
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print(f"::error::pii-guard could not run: {e}")
        sys.exit(2)
