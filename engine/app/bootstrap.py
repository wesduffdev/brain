"""bootstrap — assemble a runtime `Simulation`, persistence and all.

One function, `build_simulation`, is the seam between "a being that runs" and
"a being that *remembers*". It decides — from the environment — whether the
engine persists, and hides all of that wiring behind a single call the runtime
entrypoints (`app.main`, `app.demo`) make instead of constructing `Simulation`
directly.

Because the seam owns whatever it opens, it also owns tearing it down: it hands
back a `BuiltSimulation` handle carrying the `Simulation` and a `close()` that
releases the resources the wiring opened (with a live DB, the SQLAlchemy session
and its engine; with none, a no-op). A caller runs the being and then closes the
handle — on FastAPI shutdown, after a demo run, in a test teardown — so a
finished run never leaves a session idle-in-transaction holding locks that would
block a later schema teardown. The handle is also a context manager, so
`with build_simulation(cfg) as sim:` runs and closes in one breath.

When `DATABASE_URL` is set it opens a live session, ensures the schema, seeds the
being + object parent rows the interaction/object foreign keys require, and wires
the Postgres event / training-example / prediction-record / memory adapters (ADR
0007/0011/0012, card v1) — plus the shadow-mode outcome predictor when a trained
artifact is present (graceful `None` otherwise, ADR 0011). It also builds the unit
of work that owns the transaction boundary (ADR 0017): a session-backed unit on
the DB path, the no-op unit in memory. The seed is one unit; then a running engine
writes `interaction_events`, `training_examples`, `prediction_records`, and
`memories` a unit per interaction, so an interaction's rows commit together or not
at all.

When `DATABASE_URL` is unset (and nothing is injected) it returns a plain
in-memory `Simulation` — no database, no shadow mode, behavior unchanged. There
is no hard DB dependency: the connection string is deploy/secret config read from
the environment only (like `JWT_SECRET`), never authored YAML (ADR 0005).

Injected repositories/predictor always win over the environment, so the behavior
suite drives the whole wiring with in-memory fakes and a fake predictor without a
database — the same deep-module test seam `app.main.create_app` uses.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Mapping, Optional

from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all
from app.db.session import create_db_engine, session_factory
from app.db.unit_of_work import NullUnitOfWork, SessionUnitOfWork
from app.ml.inference import load_predictor
from app.ports.predictor import PredictorPort
from app.ports.repositories import (
    BeliefRepository,
    ConceptRepository,
    GraphRepository,
    InteractionEventRepository,
    MemoryRepository,
    PredictionRecordRepository,
    SimilarityRepository,
    TrainingExampleRepository,
    UnitOfWork,
)
from app.repositories import (
    PostgresBeliefRepository,
    PostgresConceptRepository,
    PostgresGraphRepository,
    PostgresInteractionEventRepository,
    PostgresMemoryRepository,
    PostgresPredictionRecordRepository,
    PostgresSimilarityRepository,
    PostgresTrainingExampleRepository,
)
from app.simulation import Simulation

# The trained artifact lives beside the trainer's output (see train_outcome_model);
# absent before training, in which case shadow mode stays off (ADR 0011).
_DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "outcome_predictor.pt"


def _noop() -> None:
    """The teardown for an in-memory being: nothing was opened, nothing to close."""


class BuiltSimulation:
    """A wired `Simulation` together with the teardown for whatever backs it.

    `build_simulation` returns this instead of a bare `Simulation` so the caller
    that owns the run also owns releasing its resources. `close()` runs the
    teardown the bootstrap chose — closing the SQLAlchemy session and disposing
    its engine on the DB path, a no-op in memory — and is idempotent. It doubles
    as a context manager whose ``with`` block yields the `Simulation` and closes
    on exit, so a script can run and tidy up in one breath.
    """

    def __init__(self, simulation: Simulation, close: Callable[[], None] = _noop) -> None:
        self.simulation = simulation
        self._close = close
        self._closed = False

    def close(self) -> None:
        """Release the resources the wiring opened. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._close()

    def __enter__(self) -> Simulation:
        return self.simulation

    def __exit__(self, *_exc) -> bool:
        self.close()
        return False


