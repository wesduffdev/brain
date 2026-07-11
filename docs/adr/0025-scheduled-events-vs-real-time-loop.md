# 0025 — Scheduled events vs. the real-time tick loop

## Status

Accepted

## Date

2026-07-11

## Context

The engine is a **single-writer, synchronous, in-process tick loop** with no
messaging (`event_instinct_execution_plan.md` §1.1). `Simulation.tick()`
(`engine/app/simulation.py`) runs a fixed sequence every step — advance the clock,
drift needs, push contextual needs from the room, re-derive emotion, then `_act()`
(perceive → curiosity/surprise → decide → apply outcome → re-derive emotion →
build + persist the `InteractionEvent` → cooldown → learn) — and returns
`state()`. Every service is *polled by the tick*, whether or not anything relevant
to it actually happened.

The Event Backbone + Instinct program (`docs/queue.md` Workstream C / Epic 3, cut
as ticket **TICK-INV**) needs to introduce an event bus (ADR 0024) and a new
instinct reaction path *without* rewriting the whole loop at once, and without
changing any observable behavior in the process. That requires a **shared rule**
for deciding, per responsibility, whether it should be driven by a **domain event**
(something happened), left on a **time schedule** (only the clock moved), or kept
in a **local real-time loop** (its correctness *is* the clock).

`docs/tick_to_event_inventory.md` is the companion to this ADR: it classifies all
23 tick-driven responsibilities against the vocabulary below. This ADR records the
*decision rule* and its consequences; the inventory records its *application*.
**This slice writes no production code and changes no behavior** — it is the
reference that lets later slices migrate safely.

## Decision

**Time-caused change emits scheduled events rather than every service polling the
tick; genuinely real-time work keeps a local loop and emits summarized events; a
change caused by something that happened is a domain event.** Concretely, every
tick-driven responsibility is classified into exactly one of five kinds, and that
classification governs how (and whether) it migrates onto the ADR 0024 backbone:

1. **Event-driven** — caused by *something that happened* (a perception, an action,
   its felt consequence). A producer emits a versioned domain event; consumers
   react. This is the migration target for the program's first path.
2. **Scheduled-event** — caused *only by the passage of time* on a fixed cadence
   (`every_ticks`). Eligible to be driven by a scheduler/timer emitting a summarized
   event, but **not migrated this program** — see consequences.
3. **Keep-loop (real-time)** — work whose correctness *is* the clock (the time
   source itself; action duration/cooldown timing). It **keeps a local loop** and
   emits *summarized* events (e.g. an action started/finished) rather than being
   decomposed step-by-step onto the bus.
4. **Renderer-only** — a read-model/projection assembled for the render-state frame
   (ADR 0004); it changes no domain state and migrates as a render event/frame.
5. **Training/analytics** — a learning or audit side effect of an interaction,
   "never read back into this tick's decision"; becomes an *asynchronous consumer*
   of the interaction event, off the hot path.

**Migration is narrow and behavior-preserving.** The program migrates only the
**perception → instinct → render** path first (perception becomes a
`being.perception.events` producer once `WORLD-MOTION` adds kinematics; instinct is
a *new* downstream consumer in shadow mode; render consumes reaction hints).
**Need-drift and emotion re-derivation are explicitly classified Keep-as-scheduled
and are NOT migrated this program.** The interaction event and its persistence
move onto the backbone via a transactional outbox (ADR 0028); the training/analytics
side effects become async consumers opportunistically, later.

The rule is applied in `docs/tick_to_event_inventory.md`; the tally is 5
Event-driven, 4 Scheduled-event (kept), 2 Keep-loop, 3 Renderer-only, 9
Training/analytics.

## Consequences

- **No behavior change in this slice.** This is a classification and a decision
  rule only — no engine or config code changes with it. The existing synchronous
  tick loop keeps running exactly as it does today; the suite is unaffected.
- **Later migration tickets have a stable contract.** Each migration slice can cite
  the inventory row and this rule to justify *why* a responsibility becomes an
  event, stays scheduled, or keeps its loop — so migrations are reviewable and
  reversible one path at a time, not a big-bang rewrite.
- **Emotion and need-drift stay time-driven — deliberately.** They are cheap,
  deterministic, and already correct on the tick; converting them to scheduled
  events would add machinery with no behavior gain. Emotion is a *pure projection
  of needs* (a future derive-on-read candidate), but that is out of scope here. This
  keeps the program's blast radius to the perception→instinct→render path.
- **Real-time timing is not decomposed onto the bus.** The clock heartbeat and
  action duration/cooldown timing keep a local loop and publish *summarized* events;
  putting per-tick timing on the bus would add latency and noise with no gain (it
  also answers Open Question §8.5 on instinct latency by keeping the hot path local).
- **The bus never becomes a second source of truth for time.** Scheduled changes
  that stay on the tick are not also published as time events, so there is no
  ambiguity about who advances the clock (the loop does; ADR 0024's bus carries
  *what happened*, not *time passed*).
- **Cost:** the five-way classification is a judgment call at the margins (e.g. the
  environmental push is scheduled but its trigger, `change_environment`, is already
  event-shaped). The inventory records the reasoning per row so the call is
  auditable rather than implicit.

Supersedes nothing. Depends on ADR 0024 (event backbone) for the mechanism;
constrains ADR 0028 (transactional outbox) and the instinct-path slices
(`WORLD-MOTION`, `INS-RT`, `INS-ACT`, `RENDER-RX`) to migrate only what this rule
classifies as event-driven. Companion document: `docs/tick_to_event_inventory.md`.
