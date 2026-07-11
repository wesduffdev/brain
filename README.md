# jarvis — situated-being ML simulation

A simulated **being** — human-like in psychology (needs, emotions, curiosity,
memory, learned expectations). The long-term goal is a hybrid brain:
authored rules + a small neural network for narrow prediction, rendered in 2D,
running across Docker services. The near-term goal is to learn ML by building
that loop one honest slice at a time.

The full target architecture lives in [`docs/BRIEF.md`](docs/BRIEF.md) —
Postgres, PyTorch, FastAPI/WebSocket, PixiJS, Docker Compose. This repo builds
toward it in vertical slices; the roadmap below tracks what is actually here
today.

## What exists today

A being whose **needs drift over ticks (config-driven)** and whose **dominant
emotion is derived from those needs**; it **perceives the objects in its room**
(each with a confidence); and it is exposed over an **authenticated HTTP +
WebSocket API** (always-on JWT), runnable as a **Docker Compose stack** (engine +
postgres). A first **outcome-predictor** model can be **trained on a synthetic
seed set** (`ml-trainer` sidecar / `make train`) into `models/outcome_predictor.pt`.
No database code, actions, renderer, or shadow-mode inference yet — those are
later slices.

```
config/
  tick_rates.yaml         # need drift + bands (the time-tuning surface)
  emotions.yaml           # how needs derive one dominant emotion (fear included)
  rooms.yaml              # the room and the objects it contains
  object_properties.yaml  # object property/affordance vocabulary + objects
  outcome_labels.yaml     # outcome-predictor vocab: labels + context + training
engine/
  app/
    config_service.py     # YAML/dict -> typed policies (the only config-aware code)
    simulation.py         # the public interface: tick(), state()
    main.py               # FastAPI: GET /state + WebSocket /ws tick stream
    domain/               # BeingState, Room, ObjectEntity, emotion vocabulary
    services/             # Tick, Need, Emotion, Perception services
    ml/                   # outcome predictor: encode_features, model, trainer
    ports/                # ClockPort (injectable time)
    demo.py               # run it and watch the being drift
  tests/                  # behavior-driven tests
  requirements-train.txt  # training-only deps (torch/numpy), kept off the lean image
docker-compose.yml        # engine + postgres + ml-trainer (profile: training)
engine/Dockerfile
docs/
  BRIEF.md                # full target architecture
  design_boundary.md      # the adults-only / abstract-harm boundary
  v0_execution_plan.md    # how v0 is delivered (waves, orchestration, tickets)
  adr/                    # architecture decision records
```

## Run it

```bash
make setup          # create engine/.venv and install deps (once)
make test           # run the behavior suite
make demo           # watch the being drift (make demo TICKS=600)
make run            # serve the API on http://localhost:8000  (GET /state, WS /ws)
make train          # train the outcome predictor -> models/outcome_predictor.pt
                    #   (installs torch on first run — heavy, minutes)

# or the full stack in containers:
make up             # docker compose up --build  (engine :8000, postgres :5432)
make down           # stop + remove volumes
```

The API is authenticated (always-on JWT — [ADR 0005](docs/adr/0005-api-authentication.md)).
Copy `.env.example` to `.env` and set a `JWT_SECRET`, then mint a service token
and call the API with it:

```bash
cp .env.example .env                       # then edit JWT_SECRET
export $(grep -v '^#' .env | xargs)        # load JWT_SECRET etc. into the shell
make run &                                  # serve on :8000

curl -s localhost:8000/health              # public → {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' \
  localhost:8000/state                     # no token → 401
TOKEN=$(make -s token)                      # mint a token with the same secret
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/state                     # → 200 + the being's snapshot
```

The WebSocket `/ws` takes the token as `?token=<jwt>` or the `Authorization`
header. Set `AUTH_REQUIRED=false` only for throwaway local dev (a documented
dev-only no-op — there is no localhost bypass).

