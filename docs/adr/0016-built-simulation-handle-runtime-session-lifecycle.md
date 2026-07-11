# 0016 — `BuiltSimulation` handle: explicit runtime session lifecycle

## Status

Accepted

## Date

2026-07-10

## Context

`build_simulation` (`app/bootstrap.py`, the runtime wiring seam introduced with
V0-RT) opened a SQLAlchemy `Session` when `DATABASE_URL` was set, handed it to
the Postgres event / training-example / prediction-record adapters, and returned
a bare `Simulation`. Nothing ever closed that session. Once a finished run read
its interactions back (`Simulation.interactions()` / `.predictions()` issue a
SELECT), the session sat **idle-in-transaction** holding `ACCESS SHARE` locks on
the tables it read. A later test's `drop_all` (`DROP TABLE` needs `ACCESS
EXCLUSIVE`) then blocked on that lock forever, so the full `pytest -m
integration` run against live Postgres **hung** (proven via `pg_stat_activity`).
The leak was equally real in production: the served engine and the demo never
released their session either.

The seam already owned wiring persistence *up* (deciding from the environment
whether to open a DB at all, and hiding all of it behind one call). What was
missing is that it did not own tearing that wiring *down*. Putting `close()` on
`Simulation` was rejected: `Simulation` is the pure psychology domain surface and
must not know that a SQLAlchemy session exists.

## Decision

`build_simulation` returns a **`BuiltSimulation`** handle instead of a bare
`Simulation`:

- `.simulation` — the wired being, run exactly as before.
- `.close()` — runs the teardown the bootstrap chose: on the DB path it closes
  the session (rolling back any open read/write transaction, so no locks linger)
  and disposes the engine's pool; with no database it is a no-op. Idempotent.
- It is also a context manager whose `with` block yields the `Simulation` and
  closes on exit, so a script runs and tidies up in one breath.

The teardown is an internally-chosen `Callable`, **not** an injected port: it
varies (DB vs no-op) along the same env-driven branch that already varies, and
nothing injects it, so no new seam is introduced (deep-module rule: no seam until
something varies *across* it from the outside).

Callers own the lifecycle:

- `app/main.py` holds the handle and closes it on FastAPI **shutdown** (a
  `lifespan` context manager); an injected simulation owns its own lifecycle, so
  there is nothing to tear down then.
- `app/demo.py` uses the `with` form, closing after the run.
- Tests close the handle in teardown so `drop_all` never blocks.

The DB **schema** and the repositories' **commit-per-write** pattern are
deliberately unchanged — this ADR is only about who closes the session.

## Consequences

- **The integration suite no longer hangs.** A finished run releases its session,
  so schema teardown proceeds; the full `-m integration` run completes green. A
  regression test pins this: after a run + read + `close()`, a fresh connection
  takes `ACCESS EXCLUSIVE` and drops the tables under a bounded `lock_timeout`, so
  any future leak fails fast instead of hanging CI.
- **Callers unwrap `.simulation`.** The one ergonomic cost of the handle; it buys
  deterministic teardown and keeps `Simulation` free of resource concerns.
- **Follow-up — TXN-UOW.** This fixes session *lifecycle* only. A broader
  unit-of-work refactor (owning session/transaction boundaries around a tick, and
  the repositories' commit pattern) is the separate `TXN-UOW` ticket; the general
  session/transaction-ownership decision belongs with it and may supersede the
  lifecycle detail recorded here.
