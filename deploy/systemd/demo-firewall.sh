#!/usr/bin/env bash
# Apply the demo-int isolation rules AFTER docker has created its DOCKER-USER
# chain, and ensure exactly one jump into them. Idempotent (safe to re-run).
set -euo pipefail
nft -f /opt/demo/deploy/nftables/demo-int.nft
# Ensure exactly one DOCKER-USER -> demo_isolation jump (insert only if absent).
if ! nft list chain ip filter DOCKER-USER 2>/dev/null | grep -q 'jump demo_isolation'; then
  nft insert rule ip filter DOCKER-USER jump demo_isolation
fi