No `make`? The equivalent is `python3 -m venv engine/.venv`, install
`engine/requirements.txt` into it, then run modules from `engine/` with
`PYTHONPATH=.` (e.g. `python -m app.demo 300`, `python -m pytest`,
`python -m app.auth_token`).

## Run with Postgres

Persistence uses Postgres (V0-7, [ADR 0007](docs/adr/0007-persistence-repository-port-and-schema-seam.md)).
Start the database on its own, point `DATABASE_URL` at it, and create the schema:

```bash
make db-up                                  # start Postgres, wait until it accepts connections
export DATABASE_URL=postgresql+psycopg://sim:sim@localhost:5432/being_sim
make migrate                                # create the v0 tables (retries until the DB is ready)
```

`make db-up` runs `docker compose up -d --wait postgres`, so it returns only once
the container reports healthy. `make migrate` (and any connect through
`app.db.session`) also **waits for the database to accept connections** with
bounded backoff, so running `make migrate` immediately after `docker compose up`
no longer races Postgres' first-boot init — it retries until the DB is ready and
otherwise **fails with a clear error after a configurable timeout**.

Tune the wait with these optional environment variables (deploy/ops config, same
category as `DATABASE_URL`; defaults in parentheses):

| Variable | Default | Meaning |
|---|---|---|
| `DB_CONNECT_TIMEOUT_SECONDS` | `30` | total budget before giving up with a clear error |
| `DB_CONNECT_BACKOFF_SECONDS` | `0.5` | initial wait between attempts |
| `DB_CONNECT_BACKOFF_MAX_SECONDS` | `5` | cap on the (geometrically growing) wait |
| `DB_CONNECT_BACKOFF_MULTIPLIER` | `2` | growth factor applied to the wait each retry |

With `DATABASE_URL` reachable, the persistence integration tests (the `[postgres]`
variants marked `integration`) run the real round-trip; with it unset or
unreachable they **skip cleanly** with a reason — the database is never faked:

```bash
DATABASE_URL=postgresql+psycopg://sim:sim@localhost:5432/being_sim make test
```

## Roadmap (vertical slices)

Delivered in parallel **waves** (see
[`docs/v0_execution_plan.md`](docs/v0_execution_plan.md)), so completion is not
strictly top-to-bottom.

1. **Minimal being state** — needs drift from config, emotion derived. ✅
2. **Objects + a room; the being perceives what is near.** ✅
3. Environmental conditions (light/dark, sound, temperature) that move
   contextual needs like safety — this is what makes `scared`/fear fire.
4. **Actions + a simple rule/utility decision (generic object interactions);
   a safety *invariant floor* blocks only simulation-breaking actions, while
   recoverable-but-harmful ones (touching something hot) are allowed and land
   felt consequences the being learns from** ([ADR 0014](docs/adr/0014-invariant-floor-and-outcome-state-effects.md)). ✅
5. **FastAPI engine: REST `/state` + WebSocket tick stream; `docker-compose.yml`
   (engine + postgres).** ✅
6. Postgres persistence: interaction events + training examples.
7. PyTorch outcome predictor + `ml-trainer` sidecar, running in shadow mode.
   *(Trainer landed: a multi-label net trains via `ml-trainer` / `make train` on
   the real stored `training_examples` when a database holds them, and on a
   config-derived synthetic seed set otherwise; each run records a `model_runs`
   row. The feature/label encoding contract is pinned in
   [ADR 0008](docs/adr/0008-outcome-predictor-and-feature-encoding.md).
   Shadow-mode inference + prediction/actual comparison come next.)*
8. **PixiJS renderer showing the being's current emotion/needs; sends a
   `player_command` back.** ✅ *(the wire contract is pinned in
   [ADR 0004](docs/adr/0004-render-state-contract.md); how the renderer
   authenticates in [ADR 0010](docs/adr/0010-renderer-authentication.md).
   `pose`/`action` render once V0-4 lands.)*

