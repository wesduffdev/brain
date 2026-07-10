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
(each with a confidence); and it is exposed over an **HTTP + WebSocket API**,
runnable as a **Docker Compose stack** (engine + postgres). No database code,
ML, actions, or renderer yet — those are later slices.

```
config/
  tick_rates.yaml         # need drift + bands (the time-tuning surface)
  emotions.yaml           # how needs derive one dominant emotion (fear included)
  rooms.yaml              # the room and the objects it contains
  object_properties.yaml  # object property/affordance vocabulary + objects
engine/
  app/
    config_service.py     # YAML/dict -> typed policies (the only config-aware code)
    simulation.py         # the public interface: tick(), state()
    main.py               # FastAPI: GET /state + WebSocket /ws tick stream
    domain/               # BeingState, Room, ObjectEntity, emotion vocabulary
    services/             # Tick, Need, Emotion, Perception services
    ports/                # ClockPort (injectable time)
    demo.py               # run it and watch the being drift
  tests/                  # behavior-driven tests
docker-compose.yml        # engine + postgres
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

# or the full stack in containers:
make up             # docker compose up --build  (engine :8000, postgres :5432)
make down           # stop + remove volumes
```

No `make`? The equivalent is `python3 -m venv engine/.venv`, install
`engine/requirements.txt` into it, then run modules from `engine/` with
`PYTHONPATH=.` (e.g. `python -m app.demo 300`, `python -m pytest`).

## Roadmap (vertical slices)

Delivered in parallel **waves** (see
[`docs/v0_execution_plan.md`](docs/v0_execution_plan.md)), so completion is not
strictly top-to-bottom.

1. **Minimal being state** — needs drift from config, emotion derived. ✅
2. **Objects + a room; the being perceives what is near.** ✅
3. Environmental conditions (light/dark, sound, temperature) that move
   contextual needs like safety — this is what makes `scared`/fear fire.
4. Actions + a simple rule/utility decision (generic object interactions).
5. **FastAPI engine: REST `/state` + WebSocket tick stream; `docker-compose.yml`
   (engine + postgres).** ✅
6. Postgres persistence: interaction events + training examples.
7. PyTorch outcome predictor + `ml-trainer` sidecar, running in shadow mode.
8. PixiJS renderer showing the being's current emotion/action. *(the wire
   contract is pinned in [ADR 0004](docs/adr/0004-render-state-contract.md).)*

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
| Config-driven tuning | Retune without touching code | Rates/thresholds/vocab live in `config/*.yaml`; only `ConfigService` reads them |
| ADRs | Durable decision record | One `docs/adr/NNNN` per significant decision; never rewritten, only superseded |
| No commits on `main` (hook) | Keep `main` reviewed and clean | `.githooks/pre-commit` rejects commits on `main`; all work is a worktree branch → PR |
| Worktrees + wave PRs | Parallel work without clobbering | Each slice runs in its own worktree/branch; a wave rolls up into a single PR |
| Orchestrator vs sub-agents | Clear ownership | Orchestrator owns git + the board; sub-agents own code, commit in their worktree, and report |
| Sub-agent → workflow escalation | Scale to large slices | A sub-agent may spawn a workflow/helper agents, staying within its worktree contract |
| Self-diagnosing / self-healing | Keep the open PR pristine | Defects become bug tickets → `hotfix/<ticket>` → verify → merge back; nothing merges red |
| Closing a wave | Clean, verified finish | After the PR merges: pull, verify, self-heal if needed, delete branches/worktrees, cards → done, report |
| Trello board guardrails | Safe, auditable task flow | Official MCP only; pull from `Ready for Agent`; claim before work; gated one-step moves; a human does Done |
| Design boundary | Serious but safe simulation | Harm stays abstract (state deltas + recovery paths); adults-only; never real-world-harm instruction |
| Dev env (`make`) | Reproducible setup and tests | `make setup/test/demo/run/up` — one gitignored venv, identical for everyone |
| This governance index | Keep the docs honest | New rules/hooks/conventions update this table in the same change |
