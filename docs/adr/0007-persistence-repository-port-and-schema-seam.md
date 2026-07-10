# 0007 — Persistence: repository-port and schema seam

## Status

Accepted

## Date

2026-07-10

## Context

The engine core is pure Python behind `Simulation` (ADR 0001). BRIEF §8 assigns
Postgres the simulation's *dynamic and learned* data — interaction events,
training examples, prediction records, model runs — and BRIEF §15 lists the six
v0 tables. The learning loop (V0-4 events, V0-8 training) will need somewhere to
write and read that data.

Two forces shape this slice:

- **The seam must exist before the data does.** No `InteractionEvent` is produced
  yet (that is V0-4). If we wait until events exist to design persistence, the
  event slice has to invent the storage abstraction under time pressure and the
  tick loop couples straight to a database. Landing the seam now, exercised
  through the one aggregate that already exists (the being), keeps the later
  slices small.
- **Tests must not need a database.** The behavior suite runs everywhere with no
  services up (and, in this environment, host→container port forwarding is
  broken, so `localhost:5432` is unreachable from the host). Persistence
  behavior must be testable against a fast in-process implementation, with the
  real database verified separately and skipped when absent — never faked.

## Decision

Introduce a persistence seam with a port and two adapters, plus the schema and
connection it needs.

- **Repository port** — `app/ports/repositories.py` defines `BeingRepository`
  (`save`/`get`) as a `Protocol`. This is a genuine seam under the deep-module
  rule: two implementations vary across it. Only the being aggregate exists
  today, so only its port is defined; `InteractionEvent`/`TrainingExample` ports
  are added by the slices that produce them (V0-4+), not speculatively now.

- **Two adapters** — `app/repositories.py` holds both implementations behind the
  port: `InMemoryBeingRepository` (a dict-backed fake with real store behavior —
  it copies records in and out so callers can never alias the store; this is the
  seam the suite drives, no database required) and `PostgresBeingRepository`
  (maps the port onto the ORM over a live `Session`, upserting with `merge`).

- **Schema** — `app/db/models.py` declares the six v0 tables from BRIEF §15
  (`beings`, `objects`, `interaction_events`, `training_examples`,
  `prediction_records`, `model_runs`) as SQLAlchemy models. The ORM is an
  implementation detail of the Postgres adapter, not a public interface.

- **Connection** — `app/db/session.py` builds the engine and session factory
  from `DATABASE_URL` (dialect `postgresql+psycopg`). The URL is deploy/secret
  config like `JWT_SECRET` (ADR 0005): it comes from the environment only,
  refuses to default to a guessed server, and is never committed.

- **Migration** — `app/db/migrate.py` materializes the schema via
  `Base.metadata.create_all` (`python -m app.db.migrate`, `make migrate`). v0 has
  no schema *evolution* yet, so — following "do not introduce a tool until
  something varies across it" — a migration framework (Alembic) is deferred until
  the schema starts changing over time. When it does, `migrate.py` is where it
  lands, so callers keep saying `create_all(engine)`.

`SQLAlchemy` and `psycopg[binary]` move into the active engine requirements.

## Consequences

- The engine has persistence it can build on: V0-4 adds an `InteractionEvent`
  port and adapter alongside these, and wires event-writing into the flow — this
  slice deliberately does **not** touch the tick loop, since no events exist yet.
- Persistence behavior is tested through the port against the in-memory fake and
  runs everywhere with no services. A live-Postgres round-trip runs the same
  contract when a database is reachable and is **skipped with a clear reason**
  (marked `integration`) when it is not — it is never faked with a stand-in.
- `DATABASE_URL` is the single source of the connection string, from the
  environment only; no credentials live in the repo (`.env.example` carries a
  local-dev placeholder, `.env` stays untracked).
- The ORM stays hidden behind `BeingRepository`. Swapping the store, or moving to
  a different SQL flavour, is confined to `app/db/` and `PostgresBeingRepository`;
  callers and tests see only the port.
- `create_all` is the v0 migration. Once two schema versions must coexist, that
  is the trigger to adopt Alembic — a future ADR, not a silent change here.