Each slice is test-first and ends in something observable. See
[`docs/adr/`](docs/adr/) for the decisions behind the structure and
[`CLAUDE.md`](CLAUDE.md) for how work is done here.

## How we work (governance index)

The rules and guardrails that govern how work happens here live in
[`CLAUDE.md`](CLAUDE.md); this table is their index. **Any new rule, hook,
guardrail, or sub-agent convention must add or update a row here in the same
change** (enforced by convention — see CLAUDE.md → Documentation).

| What we have | Why | What it does |
|---|---|---|
| Vertical slices | Ship observable value; avoid big-bang | Every change ends in something a user can see/do; the one-sentence outcome is stated first |
| TDD, red-first | Prove behavior, not methods | Write behavior tests, watch them fail, then implement to green |
| Deep modules | Simple interfaces, testable seams | Lots of behavior behind one small public class; no port until something varies across it |
| Deep-module review gate | Catch design drift early | `/legacy-deep-module-review` runs after each slice, before it is called done |
| Domain-model gate | Keep the ubiquitous language current | After each slice, update root `CONTEXT.md` (via the `domain-modeling` skill) with new/changed terms; an ADR only per its 3-part test |
| Config-driven tuning | Retune without touching code | Rates/thresholds/vocab live in `config/*.yaml`; only `ConfigService` reads them |
| ADRs | Durable decision record | One `docs/adr/NNNN` per significant decision; never rewritten, only superseded |
| No commits on `main` (hook) | Keep `main` reviewed and clean | `.githooks/pre-commit` rejects commits on `main`; all work is a worktree branch → PR |
| API auth (always-on JWT) | Close the state surface by default | Every protected route runs `require_auth` (HS256, sig+exp+iss+aud); `/health` public; always in the code path, gated only by `AUTH_REQUIRED` — no loopback bypass ([ADR 0005](docs/adr/0005-api-authentication.md)) |
| Secrets never committed (env + scan) | Keep secrets out of git | `.env`/`*.pem`/`*.key` gitignored (only `.env.example` committed); the `pre-commit` hook blocks a staged `.env`, key file, or PEM/AWS-key literal |
| Worktrees + wave PRs | Parallel work without clobbering | Each slice runs in its own worktree/branch; a wave rolls up into a single PR |
| Orchestrator vs sub-agents | Clear ownership | Orchestrator owns git + the board; sub-agents own code, commit in their worktree, and report |
| Sub-agent → workflow escalation | Scale to large slices | A sub-agent may spawn a workflow/helper agents, staying within its worktree contract |
| Self-diagnosing / self-healing | Keep the open PR pristine | Defects become bug tickets → `hotfix/<ticket>` → verify → merge back; nothing merges red |
| Closing a wave | Clean, verified finish | After the PR merges: pull, verify, self-heal if needed, delete branches/worktrees, cards → done, report |
| Trello board guardrails | Safe, auditable task flow | Official MCP only; pull from `Ready for Agent`; claim before work; gated one-step moves; a human does Done |
| New-work intake gate | No code before a card | Any new ask — including a direct in-session director request — becomes a board card in our pattern first; the orchestrator mints it and moves it `Ready for Agent` → `in progress` → `in review` → `done`, then normal TDD/PR/gates apply (a procedure, not a hook) |
| Design boundary | Study simulated psychology honestly | Harm is abstract internal state (pain/fear/stress/trust deltas) and **may be lasting** (no forced recovery); the being can be harmed and learn from it; adults-only; the one hard line is never real-world-harm instruction ([ADR 0013](docs/adr/0013-reframed-design-boundary.md)) |
| Dev env (`make`) | Reproducible setup and tests | `make setup/test/demo/run/train/up` — one gitignored venv, identical for everyone; `train` adds the training-only deps |
| This governance index | Keep the docs honest | New rules/hooks/conventions update this table in the same change |
