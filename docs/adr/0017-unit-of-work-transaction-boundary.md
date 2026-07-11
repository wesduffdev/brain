# 0017 — Unit-of-work transaction boundary: repositories stage, the caller commits

## Status

Accepted

## Date

2026-07-11

## Context

The Postgres repository adapters (`app/repositories.py`, ADR 0007/0011/0012)
each called `self._session.commit()` inside `add`/`save`. So every write was its
own transaction, and one logical operation was **several** of them. A single
interaction writes three related rows — an `interaction_events` row, the
`training_examples` row derived from it, and (in shadow mode) a
`prediction_records` row, the last two carrying a foreign key up to the first.
Committing per write meant a failure part-way through left **orphan rows**: a
parent event with no example, or an example/prediction whose sibling never
landed. The database could be observed in a state that no single logical step
ever intended. The seed (`bootstrap._seed_parents`) and the trainer's
`model_runs` write had the same self-commit shape.

ADR 0016 gave the runtime seam ownership of *when the session closes* but
explicitly deferred *when its writes commit* to this ticket, noting the general
session/transaction-ownership decision "belongs with it and may supersede the
lifecycle detail recorded here."

The constraint: the decision must hold for **both** persistence implementations
behind the repository port — the in-memory fakes the behavior suite drives with
no database, and the live SQLAlchemy session — without leaking the ORM above the
port or forcing a database into the pure-model tests.

## Decision

**Repositories only stage; the caller owns the transaction.** Every Postgres
adapter drops its `commit()` and only `session.add`/`merge`s. A new seam, the
**`UnitOfWork` port** (`app/ports/repositories.py`), lets the caller group the
writes of one logical operation into one transaction:

```python
with unit_of_work.begin():
    ...  # every repository write in this logical op
```

Two implementations vary across the seam (`app/db/unit_of_work.py`):

- **`NullUnitOfWork`** — a transparent no-op context for the in-memory path. The
  in-memory fakes apply each write as it happens, so there is no transaction to
  open; the block only groups writes structurally. It never swallows an error
  raised inside it. This is the seam the behavior suite drives with no database.
- **`SessionUnitOfWork`** — one real `session.begin()` transaction over a live
  session: commits every staged row on a clean exit, rolls the whole unit back on
  any exception. A read between units (a repository `all()`) autobegins its own
  read-only transaction on the session; that is ended (`rollback`) before the
  next unit so `begin()` starts clean. Because every write happens inside a unit,
  nothing uncommitted is ever discarded by that reset.

Callers open exactly one unit per logical operation:

- `Simulation._act` wraps an interaction's event + derived example + shadow
  prediction in one unit — they commit together or not at all. It takes a
  `unit_of_work` (default `NullUnitOfWork`), so a sim with no database runs
  unchanged; the Postgres path injects a `SessionUnitOfWork`. Idle ticks open no
  unit.
- `bootstrap.build_simulation` builds the unit (session-backed on the DB path,
  no-op in memory), seeds the being/object parent rows as their own unit, and
  hands the unit to the `Simulation`. ADR 0016's `BuiltSimulation.close` handle
  is untouched — 0016 owns *closing* the session, 0017 owns *committing* through
  it.
- `train_outcome_model.run_training` records the `model_runs` row inside a unit;
  example reads go through the repository port, training runs outside the
  transaction, and the standalone/no-DB path uses the no-op unit.

**Isolation level:** Postgres stays at its default **READ COMMITTED**. The
simulation is a single writer, so the anomalies stronger levels prevent cannot
arise; a higher level would only be worth its cost with concurrent writers, which
would be its own ADR.

## Consequences

- **Atomic writes, no orphan rows.** A mid-unit failure persists none of that
  unit's rows; a completed unit persists all of them together. Pinned by a
  live-Postgres integration test (`test_runtime_persistence.py`) — a committed
  unit survives, a failed unit leaves neither parent nor child — and by a
  fast, DB-free transactional test over in-memory SQLite (`test_unit_of_work.py`)
  that runs without Docker.
- **Foreign keys hold within one transaction.** Event-before-example ordering is
  now SQLAlchemy's dependency-ordered flush inside a single transaction rather
  than two separate commits; the FK-correctness integration test
  (`test_train_outcome_model.py`) is preserved, adapted to inject the unit.
- **The port stays the only seam; the ORM never leaks.** Callers depend on
  `UnitOfWork`, not on SQLAlchemy. The in-memory path needs no database, so the
  pure-model tests are unaffected.
- **Generalizes ADR 0016.** Session *lifecycle* (0016, close) and session
  *transaction boundary* (0017, commit) are now both owned by the runtime seam
  and its injected unit, not scattered across the adapters. The self-commit
  detail 0016 left "deliberately unchanged" is superseded here.
- **Deviations are explicit.** A self-committing write (e.g. an append-only
  single-row write) is allowed only with a stated reason in the code and on its
  card; none remain in v0.
