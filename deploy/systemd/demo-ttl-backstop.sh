#!/usr/bin/env bash
# Warden-independent hard-TTL backstop (invariant I3). Force-removes any
# demo.*-labelled container whose demo.created_at is older than
# HARD_TTL + POOL_MAX_AGE = 1200s. Holds the creation-age ceiling even when the
# warden is dead. Provably looser than any live session's 900s assignment-relative
# deadline, so it never fires early. Swept every 60s by the paired timer.
set -euo pipefail
CEILING=1200
now=$(date +%s)
for cid in $(docker ps -aq --filter "label=demo.instance"); do
  created=$(docker inspect -f '{{ index .Config.Labels "demo.created_at" }}' "$cid" 2>/dev/null || echo 0)
  case "$created" in '' | *[!0-9]*) continue ;; esac
  if [ "$((now - created))" -gt "$CEILING" ]; then
    docker rm -fv "$cid" >/dev/null 2>&1 || true
  fi
done
