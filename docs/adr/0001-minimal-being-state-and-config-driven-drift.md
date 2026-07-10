# 0001 — Minimal being state: config-driven need drift and derived emotion

## Status

Accepted

## Date

2026-07-10

## Context

The project (see `docs/BRIEF.md`) targets a multi-service, ML-backed
simulation: FastAPI + WebSocket transport, Postgres, a PyTorch outcome
predictor in shadow mode, and a PixiJS renderer, all on Docker Compose. Trying
to stand all of that up at once is a big-bang with nothing observable until the
end.

We also deliberately moved away from the earlier baby-centric framing. The
being is human-like in psychology but is not a baby, has no age or life-stage,
and there is no caregiver concept. The first thing built must set that tone and
avoid smuggling in baby/care-flavored mechanics (e.g. "seek caregiver").

We need a first slice that is minimal, observable, fully tested, and that
establishes the load-bearing design idea: **fine-tuning lives in config, not in
code**.

## Decision

The first slice is the being's minimal internal state only:

- **Needs** drift over ticks. Every rate, band, and starting value comes from
  `config/tick_rates.yaml`; `direction: contextual` means no autonomous drift
  (the world will move it in a later slice). Tick 0 is the birth state and
  never drifts.
- **One dominant emotion** is derived from needs by an ordered rule table in
  `config/emotions.yaml` (first match wins). `scared` (fear) is wired now via a
  low-`safety` rule, even though nothing lowers safety until the environment
  slice — so fear is ready, not retrofitted.
- The public interface is `Simulation` (`tick()`, `state()`); a `demo.py` makes
  it observable. `ConfigService` is the only config-aware code and hands
  services typed policies (`NeedTickPolicy`, `EmotionRule`).

Explicitly **out of this slice** (each its own later slice): transport
(FastAPI/WebSocket), persistence (Postgres), the neural net + trainer, the
renderer, objects/rooms/environment, and **actions/decisions** — including any
caregiver-directed action.

No `ClockPort`/`ConfigProvider` protocol is introduced yet: nothing varies
across those boundaries in this slice, and the deep-module rule is not to add a
seam until something does. `TickService` is the tick owner (tests advance it
directly).

## Consequences

- Retuning temperament (drift rates, emotion thresholds) is a `config/*.yaml`
  edit with no code change — proven by a test.
- The engine core is pure Python with only PyYAML at the edge, so it imports
  and runs (and is tested) without torch, FastAPI, a database, or Docker. Heavy
  dependencies enter only in the slice that needs them.
- Emotions that require an external event (happy, excited, comforted) are not
  reachable yet; they arrive with the interaction slice. Documented in
  `engine/app/domain/emotion.py`.
- When the real tick loop lands (FastAPI slice), we will reassess whether a
  clock port is warranted; until then, adding one would be premature.
