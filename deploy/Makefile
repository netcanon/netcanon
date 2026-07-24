# netcanon demo — operator targets. Run ON THE HOST, from deploy/.
# Deploy is human-pulled (docs/demo-plan/02): no auto-deploy, no CI secrets.
SHELL := /bin/bash
COMPOSE := docker compose --env-file demo.env

.PHONY: help verify deploy drain down dev-up dev-down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-9s %s\n",$$1,$$2}'

verify: ## Print pinned digests + compose sha256 (compare against the whitepaper)
	@echo "compose sha256:     $$(sha256sum docker-compose.yml | cut -d' ' -f1)"
	@echo "PINNED_PRODUCT_TAG: $$(cat PINNED_PRODUCT_TAG)"
	@grep -E '@sha256:' demo.env || true

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
