#!/usr/bin/env bash
# Warden-independent hard-TTL backstop (invariant I3). Force-removes any
# demo.*-labelled container that is either older than
# HARD_TTL + POOL_MAX_AGE + slack = 1320s, OR whose demo.created_at label is
# missing / non-numeric (an anomalous instance the warden did not label — remove
# it, adopt nothing). Provably later than any live session's 900s
# assignment-relative deadline. Swept every 60s by the paired timer.
set -euo pipefail
CEILING=1320
now=$(date +%s)
for cid in $(docker ps -aq --filter "label=demo.instance"); do
  created=$(docker inspect -f '{{ index .Config.Labels "demo.created_at" }}' "$cid" 2>/dev/null || echo "")
  case "$created" in
    '' | *[!0-9]*)
      docker rm -fv "$cid" >/dev/null 2>&1 || true
      continue
      ;;
  esac
  if [ "$((now - created))" -gt "$CEILING" ]; then
    docker rm -fv "$cid" >/dev/null 2>&1 || true
  fi
done
