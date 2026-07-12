# 0042 — Persist reaction events (`EmotionBiasApplied` / `ActionInterrupted`) via the transactional outbox

## Status

Accepted

Supersedes the "transient, published straight through" decision in
[ADR 0029](0029-instinct-reaction-emotion-and-action-interrupt.md) for the two
reaction events. Extends [ADR 0028](0028-transactional-outbox.md) (the
outbox/relay/event-log it reuses) and [ADR 0017](0017-unit-of-work-transaction-boundary.md)
(the unit of work). ADR 0029's reaction → emotion/interrupt *behaviour* and the
inviolable safety floor are untouched.

## Date

2026-07-11

## Context

[ADR 0029](0029-instinct-reaction-emotion-and-action-interrupt.md) shipped the
`ReactionResponseService` publishing `EmotionBiasApplied` (state topic) and
`ActionInterrupted` (action topic) **straight through the injected publisher**,
explicitly *"not staged in a persistence unit of work"* — transient runtime
signals for observers/the renderer, like the `ObjectApproached` the
`StimulusService` emits.

But [ADR 0028](0028-transactional-outbox.md) had already settled how every domain
event reaches the bus: a producer **stages an outbox row in the same
`uow.begin()`** as its data (ADR 0017), and a relay publishes it and projects it
into a durable, queryable, **idempotent `event_log`** (keyed on `event_id`). The
reaction events were the one `being.*` producer still emitting directly — so a
triggered interruption or emotion bias:

- never landed on the durable `event_log`: no audit trail, no replay substrate
  for the very moments the being *reacted*; and
- on a broker-backed bus, risked the dual-write anomaly the outbox exists to
  prevent (a publish that succeeds while the tick's data fails, or vice-versa).

This slice (`REACTION-EVENTS-PERSIST`) closes that gap by routing the reaction
events through the same outbox the rest of the backbone already uses.

## Decision

**Stage reaction events into the transactional outbox instead of publishing them
directly; a relay publishes and projects them into the idempotent event log.**

- **`ReactionResponseService` stages, it does not publish.** It no longer holds an
  `EventPublisher`; it holds an `OutboxRepository` and records each reaction event
  as an `OutboxEntry` (topic + the validated, *caused* `DomainEvent`, so the
  reaction's correlation chain is preserved). Staging is a no-op when no outbox is
  wired — the byte-identical default, exactly as `publisher is None` was before.
- **`Simulation` stages inside the tick's unit of work (ADR 0017).** `begin_tick`'s
  `EmotionBiasApplied` and `_act`'s `ActionInterrupted` are each staged inside a
  `with self._uow.begin()` block (a no-op context when no reaction outbox is
  wired). An `ActionInterrupted` precludes the interaction write for that tick, so
  it is its own unit; an `EmotionBiasApplied` rides its own unit at `begin_tick`.
- **A relay publishes and projects, out of band.** After advancing the chain,
  `_drain_reactions` runs `drain_outbox` (ADR 0028): it publishes each staged
  envelope onto the bus (**outside** any DB transaction) and projects it into an
  idempotent `event_log`. The append-only outbox may be re-drained every tick; an
  already-logged event is neither re-published nor re-logged (the log is the
  delivery ledger).
- **The durable projection is observable.** `Simulation.event_log()` returns the
  projected reaction events (envelope snapshots, oldest first) — the durable
  audit surface, alongside `interactions()` / `memories()`.
- **Behaviour is unchanged.** Reactions still surface, bias the derived emotion,
  and interrupt exactly as ADR 0029 specified (shadow / visual / interrupt
  semantics, safety-floor gating). Only *how* the events are emitted changes
  (staged → relayed, vs. direct publish). A tick in which no reaction fires is
  byte-identical.

The in-process `Simulation` reuses the **in-memory** outbox + event log (mirroring
the instinct chain's in-process relay, ADR 0028/EVT-VALID); the Postgres adapters
and the DB-free atomicity proof reuse the exact ADR 0028 seam.

## Consequences

- **Durable audit + replay.** Every triggered `EmotionBiasApplied` /
  `ActionInterrupted` lands in the idempotent `event_log` keyed on `event_id` —
  queryable and replayable, the same substrate ADR 0028 gives every other event.
- **No dual-write.** The reaction event and the tick's data commit together or not
  at all; the broker is reached only by the relay, after commit. Pinned DB-free by
  staging an interaction + an `ActionInterrupted` outbox row in one SQLite unit and
  rolling it back — **both** drop — mirroring `test_transactional_outbox.py`.
- **Idempotent projection.** Draining the append-only reaction outbox every tick
  projects exactly one `event_log` row per `event_id`; a replay re-publishes and
  re-logs nothing (pinned across ticks through `Simulation.event_log()`).
- **Byte-identical default.** No bus wired → no reaction outbox → nothing staged;
  both flags off → no reaction event → `state()` unchanged. The full suite stays
  green.
- **Cost / deferral.** The relay re-scans the reaction outbox against the log each
  tick (fine at single-being scale, per ADR 0028). Wiring a **Postgres** reaction
  outbox that shares the runtime session (so atomicity holds end-to-end in the
  deployed being, not just in the proof) is a follow-on — the same deferral the
  instinct chain's in-process relay carries.
