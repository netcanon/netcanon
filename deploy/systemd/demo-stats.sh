#!/usr/bin/env bash
# netcanon demo — aggregate traffic sampler.
#
# The demo keeps no access log by design (claim 4), so the only traffic signal
# that exists is the warden's in-RAM counters plus Caddy's aggregate request
# metrics. Both are wiped by a restart, which means "how much traffic did the
# demo get?" is unanswerable without sampling them to disk.
#
# What this writes is deliberately narrow: totals only. No client IP, no path,
# no user-agent, no referrer, no per-session row — nothing with a visitor
# dimension. The warden's per-IP records stay in RAM and are never touched here.
# Disclosed in the whitepaper's "What we do see".
#
# Counters are cumulative-since-process-start and reset on restart, so
# `warden_uptime_s` is emitted alongside them: a consumer computing rates must
# treat a drop in uptime as a counter reset, exactly like a Prometheus counter.
set -euo pipefail

OUT=${DEMO_STATS_FILE:-/var/log/demo-stats.jsonl}
MAX_BYTES=${DEMO_STATS_MAX_BYTES:-10485760}   # 10 MiB, ~6 months at 5-min samples
HEALTH_URL=${DEMO_HEALTH_URL:-https://demo.netcanon.net/healthz}

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Validate before handing anything to --argjson: a partial response or a changed
# upstream shape must degrade to a null/empty field, never abort the sample or —
# worse — write a malformed line into the series.
json_or() {  # stdin -> stdout, falling back to $1 when the input is not JSON
  local fallback=$1 buf
  buf=$(cat)
  if [ -n "$buf" ] && printf '%s' "$buf" | jq empty >/dev/null 2>&1; then
    printf '%s' "$buf"
  else
    printf '%s' "$fallback"
  fi
}

# `|| true` is load-bearing: under `pipefail` a failed curl aborts the whole
# script, so an outage would leave a GAP in the series — indistinguishable from
# the timer not firing. Recording `warden: null` instead makes "the demo was
# down at this timestamp" an actual data point.
health=$( { curl -fsS --max-time 10 "$HEALTH_URL" 2>/dev/null || true; } | json_or 'null')

# Caddy's admin endpoint is not published; reach it inside the container.
metrics=$(docker exec deploy-caddy-1 wget -qO- http://127.0.0.1:2019/metrics 2>/dev/null || echo '')

# Status codes are NOT on caddy_http_requests_total (that carries only
# {handler,server}); they live on the duration histogram's _count series, which
# is labelled {code,handler,method,server}. Match the label by name rather than
# by position so a label-order change upstream cannot silently zero this.
http_by_code=$(printf '%s\n' "$metrics" | awk '
  /^caddy_http_request_duration_seconds_count\{/ {
    if (match($0, /code="[0-9]+"/)) {
      code = substr($0, RSTART + 6, RLENGTH - 7)
      total[code] += $NF
    }
  }
  END {
    printf "{"; sep = ""
    for (c in total) { printf "%s\"%s\":%d", sep, c, total[c]; sep = "," }
    printf "}"
  }' | json_or '{}')

http_total=$(printf '%s\n' "$metrics" \
  | awk '/^caddy_http_requests_total\{/ { n += $NF } END { print n + 0 }')

started=$(docker inspect deploy-warden-1 -f '{{.State.StartedAt}}' 2>/dev/null || echo '')
uptime_s=0
if [ -n "$started" ]; then
  uptime_s=$(( $(date -u +%s) - $(date -u -d "$started" +%s) ))
fi

# Rotate before appending so the file can never exceed the cap by more than one
# sample; keep one previous generation so a rotation does not lose a whole window.
if [ -f "$OUT" ] && [ "$(stat -c %s "$OUT")" -ge "$MAX_BYTES" ]; then
  mv -f "$OUT" "${OUT}.1"
fi

jq -cn \
  --arg ts "$ts" \
  --argjson health "$health" \
  --argjson http "$http_by_code" \
  --argjson http_total "${http_total:-0}" \
  --argjson uptime "$uptime_s" \
  '{ts: $ts, warden_uptime_s: $uptime, http_requests_total: $http_total,
    http_by_code: $http, warden: $health}' >> "$OUT"
