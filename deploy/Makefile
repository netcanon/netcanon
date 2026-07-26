# netcanon demo — operator targets. Run ON THE HOST, from deploy/.
# Deploy is human-pulled (docs/demo-plan/02): no auto-deploy, no CI secrets.
SHELL := /bin/bash
COMPOSE := docker compose --env-file demo.env

.PHONY: help verify whitepaper deploy drain down dev-up dev-down

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

deploy: ## Pull pinned images + bring the stack up (TODO Gate-4: verify signatures/SHA256SUMS first)
	docker pull "$$(grep '^NETCANON_INSTANCE_IMAGE=' demo.env | cut -d= -f2-)"
	$(COMPOSE) pull
	$(COMPOSE) up -d

drain: ## Stop minting new sessions (loopback control); let sessions lapse
	@echo "TODO(Gate-1): trip the warden drain sentinel (loopback-only). SIGTERM != drain."

down: ## Stop the stack (SIGTERM — kills live sessions by design)
	$(COMPOSE) down

dev-up: ## Local Gate-1: build warden+shim from source and run the stack
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up --build -d

dev-down: ## Tear down the local Gate-1 stack (+ volumes)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml down -v
