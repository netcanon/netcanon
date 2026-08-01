"""The no-telemetry claim, enforced (launch gate G4).

netcanon.net and the README state: **no telemetry, no phone-home, no update
checks — on any install path**, and the only network connections netcanon
makes are the SSH sessions you configure for backups (the only collectors
are Netmiko and Paramiko, both SSH — this PR also removed the README's
claim of NETCONF/REST fetchers that do not exist).

That sentence is only durably true if no module can quietly grow an HTTP
client. This test AST-walks every module in the shipped packages and fails
on any HTTP-client import, so the claim breaks in CI instead of on the
landing page.

``netcanon_desktop/server.py`` holds the single allowed exception: a
loopback-only readiness poll of its own embedded server
(``urllib.request.urlopen(self.url)`` against ``127.0.0.1``). Anything added
to the allowlist must be argued in review the way that entry was.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# Client libraries and stdlib client modules. Server-side frameworks
# (fastapi/starlette/uvicorn) are deliberately absent — serving HTTP is the
# product; *originating* HTTP is the claim under guard. `urllib.parse` and
# `http.HTTPStatus` are fine; `urllib.request` and `http.client` are not.
BANNED_MODULES = (
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "urllib.request",
    "http.client",
)

ALLOWED = {
    # Desktop shell: polls ITS OWN embedded server on loopback until the HTTP
    # layer answers, so the webview never opens onto a blank window.
    ("netcanon_desktop/server.py", "urllib.request"),
}


def _imported_modules(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            # `from urllib import request` must resolve to urllib.request.
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


@pytest.mark.parametrize("package", ("netcanon", "netcanon_desktop"))
def test_no_http_client_imports(package):
    violations = []
    for path in sorted((REPO_ROOT / package).rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for module in _imported_modules(path):
            hit = next(
                (b for b in BANNED_MODULES
                 if module == b or module.startswith(b + ".")),
                None,
            )
            if hit and (rel, hit) not in ALLOWED:
                violations.append(f"{rel}: imports {module}")
    assert not violations, (
        "HTTP-client import(s) contradict the published no-telemetry claim "
        "(netcanon.net + README):\n" + "\n".join(violations)
    )
