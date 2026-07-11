"""bootstrap — assemble a runtime `Simulation`, persistence and all.

One function, `build_simulation`, is the seam between "a being that runs" and
"a being that *remembers*". It decides — from the environment — whether the
engine persists, and hides all of that wiring behind a single call the runtime
entrypoints (`app.main`, `app.demo`) make instead of constructing `Simulation`
directly.

When `DATABASE_URL` is set it opens a live session, ensures the schema, seeds the
being + object parent rows the interaction/object foreign keys require, and wires
the Postgres event / training-example / prediction-record adapters (ADR
0007/0011/0012) — plus the shadow-mode outcome predictor when a trained artifact
is present (graceful `None` otherwise, ADR 0011). A running engine then writes
`interaction_events`, `training_examples`, and `prediction_records` as it acts.

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
from typing import Mapping, Optional

from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all
from app.db.session import create_db_engine, session_factory
from app.ml.inference import load_predictor
from app.ports.predictor import PredictorPort
from app.ports.repositories import (
    InteractionEventRepository,
    PredictionRecordRepository,
    TrainingExampleRepository,
)
from app.repositories import (
    PostgresInteractionEventRepository,
    PostgresPredictionRecordRepository,
    PostgresTrainingExampleRepository,
)
from app.simulation import Simulation

# The trained artifact lives beside the trainer's output (see train_outcome_model);
# absent before training, in which case shadow mode stays off (ADR 0011).
_DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "outcome_predictor.pt"


def build_simulation(
    config: ConfigService,
    *,
    being_id: str = "being_001",
    env: Optional[Mapping[str, str]] = None,
    event_repo: Optional[InteractionEventRepository] = None,
    training_repo: Optional[TrainingExampleRepository] = None,
    prediction_repository: Optional[PredictionRecordRepository] = None,
    predictor: Optional[PredictorPort] = None,
) -> Simulation:
    """Build a runtime `Simulation`, wiring persistence when configured.

    With `DATABASE_URL` set (and no repositories injected), opens a session,
    ensures the schema, seeds the parent rows, and wires the Postgres adapters
    plus a shadow-mode predictor when one loads. Otherwise returns a plain
    in-memory being. Injected ports/predictor take precedence, so tests wire the
    full path with fakes and no database.
    """
    env = os.environ if env is None else env
    url = env.get("DATABASE_URL")

    persistence_injected = (
        event_repo is not None
        or training_repo is not None
        or prediction_repository is not None
    )

    if url and not persistence_injected:
        session = _open_session(url)
        _seed_parents(session, config, being_id)
        event_repo = PostgresInteractionEventRepository(session)
        training_repo = PostgresTrainingExampleRepository(session)
        prediction_repository = PostgresPredictionRecordRepository(session)
        if predictor is None:
            predictor = _load_predictor(config, env)

    return Simulation(
        config,
        being_id,
        event_repo=event_repo,
        training_repo=training_repo,
        predictor=predictor,
        prediction_repository=prediction_repository,
    )


def _open_session(url: str):
    """A live session on ``url``. Ensures the v0 schema exists first (idempotent),
    so seeding and the first writes never hit a missing table."""
    engine = create_db_engine(url)
    create_all(engine)
    return session_factory(engine)()


def _seed_parents(session, config: ConfigService, being_id: str) -> None:
    """Insert the being + object rows the `interaction_events` / `objects` foreign
    keys depend on. Idempotent (``merge`` by primary key), so restarting an
    already-seeded engine is a no-op rather than a duplicate-key error. This is the
    runtime bootstrap seed that used to live inline in the integration tests."""
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
    session.commit()


def _load_predictor(config: ConfigService, env: Mapping[str, str]) -> Optional[PredictorPort]:
    """The shadow-mode predictor, or ``None`` when it cannot run. Reads the
    artifact path from ``MODEL_PATH`` (default beside the trainer's output);
    `load_predictor` returns ``None`` gracefully when torch or the artifact is
    absent, and raises loudly on a stale artifact (ADR 0008/0011)."""
    model_path = env.get("MODEL_PATH", str(_DEFAULT_MODEL_PATH))
    return load_predictor(config=config, model_path=model_path)
