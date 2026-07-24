#!/usr/bin/env bash
# Apply the demo-int isolation rules AFTER docker has created its DOCKER-USER
# chain, and ensure exactly one jump into them. Idempotent (safe to re-run).
set -euo pipefail
nft -f /opt/demo/deploy/nftables/demo-int.nft
# Assert DOCKER-USER is visible to nft (iptables-nft backend). On the legacy
# backend it is invisible here and instances would run UNISOLATED — fail loudly
# rather than leaving a silent isolation gap.
if ! nft list chain ip filter DOCKER-USER >/dev/null 2>&1; then
  echo "demo-firewall: DOCKER-USER not visible to nft (iptables-legacy backend?) — isolation NOT applied" >&2
  exit 1
fi
# Ensure exactly one DOCKER-USER -> demo_isolation jump (insert only if absent).
if ! nft list chain ip filter DOCKER-USER 2>/dev/null | grep -q 'jump demo_isolation'; then
  nft insert rule ip filter DOCKER-USER jump demo_isolation
fi
