# jarvis — situated-being ML simulation

A simulated **being** — human-like in psychology (needs, emotions, curiosity,
memory, learned expectations), but not a baby, not tied to an age or
life-stage, and not a literal person. The long-term goal is a hybrid brain:
authored rules + a small neural network for narrow prediction, rendered in 2D,
running across Docker services. The near-term goal is to learn ML by building
that loop one honest slice at a time.

The full target architecture lives in [`docs/BRIEF.md`](docs/BRIEF.md) —
Postgres, PyTorch, FastAPI/WebSocket, PixiJS, Docker Compose. This repo builds
toward it in vertical slices; see the roadmap below for what is actually here
today.

## What exists today (slice 1 — minimal being state)

A being whose **needs drift over ticks, entirely driven by config**, and whose
**dominant emotion is derived from those needs**. No transport, database, ML,
renderer, or actions yet — those are later slices.

```
config/
  tick_rates.yaml     # the tuning surface for time: need drift + bands
  emotions.yaml       # how needs derive one dominant emotion (fear included)
engine/
  app/
    config_service.py # YAML/dict -> typed policies (the only config-aware code)
    simulation.py     # the public interface: tick(), state()
    domain/           # BeingState, emotion vocabulary
    services/         # TickService, NeedService, EmotionService
    demo.py           # run it and watch the being drift
  tests/              # behavior-driven tests
docs/
  design_boundary.md  # the adults-only / abstract-harm boundary
  adr/                # architecture decision records
```

## Run it

```bash
cd engine
pip install -r requirements.txt          # PyYAML + pytest

# watch a being drift (needs climb; emotion turns calm -> curious ~tick 225)
PYTHONPATH=. python -m app.demo 300

# run the behavior tests
python -m pytest
```

## Roadmap (vertical slices, in order)

1. **Minimal being state** — needs drift from config, emotion derived. ✅ *done*
2. Objects + a room; the being perceives what is near.
3. Environmental conditions (light/dark, sound, temperature) that move
   contextual needs like safety — this is what makes `scared`/fear fire.
4. Actions + a simple rule/utility decision (generic object interactions; no
   caregiver-directed actions).
5. FastAPI engine: REST `/state` + a WebSocket tick stream. Reintroduce
   `docker-compose.yml` (engine + postgres).
6. Postgres persistence: interaction events + training examples.
7. PyTorch outcome predictor + `ml-trainer` sidecar, running in shadow mode.
8. PixiJS renderer showing the being's current emotion/action.

Each slice is test-first and ends in something observable. See
[`docs/adr/`](docs/adr/) for the decisions behind the structure and
[`CLAUDE.md`](CLAUDE.md) for how work is done here.
