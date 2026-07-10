# 0012 — Interaction-event and training-example repository ports

## Status

Accepted

## Date

2026-07-10

## Context

ADR 0007 landed the persistence seam (a repository port + Postgres/in-memory
adapters) and the six-table schema, but deliberately defined only the
`BeingRepository` — "each [new aggregate] gets its own port here, added when it
is actually needed rather than speculatively." V0-4 then made the being *act*:
each tick can produce one `InteractionEvent` (`app.domain.interaction_event`),
held only in an in-memory log (`Simulation.interactions()`).

Those events are the lasting facts everything learned is derived from (BRIEF §9),
and ADR 0008 pinned how an interaction is encoded into a model-ready row (the
`FeatureEncoder` feature/label contract). What was missing is the wiring: as the
sim runs, write each event to Postgres and derive a `TrainingExample` from it, so
the learning loop has real stored data (the follow-up ADR 0008 named). This slice
(V0-7b) adds that, which raises two genuinely new interface decisions — the two
new ports and *how* an example is derived at write time — hence this ADR extends
0007 rather than silently reusing it.

## Decision

### Two append-only repository ports

`app/ports/repositories.py` gains `InteractionEventRepository` and
`TrainingExampleRepository`. Unlike `BeingRepository` (which upserts a mutable
snapshot by id via `save`/`get`), events and examples are **append-only facts**,
so their ports are `add(...)` + `all()`. Each has the two adapters the seam
requires (`app/repositories.py`): an in-memory list-backed fake the behavior
suite drives, and a Postgres adapter over a SQLAlchemy `Session`. Callers depend
on the port; the ORM stays hidden (the Postgres adapter is the only code that
imports `app.db.models`).

### Event identity is `(being, tick)`

The domain `InteractionEvent` exposes a computed `event_id` property,
`f"{being_id}:{tick}"`. The being takes at most one action per tick, so this
names an event uniquely, is deterministic (re-running ticks upserts rather than
duplicating, via `merge`), and gives the derived training example a stable
foreign key back to its event. No new stored field or constructor argument — the
identity is derived from the natural key.

### The training example is derived at write time, through the encoder

When a training-example port is injected, `Simulation` builds the
`FeatureEncoder` from config (ADR 0008) and, per event, encodes an
`Example(properties = the object's *true* properties, action = the affordance
taken, context, outcomes = the observed outcomes)` into a domain `TrainingExample`
(`event_id` + multi-hot `input_features` + multi-hot `output_labels`). Using the
true properties + observed outcomes keeps each row self-consistent and matches
the trainer's synthetic seed set convention (ADR 0008), so stored and synthetic
examples are encoded identically.

Two consequences of the encode contract shape the derivation:

- **The action slot is the affordance, not the action name.** The encoder's
  action vocabulary is the object *affordances* (`look`, `touch`, …); the being's
  actions are named separately (`observe` uses affordance `look`). The derivation
  encodes `policy.affordance`, so `observe` maps to the `look` slot.
- **Free actions yield no training example.** `approach`/`withdraw` carry no
  affordance — they are not object→outcome interactions the predictor models — so
  they are still recorded as interaction events but produce no example. (Live run
  of the shipped config over 80 ticks: 80 events, 52 examples.)

### The write stays behind an injected, defaulted seam

`Simulation.__init__` takes optional `event_repo` and `training_repo`, both
defaulting to `None` (no-op). The pure model/decision tests construct a
`Simulation` with no store and are unaffected; the behavior suite injects the
in-memory fakes; production injects the Postgres adapters. Nothing below the seam
imports SQLAlchemy. The encoder is built only when a training port is present, so
minimal configs without the ML vocabulary keep working.

## Consequences

- **The learning loop has real data.** As the sim runs, interaction events and
  derived training examples land in Postgres; a query shows both. This is the
  data source ADR 0008's trainer named as a follow-up.
- **Behavior is tested through the ports against in-memory fakes** (no database),
  and a live Postgres round-trip runs the *same* ports when `DATABASE_URL` is
  reachable and skips cleanly otherwise (`integration`, never faked) — the ADR
  0007 discipline, now covering events and examples.
- **The event/example write is optional and localized.** Two constructor kwargs
  plus one private `Simulation._record` step; existing call sites are unchanged.
- **Follow-ups (unchanged owners):** wire `train_outcome_model.load_training_examples`
  to read stored `training_examples` (currently returns `None`, ADR 0008); record
  a `model_runs` row per training run; V0-9 shadow-mode inference +
  prediction/actual comparison. A `surface`/context dimension in the room would
  fill the currently-empty context slots — a future slice, not this one.
- **Design boundary.** Outcome labels such as `causes_pain`/`scary` are abstract
  values the being learns to anticipate so it can avoid harm; persisting them
  changes nothing about that (see `docs/design_boundary.md`, ADR 0008).