def build_simulation(
    config: ConfigService,
    *,
    being_id: str = "being_001",
    env: Optional[Mapping[str, str]] = None,
    event_repo: Optional[InteractionEventRepository] = None,
    training_repo: Optional[TrainingExampleRepository] = None,
    prediction_repository: Optional[PredictionRecordRepository] = None,
    memory_repository: Optional[MemoryRepository] = None,
    concept_repository: Optional[ConceptRepository] = None,
    belief_repository: Optional[BeliefRepository] = None,
    similarity_repository: Optional[SimilarityRepository] = None,
    graph_repository: Optional[GraphRepository] = None,
    predictor: Optional[PredictorPort] = None,
) -> BuiltSimulation:
    """Build a runtime `Simulation`, wiring persistence when configured.

    With `DATABASE_URL` set (and no repositories injected), opens a session,
    ensures the schema, seeds the parent rows, and wires the Postgres adapters
    plus a shadow-mode predictor when one loads. Otherwise the being is plain and
    in-memory. Injected ports/predictor take precedence, so tests wire the full
    path with fakes and no database.

    Returns a :class:`BuiltSimulation` handle: read ``.simulation`` to run the
    being and call ``.close()`` (or use it as a context manager) when done, which
    releases the session/engine on the DB path so a finished run never strands a
    session idle-in-transaction.
    """
    env = os.environ if env is None else env
    url = env.get("DATABASE_URL")

    persistence_injected = (
        event_repo is not None
        or training_repo is not None
        or prediction_repository is not None
        or memory_repository is not None
        or concept_repository is not None
        or belief_repository is not None
        or similarity_repository is not None
        or graph_repository is not None
    )

    close: Callable[[], None] = _noop
    unit_of_work: UnitOfWork = NullUnitOfWork()
    if url and not persistence_injected:
        session, engine = _open_session(url)
        unit_of_work = SessionUnitOfWork(session)
        _seed_parents(session, unit_of_work, config, being_id)
        event_repo = PostgresInteractionEventRepository(session)
        training_repo = PostgresTrainingExampleRepository(session)
        prediction_repository = PostgresPredictionRecordRepository(session)
        memory_repository = PostgresMemoryRepository(session)
        concept_repository = PostgresConceptRepository(session)
        belief_repository = PostgresBeliefRepository(session)
        similarity_repository = PostgresSimilarityRepository(session)
        graph_repository = PostgresGraphRepository(session)
        if predictor is None:
            predictor = _load_predictor(config, env)
        close = _teardown(session, engine)

    simulation = Simulation(
        config,
        being_id,
        event_repo=event_repo,
        training_repo=training_repo,
        predictor=predictor,
        prediction_repository=prediction_repository,
        memory_repository=memory_repository,
        concept_repository=concept_repository,
        belief_repository=belief_repository,
        similarity_repository=similarity_repository,
        graph_repository=graph_repository,
        unit_of_work=unit_of_work,
    )
    return BuiltSimulation(simulation, close)


def _open_session(url: str):
    """A live session on ``url``, with the engine that backs it. Ensures the v0
    schema exists first (idempotent), so seeding and the first writes never hit a
    missing table. The engine is returned alongside so teardown can dispose it."""
    engine = create_db_engine(url)
    create_all(engine)
    return session_factory(engine)(), engine


def _teardown(session, engine) -> Callable[[], None]:
    """The DB-path teardown: close the session (rolling back any open read/write
    transaction, so no locks linger) and dispose its engine's pool."""

    def close() -> None:
        session.close()
        engine.dispose()

    return close


def _seed_parents(
    session, unit_of_work: UnitOfWork, config: ConfigService, being_id: str
) -> None:
    """Insert the being + object rows the `interaction_events` / `objects` foreign
    keys depend on, as one unit of work (ADR 0017) — the seed commits atomically
    before any interaction row is written. Idempotent (``merge`` by primary key),
    so restarting an already-seeded engine is a no-op rather than a duplicate-key
    error. This is the runtime bootstrap seed that used to live inline in the
    integration tests."""
    with unit_of_work.begin():
        session.merge(models.Being(being_id=being_id, needs={}, emotion=config.default_emotion()))
        for entity in config.object_catalog().values():
            session.merge(
                models.ObjectRecord(
                    object_id=entity.object_id,
                    developer_label=entity.developer_label,
                    properties=list(entity.properties),
                    affordances=list(entity.affordances),
                )
            )


def _load_predictor(config: ConfigService, env: Mapping[str, str]) -> Optional[PredictorPort]:
    """The shadow-mode predictor, or ``None`` when it cannot run. Reads the
    artifact path from ``MODEL_PATH`` (default beside the trainer's output);
    `load_predictor` returns ``None`` gracefully when torch or the artifact is
    absent, and raises loudly on a stale artifact (ADR 0008/0011)."""
    model_path = env.get("MODEL_PATH", str(_DEFAULT_MODEL_PATH))
    return load_predictor(config=config, model_path=model_path)
