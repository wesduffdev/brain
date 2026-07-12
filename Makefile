# jarvis — common dev tasks.
# One-time:  make setup
# Then:      make test | make demo | make run | make up
#
# Everything runs against a local virtualenv at engine/.venv (gitignored), so
# `make test` behaves the same for everyone and in CI later. No global installs.

# Load .env (gitignored) if present so RUNTIME host targets see JWT_SECRET/DATABASE_URL
# etc. without a manual `export`. SCOPED on purpose: the secrets are exported only to
# the targets below, NOT to `test`/`demo`/`train`, which must stay zero-dependency
# (in-memory/sqlite) — a blanket export would force the lean suite onto Postgres.
# docker compose reads .env on its own; when .env is absent make still runs and
# compose's required-var guard still fires.
ifneq (,$(wildcard .env))
include .env
endif
# Scope the export to the runtime targets only. GNU Make 3.81 (the macOS default)
# does NOT support a bare `target: export VAR` list, so use the portable
# target-specific `export VAR := $(VAR)` form — one per secret — over the target list.
RUNTIME_TARGETS := token migrate run up down db-up kafka-up kafka-init serve-language consolidate
$(RUNTIME_TARGETS): export JWT_SECRET := $(JWT_SECRET)
$(RUNTIME_TARGETS): export DATABASE_URL := $(DATABASE_URL)
$(RUNTIME_TARGETS): export RENDERER_TOKEN := $(RENDERER_TOKEN)
$(RUNTIME_TARGETS): export JWT_ISSUER := $(JWT_ISSUER)
$(RUNTIME_TARGETS): export JWT_AUDIENCE := $(JWT_AUDIENCE)
$(RUNTIME_TARGETS): export JWT_TTL_SECONDS := $(JWT_TTL_SECONDS)
$(RUNTIME_TARGETS): export KAFKA_BOOTSTRAP_SERVERS := $(KAFKA_BOOTSTRAP_SERVERS)
$(RUNTIME_TARGETS): export OLLAMA_BASE_URL := $(OLLAMA_BASE_URL)

ENGINE := engine
VENV   := $(ENGINE)/.venv
PY     := $(VENV)/bin/python

.PHONY: help setup test demo run token db-up migrate train train-language serve-language consolidate up down clean kafka-up kafka-init

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

demo: ## watch the being alone with one object (make demo OBJ=ball TICKS=600; default hot lamp)
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.demo $(or $(TICKS),300) $(OBJ)

run: ## serve the engine API on http://localhost:8000 (GET /state, WS /ws)
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 8000

token: ## mint a service JWT for the API (needs JWT_SECRET set; see .env.example)
	@cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.auth_token

db-up: ## start Postgres alone and wait until it is accepting connections
	docker compose up -d --wait postgres

migrate: ## create the v0 database schema (needs DATABASE_URL set; see .env.example)
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.db.migrate

train: ## train the outcome predictor -> models/outcome_predictor.pt (installs torch on first run; minutes)
	$(PY) -m pip install --quiet -r $(ENGINE)/requirements-train.txt
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.ml.train_outcome_model

train-language: ## fine-tune our own language model on a document (host-native MLX-LM LoRA; Mac + mlx_lm) — make train-language DOC=path/to/doc.txt
	$(PY) -m pip install --quiet -r $(ENGINE)/requirements-finetune.txt
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.language.finetune "$(DOC)"

serve-language: ## serve our fine-tuned model via Ollama: fuse R1's LoRA -> GGUF -> `ollama create` on :11434 (host-native Mac + Ollama + the R1 adapter)
	$(PY) -m pip install --quiet -r $(ENGINE)/requirements-finetune.txt
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.language.serve

consolidate: ## force a knowledge-consolidation pass now (the being's 'sleep' fine-tune): synthesize pairs from the knowledge store -> host-native MLX-LM LoRA -> re-serve (Mac + mlx_lm + Ollama; needs DATABASE_URL)
	$(PY) -m pip install --quiet -r $(ENGINE)/requirements-finetune.txt
	cd $(ENGINE) && PYTHONPATH=. .venv/bin/python -m app.language.consolidation

kafka-up: ## start the Kafka broker (KRaft) and create the being.* topics + .dlq companions
	docker compose --profile events up -d --wait kafka
	$(MAKE) kafka-init

kafka-init: ## create/verify the being.* topics from config/events.yaml (broker at $$KAFKA_BOOTSTRAP_SERVERS, default localhost:9092)
	cd $(ENGINE) && PYTHONPATH=. KAFKA_BOOTSTRAP_SERVERS=$${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092} .venv/bin/python -m app.kafka_bootstrap

up: ## build + start the full stack (engine + postgres) via docker compose
	docker compose up --build

down: ## stop the stack and remove volumes
	docker compose down -v

clean: ## remove the local virtualenv
	rm -rf $(VENV)
