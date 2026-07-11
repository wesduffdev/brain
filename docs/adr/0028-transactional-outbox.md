# 0028 — Transactional outbox for atomic event publish (+ event log & instinct capture)

## Status

Accepted

## Date

2026-07-11

## Context

The event backbone (ADR 0024) gives the being an `EventPublisher` port and, at
runtime, a Kafka adapter (EVT-KAFKA) below it. But an interaction both **writes
the database** (its `interaction_events` row and the rows derived from it — ADR
0017) **and** must **publish a domain event** so other services react. Those are
two independent systems that can fail independently: publish-then-write can leave
an event on the bus for data that never landed; write-then-publish can commit data
whose event is lost if the broker call fails after the commit. There is no
cross-system transaction to lean on.

The wave plan settled the shape in advance (`docs/event_instinct_execution_plan.md`
§1.2.5): *"Atomic publish = transactional outbox. Kafka+Postgres dual-write is
solved by staging an outbox row in the same `uow.begin()` (ADR 0017 fits this
exactly); a relay publishes to Kafka. Domain code never publishes inside the DB
transaction."*

Two further, related needs land in the same slice (`EVT-PERSIST`): a durable,
queryable **projection** of every published event (the audit + replay substrate),
and **persistence for the instinct layer** (ADR 0026) — its per-stimulus
predictions, the reactions it triggered or suppressed, and the training rows
derived from them — so the fast-reaction learning loop has somewhere to write and
read. All of this is additive schema behind the ADR 0007 repository-port seam, and
must stay testable with **no database and no broker** (the hermetic-suite rule).

## Decision

**Solve the dual-write with a transactional outbox, and add the event-log
projection and instinct-capture tables as additive, append-only repository
ports.**

### Transactional outbox (the load-bearing decision)

- **Stage, don't publish, inside the transaction.** A producer records an
  `OutboxEntry` (topic + validated `DomainEvent`) through a new `OutboxRepository`,
  staged in the **same `uow.begin()`** as the rest of its writes (ADR 0017). The
  outbox row therefore commits atomically with the data it accompanies — an event
  is never queued without its data, and data never lands without its event queued.
  A domain producer **never calls the broker inside its transaction**.
- **A relay publishes and projects, out of band.** `drain_outbox`
  (`app/outbox_relay.py`) reads the outbox, publishes each envelope through the
  `EventPublisher` port (**outside** any DB transaction), then records it in the
  `event_log` through `EventLogRepository`, wrapping only that projection write in
  its own unit of work.
- **The event log is the idempotency ledger.** The `event_log` is keyed on
  `event_id`, so projection is idempotent — a replayed or duplicated envelope
  leaves the log at exactly one row. The relay reads the log to know what is
  already delivered and skips it, so an already-logged event is neither
  re-published nor re-logged. Delivery is thus **at-least-once with an idempotent
  projection**: if the process dies after publishing but before the log write
  commits, the next drain re-publishes and the log still ends at one row. This is
  deliberately simpler than a mutable `published` flag on the outbox — the ports
  stay purely append-only `add()/all()`, and correctness rests on the log's
  natural key rather than a second state machine. (Reclaiming drained outbox rows
  is a retention concern, not a correctness one, and is deferred.)

### Event log & instinct capture (additive schema, ADR 0007 seam)

Five additive tables and their repository ports (in-memory fake + Postgres adapter
each, per ADR 0007), no change to existing tables:

- `event_outbox` / `event_log` — the outbox queue and its durable projection. The
  Postgres adapters flatten a `DomainEvent`'s scalar fields into queryable columns
  and store its timestamps as the ISO-8601 wire form (`DomainEvent.snapshot`), and
  rebuild the envelope on read through `DomainEvent.from_snapshot`, which
  **re-validates it loudly** — the same discipline a Kafka consumer uses off the
  wire, and it sidesteps dialect timezone-coercion differences.
- `instinct_predictions` / `instinct_reactions` / `instinct_training_examples` —
  the instinct layer's facts (ADR 0026). `instinct_training_examples` is derived
  from a prediction plus the observed reaction (`instinct_training_example(...)`),
  the instinct analogue of how a `TrainingExample` derives from an
  `InteractionEvent` (ADR 0008/0012).

**FK discipline.** Neither the event tables nor the instinct tables add DB foreign
keys. An event is a self-contained, replayable *fact*, so `being_id` is a plain
indexed column, not a catalog relationship — coupling the log's separate-unit
projection write to the `beings` table would force a brittle cross-unit insert
ordering without adding integrity the envelope's own `event_id` identity does not
already carry (the same reasoning as `beliefs.object_id` and
`concept_evidence.concept_id`, ADR 0019). The instinct rows' `event_id` is the id
of the perception/approach `DomainEvent` that prompted them (ADR 0024/0027) — which
lives on the event backbone, **not** in `interaction_events` — so it too is a plain
indexed link, not a foreign key (the outcome model's `training_examples.event_id`
FK points at the wrong parent for instinct).

## Consequences

- **No dual-write anomaly.** An interaction's data and its event commit together
  or not at all; the broker is reached only after commit, and never holds a DB
  transaction open. A mid-unit failure drops the event *and* its outbox row —
  pinned DB-free by staging both into an in-memory SQLite unit of work and rolling
  it back (`test_transactional_outbox.py`), and again against live Postgres under
  the `integration` marker.
- **Idempotent, replayable projection.** Draining a committed outbox row publishes
  once and writes exactly one `event_log` row; replaying the same `event_id` keeps
  it at one row. The log is a queryable audit trail and a replay source for
  training.
- **Instinct learning has a substrate.** Predictions, reactions, and derived
  training examples are queryable through append-only ports — what `INS-RT`
  (shadow persistence) and the instinct trainer will read and write.
- **The suite stays hermetic.** Every behavior is tested on the in-memory fakes +
  a recording `EventPublisher` fake, with no broker and no database; the
  live-Postgres round-trip is `integration`-marked and skipped when unreachable,
  never faked.
- **The ports stay the only seam.** Callers depend on `OutboxRepository`,
  `EventLogRepository`, the instinct ports, the `EventPublisher` port, and
  `UnitOfWork` — never on SQLAlchemy or a broker; the ORM never leaks above the
  seam.
- **Cost / deferrals.** Five new tables and one relay function; the relay
  re-scans the outbox against the log each drain (fine at single-being scale —
  the guardrail sizes the backbone for one being). Outbox-row retention/compaction
  and wiring the relay into the live runtime (a Kafka consumer group + DLQ) are
  deferred to EVT-KAFKA / INS-RT.

Extends: **ADR 0017** (unit-of-work transaction boundary — the outbox row is staged
in the caller's unit and the relay owns its own unit).

Relates-to: **ADR 0024** (event backbone: the `DomainEvent` envelope + `EventBus`
port the outbox stages and the relay publishes through); **ADR 0007** (persistence
repository-port + schema seam — the additive tables and ports follow it);
**ADR 0026** (instinct model strategy — the prediction/reaction/training contract
these tables persist).

Supersedes nothing.
