# hospital-sys: the single entry point for common commands (docs/ARCHITECTURE.md section 2).
# Works from the repo root or via `make -C <repo>`. Compatible with GNU Make 3.81 (macOS default).
#
# Parallel-safe: no hardcoded DB names or ports. Dev ports come from BACKEND_PORT / FRONTEND_PORT
# or are derived per worktree by scripts/ports.sh. DB connection uses PGHOST/PGPORT/PGUSER/
# PGPASSWORD and DB_NAME (default hospital_dev).

SHELL := /bin/bash

ROOT     := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
BACKEND  := $(ROOT)/backend
FRONTEND := $(ROOT)/frontend
E2E      := $(ROOT)/e2e
AGENT    := $(ROOT)/agent
SCRIPTS  := $(ROOT)/scripts

UV   ?= uv
PNPM ?= pnpm
MANAGE := $(UV) run python manage.py

# Optional Playwright filter: make e2e E2E_GREP=@billing
E2E_GREP ?=

.DEFAULT_GOAL := help

.PHONY: help setup setup-backend setup-frontend setup-e2e db migrate dev \
        test test-backend test-frontend \
        lint lint-backend lint-frontend lint-shell \
        typecheck typecheck-backend typecheck-frontend typecheck-e2e \
        api api-check e2e seed check clean distclean \
        agent-setup agent-test agent-lint infra-test ports repo-hash

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------- setup

setup: setup-backend setup-frontend setup-e2e db migrate ## uv sync, pnpm install (frontend, e2e), create dev DB, migrate

setup-backend:
	cd "$(BACKEND)" && $(UV) sync

setup-frontend:
	cd "$(FRONTEND)" && $(PNPM) install

setup-e2e:
	cd "$(E2E)" && $(PNPM) install
	@# A no-op when this Playwright version's chromium is already installed.
	cd "$(E2E)" && $(PNPM) exec playwright install chromium

db: ## Create the dev database (DB_NAME, default hospital_dev) if missing
	"$(SCRIPTS)/db-create.sh"

migrate: ## Apply Django migrations to the dev database
	cd "$(BACKEND)" && $(MANAGE) migrate

# ---------------------------------------------------------------------------- dev

dev: ## Backend and frontend together on per-worktree ports; Ctrl-C stops both
	"$(SCRIPTS)/dev.sh"

ports: ## Print the BACKEND_PORT / FRONTEND_PORT this worktree uses
	@"$(SCRIPTS)/ports.sh"

repo-hash: ## Print this worktree's 8-char id (test/e2e DB suffix)
	@"$(SCRIPTS)/repo-hash.sh"

# ---------------------------------------------------------------------------- quality

test: test-backend test-frontend ## Backend pytest (incl. Hypothesis) + frontend vitest

test-backend:
	cd "$(BACKEND)" && $(UV) run pytest

test-frontend:
	cd "$(FRONTEND)" && $(PNPM) test

lint: lint-backend lint-frontend lint-shell ## ruff check + ruff format --check + eslint + prettier + shell syntax

lint-backend:
	cd "$(BACKEND)" && $(UV) run ruff check .
	cd "$(BACKEND)" && $(UV) run ruff format --check .
	@# A model change committed without its migration would reach production as schema drift
	@# (and without the pgtrigger/pghistory protections that migrations install).
	cd "$(BACKEND)" && $(UV) run python manage.py makemigrations --check --dry-run

lint-frontend:
	cd "$(FRONTEND)" && $(PNPM) lint
	cd "$(FRONTEND)" && $(PNPM) format:check

lint-shell:
	"$(SCRIPTS)/lint-shell.sh"

typecheck: typecheck-backend typecheck-frontend typecheck-e2e ## mypy + tsc --noEmit (frontend and e2e)

typecheck-backend:
	cd "$(BACKEND)" && $(UV) run mypy

typecheck-frontend:
	cd "$(FRONTEND)" && $(PNPM) typecheck

typecheck-e2e:
	cd "$(E2E)" && $(PNPM) typecheck

# ---------------------------------------------------------------------------- API contract

api: ## Export OpenAPI to frontend/openapi.json and regenerate src/lib/api/schema.d.ts
	cd "$(BACKEND)" && $(MANAGE) export_openapi --output ../frontend/openapi.json
	cd "$(FRONTEND)" && $(PNPM) gen:api

api-check: api ## Regenerate the API contract and fail if it differs from git
	"$(SCRIPTS)/api-check.sh"

# ---------------------------------------------------------------------------- e2e and data

e2e: ## Reset e2e DB, seed, start servers on free ports, run Playwright (E2E_GREP=...)
	E2E_GREP="$(E2E_GREP)" "$(SCRIPTS)/e2e.sh"

seed: migrate ## Load the demo dataset into the dev DB (seed_demo when present, else seed_e2e)
	@cd "$(BACKEND)" && if $(MANAGE) help seed_demo >/dev/null 2>&1; then \
		echo "seed: running seed_demo"; $(MANAGE) seed_demo; \
	else \
		echo "seed: seed_demo not available yet; running seed_e2e (users, center profile, policy)"; \
		ALLOW_SEED_E2E=1 $(MANAGE) seed_e2e; \
	fi

check: ## lint + typecheck + test + api drift. Must be green before any commit to main
	@$(MAKE) --no-print-directory -f "$(ROOT)/Makefile" lint
	@$(MAKE) --no-print-directory -f "$(ROOT)/Makefile" typecheck
	@$(MAKE) --no-print-directory -f "$(ROOT)/Makefile" test
	@$(MAKE) --no-print-directory -f "$(ROOT)/Makefile" api-check
	@echo "check: all green"

# ---------------------------------------------------------------------------- agent and infra

agent-setup: ## Install the local device agent's environment
	cd "$(AGENT)" && $(UV) sync

agent-test: ## Device agent tests (dry-run printers)
	cd "$(AGENT)" && $(UV) run pytest

agent-lint: ## Device agent ruff + mypy
	cd "$(AGENT)" && $(UV) run ruff check . && $(UV) run ruff format --check . && $(UV) run mypy

infra-test: lint-shell ## Shell syntax + backup/restore and update.sh tests (needs local Postgres for backup tests)
	bash "$(ROOT)/infra/tests/run.sh"

# ---------------------------------------------------------------------------- cleanup

clean: ## Remove caches and build output (keeps .venv and node_modules)
	rm -rf "$(BACKEND)/.pytest_cache" "$(BACKEND)/.mypy_cache" "$(BACKEND)/.ruff_cache" \
	       "$(BACKEND)/.hypothesis" "$(BACKEND)/htmlcov" "$(BACKEND)/.coverage" "$(BACKEND)/staticfiles"
	rm -rf "$(FRONTEND)/dist" "$(FRONTEND)/.vite" "$(FRONTEND)/coverage"
	rm -rf "$(E2E)/test-results" "$(E2E)/playwright-report" "$(E2E)/.logs" "$(E2E)/.auth"
	rm -rf "$(AGENT)/.pytest_cache" "$(AGENT)/.mypy_cache" "$(AGENT)/.ruff_cache" \
	       "$(AGENT)/build" "$(AGENT)/dist" "$(AGENT)/print-out"
	find "$(BACKEND)" "$(AGENT)" -type d -name __pycache__ -not -path '*/.venv/*' -prune -exec rm -rf {} + 2>/dev/null || true

distclean: clean ## clean + remove .venv and node_modules
	rm -rf "$(BACKEND)/.venv" "$(AGENT)/.venv" "$(FRONTEND)/node_modules" "$(E2E)/node_modules"
