# netcanon demo — operator targets. Run ON THE HOST, from deploy/.
# Deploy is human-pulled (docs/demo-plan/02): no auto-deploy, no CI secrets.
SHELL := /bin/bash
COMPOSE := docker compose --env-file demo.env

# Gate-4 inputs. BUNDLE is the unpacked release bundle; DEMO_TAG is the exact
# demo-v<semver> tag whose workflow run signed it (the cosign identity is the
# workflow file AT that tag, so it cannot be inferred from the bundle).
BUNDLE  ?= .
DEMO_TAG ?=
REPO    ?= netcanon/netcanon

.PHONY: help verify verify-bundle promote whitepaper deploy drain down dev-up dev-down smoke-up smoke smoke-down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-11s %s\n",$$1,$$2}'

verify: ## Print pinned digests + compose sha256 (compare against the whitepaper)
	@echo "compose sha256:     $$(sha256sum docker-compose.yml | cut -d' ' -f1)"
	@echo "PINNED_PRODUCT_TAG: $$(cat PINNED_PRODUCT_TAG)"
	@grep -E '@sha256:' demo.env || true

# demo-publish.yml ships whitepaper-values.json with every digest it can know,
# but deliberately NOT the deploy date — CI cannot know when you deploy, and a
# wrong date in a trust document is worse than a visibly pending one. This target
# stamps today's date and renders the copy Caddy serves at /whitepaper.
# Run it from the unpacked bundle directory (needs whitepaper-values.json).
whitepaper: ## Fill the deploy date + render frontend/whitepaper.html for /whitepaper
	@test -f whitepaper-values.json || { echo "whitepaper-values.json not found — run from the unpacked bundle dir"; exit 1; }
	@jq --arg d "$$(date -u +%Y-%m-%d)" '. + {DEPLOY_DATE: $$d}' whitepaper-values.json > .wp-values.filled.json
	python3 ../tools/render_whitepaper.py \
		--in ../docs/DEMO_WHITEPAPER.md \
		--out ../frontend/whitepaper.html \
		--values .wp-values.filled.json
	@rm -f .wp-values.filled.json
	@echo "Rendered ../frontend/whitepaper.html — Caddy serves it at /whitepaper."

# Gate 4. SHA256SUMS is the one mutable, unsigned link in the chain, so
# demo-publish.yml cosign sign-blob's it; verify that signature FIRST and let the
# manifest vouch for every other asset. Fails closed — no cosign, no deploy —
# because a deploy target that silently skips verification is worse than one that
# never claimed to verify at all.
verify-bundle: ## Gate-4 — cosign-verify SHA256SUMS, then checksum the bundle (DEMO_TAG=demo-vX.Y.Z)
	@test -n "$(DEMO_TAG)" || { echo "usage: make verify-bundle DEMO_TAG=demo-v0.1.0 [BUNDLE=<dir>]"; exit 1; }
	@command -v cosign >/dev/null || { echo "cosign is not installed — Gate 4 cannot pass. See deploy/README.md."; exit 1; }
	cd $(BUNDLE) && cosign verify-blob SHA256SUMS \
		--bundle SHA256SUMS.cosign.bundle \
		--certificate-identity "https://github.com/$(REPO)/.github/workflows/demo-publish.yml@refs/tags/$(DEMO_TAG)" \
		--certificate-oidc-issuer https://token.actions.githubusercontent.com
	cd $(BUNDLE) && sha256sum -c SHA256SUMS
	@echo "Gate 4 OK — signature valid and every bundle file matches its published hash."

# Verifying a bundle and then deploying whatever `demo.env` happens to contain is
# theatre: the first real Gate-4 run verified demo-v0.1.0's signed digests and
# would have brought up the locally-built `:dev` images sitting in deploy/.
# `deploy` therefore PROMOTES the verified env into place first, and cannot be
# reached except through verify-bundle.
#
# ACME_EMAIL is the one value the bundle deliberately does not carry (operator
# data, not a build output), so it is preserved from the existing demo.env and
# the promotion refuses rather than deploying a Caddy that cannot start.
promote: verify-bundle ## Copy the VERIFIED bundle's digests into demo.env, keeping ACME_EMAIL
	@test -f demo.env || { echo "no demo.env — cp demo.env.example demo.env and set ACME_EMAIL"; exit 1; }
	@email="$$(grep '^ACME_EMAIL=' demo.env | cut -d= -f2-)"; \
	 case "$$email" in ""|REPLACE_WITH_OPERATOR_EMAIL|you@example.com) \
	   echo "set a real ACME_EMAIL in demo.env before deploying"; exit 1;; esac; \
	 sed "s|^ACME_EMAIL=.*|ACME_EMAIL=$$email|" $(BUNDLE)/demo.env > demo.env.promoted && \
	 mv demo.env.promoted demo.env && \
	 echo "demo.env now carries $(DEMO_TAG)'s verified digests (ACME_EMAIL preserved)."
	@grep -c '@sha256:' demo.env | xargs -I{} echo "  digest-pinned images in demo.env: {}"

deploy: promote ## Gate 4 → promote the verified env → pull pinned images + bring the stack up
	docker pull "$$(grep '^NETCANON_INSTANCE_IMAGE=' demo.env | cut -d= -f2-)"
	$(COMPOSE) pull
	$(COMPOSE) up -d

# Deliberately exits non-zero. The warden has no drain sentinel yet, and a target
# that prints a TODO and returns success is exactly what someone reaches for
# mid-incident and believes.
drain: ## NOT IMPLEMENTED — no warden drain sentinel exists; use `make down` (kills live sessions)
	@echo "make drain is NOT IMPLEMENTED — the warden exposes no drain sentinel."
	@echo "Intended design: loopback-only control (docs/demo-plan/02-deployment.md)."
	@echo "Today your options are: wait out HARD_TTL, or 'make down' (SIGTERM != drain)."
	@exit 1

down: ## Stop the stack (SIGTERM — kills live sessions by design)
	$(COMPOSE) down

dev-up: ## Local Gate-1: build warden+shim from source and run the stack
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up --build -d

dev-down: ## Tear down the local Gate-1 stack (+ volumes)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml down -v

# The live-smoke suite proves the claims that need a real daemon (module 08's
# "[O]" rows): hardening as APPLIED by dockerd, no egress, the authz shim and
# socket-proxy refusing on the wire, volume-reap, no Fernet key file.
smoke-up: ## Bring up the dev stack with the warden published for the live smoke
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml \
		-f docker-compose.smoke.yml up --build -d

smoke: ## Run the live-stack smoke suite (needs `make smoke-up` first)
	cd .. && NETCANON_DEMO_SMOKE=1 pytest tests/demo/test_live_stack_smoke.py -v

# Instances must be removed BEFORE the network can go, or `down` fails on
# demo-int still having endpoints attached.
smoke-down: ## Remove demo instances, then tear the smoke stack down
	-docker ps -aq --filter label=demo.instance | xargs -r docker rm -f
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml \
		-f docker-compose.smoke.yml down -v
