# Momentum developer commands. See CLAUDE.md §4 and docs/runbooks/local-development.md.
SHELL := /bin/bash
API := apps/api
WEB := apps/web
COMPOSE := docker compose -f infra/compose/docker-compose.dev.yml

.PHONY: help install db-up db-down dev dev-api dev-web migrate migration seed types e2e \
        check check-api check-web test-api test-web fmt build docker-build

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n",$$1,$$2}'

install: ## Install backend (uv) and frontend (pnpm) dependencies
	cd $(API) && uv sync
	cd $(WEB) && pnpm install

db-up: ## Start Postgres+pgvector in Docker (skip if you run Postgres natively)
	$(COMPOSE) up -d postgres

db-down: ## Stop the Docker Postgres
	$(COMPOSE) down

dev: ## Run API (reload, :8000) and web (Vite, :5173) together
	@trap 'kill 0' EXIT; \
	(cd $(API) && uv run momentum serve --reload --port 8000) & \
	(cd $(WEB) && pnpm dev) & \
	wait

dev-api: ## Run only the API with reload
	cd $(API) && uv run momentum serve --reload --port 8000

dev-web: ## Run only the Vite dev server
	cd $(WEB) && pnpm dev

migrate: ## Apply migrations
	cd $(API) && uv run momentum migrate

migration: ## Autogenerate a migration: make migration m="s1_1_1 teams"
	cd $(API) && uv run python -c "from alembic import command; from momentum.migrations_runner import alembic_config; from momentum.core.settings import Settings; command.revision(alembic_config(Settings()), message='$(m)', autogenerate=True)"

seed: ## Load the synthetic demo workspace
	cd $(API) && uv run momentum seed

types: ## Regenerate frontend API types from the backend OpenAPI schema
	cd $(API) && uv run python -m momentum.openapi_dump > ../../.openapi.json
	cd $(WEB) && pnpm exec openapi-typescript ../../.openapi.json -o src/momentum/lib/api/schema.d.ts
	rm -f .openapi.json

check: check-api check-web ## The quality gate (must be green)

check-api: ## Backend: format, lint, types, layering, tests
	cd $(API) && uv run ruff format --check momentum tests
	cd $(API) && uv run ruff check momentum tests
	cd $(API) && uv run mypy
	cd $(API) && uv run lint-imports
	cd $(API) && uv run pytest -q
	@$(MAKE) --no-print-directory types-check

types-check:
	@cd $(API) && uv run python -m momentum.openapi_dump > /tmp/momentum-openapi.json
	@cd $(WEB) && pnpm exec openapi-typescript /tmp/momentum-openapi.json -o /tmp/momentum-schema.d.ts >/dev/null 2>&1
	@diff -q /tmp/momentum-schema.d.ts $(WEB)/src/momentum/lib/api/schema.d.ts >/dev/null || (echo "Frontend API types are stale: run 'make types'"; exit 1)

check-web: ## Frontend: format, lint, types, tests
	cd $(WEB) && pnpm exec prettier --check .
	cd $(WEB) && pnpm exec eslint .
	cd $(WEB) && pnpm exec tsc -b --noEmit
	cd $(WEB) && pnpm exec vitest run

test-api:
	cd $(API) && uv run pytest -q

test-web:
	cd $(WEB) && pnpm exec vitest run

e2e: ## E2E journeys (real API + Postgres, throwaway *_e2e database, built SPA)
	cd $(WEB) && pnpm build && pnpm exec playwright test

fmt: ## Auto-format everything
	cd $(API) && uv run ruff format momentum tests && uv run ruff check --fix momentum tests
	cd $(WEB) && pnpm exec prettier --write .

build: ## Build the SPA into the API package (for a single-process local run)
	cd $(WEB) && pnpm build
	rm -rf $(API)/momentum/web/static && cp -r $(WEB)/dist $(API)/momentum/web/static

docker-build: ## Build the production image
	docker build -f infra/docker/Dockerfile -t momentum:local .
