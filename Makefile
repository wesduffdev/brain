# jarvis — common dev tasks.
# One-time:  make setup
# Then:      make test | make demo | make run | make up
#
# Everything runs against a local virtualenv at engine/.venv (gitignored), so
# `make test` behaves the same for everyone and in CI later. No global installs.

ENGINE := engine
VENV   := $(ENGINE)/.venv
PY     := $(VENV)/bin/python

.PHONY: help setup test demo run token migrate up down clean

help: ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

setup: ## create engine/.venv, install deps, install the git guardrail hooks
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r $(ENGINE)/requirements.txt
	git config core.hooksPath .githooks
	@echo "env ready + git hooks installed (no commits on main) — run 'make test'"

test: ## run the behavior suite
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m pytest

demo: ## watch the being drift (override count: make demo TICKS=600)
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.demo $(or $(TICKS),300)

run: ## serve the engine API on http://localhost:8000 (GET /state, WS /ws)
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 8000

token: ## mint a service JWT for the API (needs JWT_SECRET set; see .env.example)
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.auth_token

migrate: ## create the v0 database schema (needs DATABASE_URL set; see .env.example)
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.db.migrate

up: ## build + start the full stack (engine + postgres) via docker compose
	docker compose up --build

down: ## stop the stack and remove volumes
	docker compose down -v

clean: ## remove the local virtualenv
	rm -rf $(VENV)
