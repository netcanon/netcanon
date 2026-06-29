#!/usr/bin/env bash
#
# Regenerate ``requirements.lock`` -- the hash-pinned dependency manifest for
# the shipped Docker image (audit e5b77d7 finding #5: "no pinned/hash-locked
# dependency manifest for shipped artifacts").
#
# The lock is resolved INSIDE the exact digest-pinned base image the runtime
# uses, so the pinned versions + hashes match the deploy platform (linux/amd64,
# CPython 3.14) -- a lock resolved on another OS/Python would carry the wrong
# wheels and break ``pip --require-hashes`` in the Dockerfile.
#
# The PyPI sdist/wheel deliberately does NOT use this lock: that artifact is a
# *library*, and a library must keep pyproject's version *ranges* so downstream
# resolvers can co-install it.  The lock constrains the *application* (the
# container), which is the thing finding #5 is about.
#
# Run it from a POSIX shell with Docker available (Linux / macOS / WSL):
#   tools/gen_requirements_lock.sh
# then commit the regenerated requirements.lock.  ``tests/unit/
# test_requirements_lock.py`` fails if the committed lock drifts out of sync
# with pyproject's declared dependencies.
set -euo pipefail

# Keep this digest in lock-step with the FROM lines in Dockerfile.
BASE="python:3.14.5-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Extract [project.dependencies] verbatim into a requirements.in (no project
# build -- keeps the resolution hermetic and independent of setuptools_scm/git).
python3 - "$ROOT/pyproject.toml" "$WORK/requirements.in" <<'PY'
import sys
import tomllib

data = tomllib.load(open(sys.argv[1], "rb"))
deps = data["project"]["dependencies"]
with open(sys.argv[2], "w", newline="\n") as f:
    f.write("\n".join(deps) + "\n")
PY

docker run --rm -v "$WORK:/w" -w /w "$BASE" bash -c '
  set -e
  apt-get update -qq && apt-get install -y -qq build-essential libffi-dev libssl-dev >/dev/null 2>&1
  pip install -q pip-tools
  pip-compile --quiet --generate-hashes --strip-extras \
    --output-file requirements.lock requirements.in
'

cp "$WORK/requirements.lock" "$ROOT/requirements.lock"
echo "wrote $ROOT/requirements.lock"
