# 0024 — Event backbone: the DomainEvent envelope and EventBus port

## Status

Accepted

## Date

2026-07-11

## Context

The repo is a single-writer, synchronous, in-process tick loop with **no
messaging of any kind** (`docs/event_instinct_execution_plan.md` §1). The
event-instinct augmentation needs the being's world to be driven by **domain
events** — versioned facts one service produces and others react to
(`being.perception.object_approached`, `being.instinct.prediction_made`, and the
rest of the `being.*` catalogue described in `docs/queue.md` §"Event Schema
Requirements"). The chosen runtime broker is Kafka (EVT-KAFKA).

Two standing repo rules shape *how* that backbone lands:

1. **The suite must stay hermetic.** `pytest` may never require a live broker
   (the same rule that keeps the fast suite independent of Postgres, ADR 0007).
2. **A seam needs a real second implementation, not speculation.** We introduce a
   port only when something actually varies across it.

Both are satisfied here: the events flow needs an in-process test implementation
*and* a Kafka runtime implementation, so the seam is justified by two genuine
impls from day one — mirroring how `PredictorPort` (ADR 0011) hides torch and the
repository ports (ADR 0007) hide SQLAlchemy behind an in-memory fake the suite
drives.

## Decision

**1. A self-validating `DomainEvent` envelope (`engine/app/domain/event.py`).**
A frozen dataclass carrying the queue's base-envelope fields: `event_id`,
`event_type`, `event_version`, `occurred_at`, `produced_at`, `source_service`,
`being_id`, `correlation_id`, `causation_id`, `payload`. It **validates itself
loudly** on construction — a non-empty type, a version `>= 1`, timezone-aware
timestamps, a mapping payload, an optional-but-non-empty causation id — raising
`ValueError` rather than carrying a malformed envelope onward. `from_snapshot`
re-validates an event rebuilt off the wire the same way, so a consumer can never
half-build a bad event. Producers assemble events only through `create` (a root
event that heads its own correlation chain: `correlation_id == event_id`,
`causation_id is None`) and `prior.causes(...)` (a downstream event inheriting
`correlation_id` and recording the prior event's id as its `causation_id`), so an
`A -> B -> C` chain is traceable by construction. `snapshot()`/`from_snapshot()`
round-trip the envelope through stable camelCase, JSON-ready keys — the form the
Kafka adapter will serialize.

**2. An `EventPublisher` / `EventConsumer` port pair
(`engine/app/ports/events.py`).** Two `Protocol` ports — `publish(topic, event)`
and `subscribe(topic, handler)` — are the **only** surface the sim binds to.
There is deliberately **no Kafka (or any broker) symbol at or above this seam**;
the broker is an adapter below it.

**3. An `InMemoryEventBus` as the default, broker-free implementation
(`engine/app/adapters/in_memory_event_bus.py`).** It implements both ports in one
in-process object: `subscribe` registers a handler per topic; `publish` delivers
synchronously to every handler on that topic (snapshotting the handler list so a
handler may itself publish — an in-process `A -> B` chain — without mutating the
sequence mid-dispatch). It carries only validated envelopes: publishing a
non-`DomainEvent` is refused loudly. This is the implementation **the whole suite
runs on**, so `pytest` needs no broker.

**4. Kafka is the runtime implementation, to follow (EVT-KAFKA).** The same two
ports get a `KafkaEventBus` adapter; the broker URL comes from env and topic
names from config. Nothing above the port changes when it is swapped in.

Naming is `being.*` throughout (`being.perception.events`,
`being.instinct.predictions`), never `npc.*`/`shell_001` — matching `CONTEXT.md`.

## Consequences

- Domain code can publish and subscribe to versioned events today, entirely in
  process; a `being.*` event flows producer → bus → consumer, and a two-hop
  causal chain is preserved, in tests — with **no broker required to run
  `pytest`**.
- A malformed envelope cannot enter the flow: it is rejected at construction and
  again at `from_snapshot`, so every event on the bus is well-formed.
- The seam is honest, not speculative — the in-memory fake is a real second
  implementation now, and Kafka is the second runtime implementation next
  (EVT-KAFKA), exactly the shadow-mode/port precedent set by ADR 0011.
- This slice is envelope + port + fake only: no simulation wiring, no persistence
  (`EVT-PERSIST`/ADR 0028), no Kafka (`EVT-KAFKA`). Those build on this seam.
- Delivery here is synchronous and in-order per topic; at-least-once semantics,
  idempotency (dedupe on `event_id`), and DLQ-on-failure are Kafka-adapter
  concerns and are specified with EVT-KAFKA, not baked into the port.

Supersedes nothing. Relates to ADR 0011 (shadow-mode + predictor-port precedent
for a fake-default, real-runtime seam) and ADR 0007 (the hermetic-suite /
in-memory-fake persistence seam this mirrors). Extended by EVT-KAFKA (Kafka
runtime adapter) and EVT-PERSIST/ADR 0028 (transactional outbox for atomic
publish).
