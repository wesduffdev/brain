"""Behavior of wiring persistence into the runtime (V0-RT).

The runtime engine — the being behind `main.py` and the demo — is assembled by a
bootstrap factory that hides the persistence wiring behind one call. When
`DATABASE_URL` is set it opens a live session, ensures the schema, seeds the
being + object parent rows the foreign keys require, and hands a `Simulation`
the Postgres event / training-example / prediction-record adapters (plus a
shadow-mode predictor when one is available), so a running engine writes
`interaction_events`, `training_examples`, and `prediction_records` — not just
the test harness. With no `DATABASE_URL` (and nothing injected) it returns a
plain in-memory `Simulation`, so the no-DB path is unchanged and there is no hard
DB dependency.

These tests pin that behavior through the bootstrap's public surface:

- the fake path injects the in-memory repos + a behaving fake predictor, so the
  wiring is proven end-to-end without a database (events, examples, predictions
  land through the ports as the being acts);
- the no-DB path proves an unconfigured engine still runs, in memory, with no
  persistence and shadow mode off;
- a live Postgres round-trip runs the same bootstrap against a real database and
  counts the rows it wrote, skipping cleanly (never faking) when DATABASE_URL is
  unset or unreachable.
"""
from __future__ import annotations

import os
from typing import Dict

import pytest
from sqlalchemy import text

from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all, drop_all
from app.db.models import Base
from app.db.session import create_db_engine, session_factory
from app.db.unit_of_work import SessionUnitOfWork
from app.domain.interaction_event import InteractionEvent
from app.domain.training_example import TrainingExample
from app.ml.encode_features import Example
from app.repositories import (
    InMemoryInteractionEventRepository,
    InMemoryPredictionRecordRepository,
    InMemoryTrainingExampleRepository,
    PostgresInteractionEventRepository,
    PostgresTrainingExampleRepository,
)

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_OUTCOME_LABELS = (
    "rolls",
    "bounces",
    "falls",
    "causes_pain",
    "makes_noise",
    "pleasant",
    "scary",
)


class _FakePredictor:
    """A PredictorPort that returns fixed probabilities — the seam that turns
    shadow mode on without torch or an artifact, so prediction records are
    written for every interaction."""

    def __init__(self, probabilities: Dict[str, float]):
        self._probabilities = probabilities

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        return dict(self._probabilities)


def _fake_predictor() -> _FakePredictor:
    return _FakePredictor({label: 0.5 for label in _OUTCOME_LABELS})


# --- the bootstrap wires the injected ports into a running being -------------


def test_the_bootstrap_wires_repos_and_records_events_examples_and_predictions():
    # Inject the in-memory repos + a fake predictor: no DATABASE_URL is needed to
    # prove the wiring — running the being writes an event and a derived example
    # per affordance interaction, and a prediction per interaction, through the
    # ports the bootstrap wired.
    config = ConfigService.from_files(_CONFIG_ROOT)
    events = InMemoryInteractionEventRepository()
    examples = InMemoryTrainingExampleRepository()
    predictions = InMemoryPredictionRecordRepository()

    with build_simulation(
        config,
        env={},
        event_repo=events,
        training_repo=examples,
        prediction_repository=predictions,
        predictor=_fake_predictor(),
    ) as sim:
        for _ in range(80):
            sim.tick()

        assert len(sim.interactions()) > 0, "the being should have acted at least once"
        assert len(events.all()) == len(sim.interactions())
        assert len(examples.all()) > 0, "an affordance interaction should derive an example"
        assert len(predictions.all()) == len(sim.predictions()) > 0


def test_without_a_database_url_the_engine_runs_in_memory_with_no_persistence():
    # The no-DB path is unchanged: the being still acts and logs its interactions
    # in memory, nothing raises, and with no predictor loaded shadow mode is off.
    config = ConfigService.from_files(_CONFIG_ROOT)

    with build_simulation(config, env={}) as sim:
        for _ in range(20):
            sim.tick()

        assert len(sim.interactions()) > 0
        assert sim.predictions() == []


# --- live Postgres round-trip (skipped when unreachable, never faked) --------


def _reachable_postgres_or_skip():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping live Postgres round-trip")
    try:
        engine = create_db_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connect failure means "skip, don't fake"
        pytest.skip(f"Postgres not reachable at DATABASE_URL ({type(exc).__name__}) — skipping")
    return engine


@pytest.mark.integration
def test_a_configured_engine_persists_events_examples_predictions_to_postgres():
    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so the counts below see only this run
    create_all(engine)

    # The bootstrap opens its own session, ensures the schema, seeds the being +
    # object parent rows, and wires the Postgres adapters. A fake predictor turns
    # shadow mode on so prediction records are written too.
    config = ConfigService.from_files(_CONFIG_ROOT)
    built = build_simulation(
        config,
        env={"DATABASE_URL": os.environ["DATABASE_URL"]},
        predictor=_fake_predictor(),
    )
    sim = built.simulation
    try:
        for _ in range(80):
            sim.tick()

        session = session_factory(engine)()
        try:
            event_count = session.query(models.InteractionEvent).count()
            example_count = session.query(models.TrainingExample).count()
            prediction_count = session.query(models.PredictionRecord).count()

            assert event_count == len(sim.interactions()) > 0
            assert example_count > 0
            assert prediction_count == len(sim.predictions()) > 0
        finally:
            session.close()
    finally:
        # Close the runtime's own session so its read transaction (and locks) is
        # released before the next test's schema teardown — the regression this
        # bug fixed.
        built.close()
        engine.dispose()


@pytest.mark.integration
def test_a_finished_run_releases_its_session_so_schema_teardown_never_blocks():
    # Regression (bug: bootstrap session leak). The runtime bootstrap opened a
    # session that no one closed; once a finished run read its interactions back,
    # that session sat idle-in-transaction holding ACCESS SHARE locks, so a later
    # `drop_all` (which needs ACCESS EXCLUSIVE) blocked forever and the whole
    # integration suite hung. Closing the built handle must release the session so
    # schema teardown proceeds. The DROP below is bounded by a `lock_timeout`, so a
    # regression fails fast here instead of hanging the suite.
    engine = _reachable_postgres_or_skip()
    drop_all(engine)
    create_all(engine)

    config = ConfigService.from_files(_CONFIG_ROOT)
    built = build_simulation(
        config,
        env={"DATABASE_URL": os.environ["DATABASE_URL"]},
        predictor=_fake_predictor(),
    )
    sim = built.simulation
    for _ in range(20):
        sim.tick()
    # the reads that used to strand the runtime's session idle-in-transaction
    assert len(sim.interactions()) > 0
    _ = sim.predictions()

    built.close()  # must release the runtime's session (and any locks it held)

    # A fresh, independent connection must now be able to take ACCESS EXCLUSIVE and
    # drop the tables. Bound the wait so a leak regression errors in seconds rather
    # than hanging the run.
    guard = create_db_engine(os.environ["DATABASE_URL"])
    try:
        with guard.connect() as conn:
            conn.execute(text("SET lock_timeout = '5s'"))
            Base.metadata.drop_all(bind=conn)
            conn.commit()
    finally:
        guard.dispose()


# --- atomic unit of work: commit-together / rollback-whole (ADR 0017) --------


def _touch_event(tick: int) -> InteractionEvent:
    return InteractionEvent(
        being_id="being_001",
        tick=tick,
        object_id="obj_soft",
        action="touch",
        expected_outcome=("pleasant",),
        observed_outcome=("pleasant",),
        emotion_before="calm",
        emotion_after="calm",
    )


def _derived_example(event_id: str) -> TrainingExample:
    return TrainingExample(event_id=event_id, input_features=(1.0,), output_labels=(1.0,))


@pytest.mark.integration
def test_a_unit_commits_together_and_a_failed_unit_leaves_no_orphan_rows_in_postgres():
    # The atomic-write invariant against a real database: a completed unit
    # persists an interaction_event and its derived training_example together;
    # a unit that fails mid-way persists neither — no orphan parent, no orphan
    # child. A fresh, independent session reads the committed state, so this
    # observes real transaction boundaries, not the writer's identity map.
    engine = _reachable_postgres_or_skip()
    drop_all(engine)
    create_all(engine)

    seed = session_factory(engine)()
    try:
        seed.add(models.Being(being_id="being_001", needs={}, emotion="calm"))
        seed.add(
            models.ObjectRecord(
                object_id="obj_soft",
                developer_label="Soft",
                properties=["soft"],
                affordances=["touch"],
            )
        )
        seed.commit()
    finally:
        seed.close()

    session = session_factory(engine)()
    events = PostgresInteractionEventRepository(session)
    examples = PostgresTrainingExampleRepository(session)
    uow = SessionUnitOfWork(session)
    try:
        # a complete unit: parent event + child example commit together
        with uow.begin():
            events.add(_touch_event(1))
            examples.add(_derived_example("being_001:1"))

        # a failed unit: both staged rows roll back as one
        with pytest.raises(RuntimeError):
            with uow.begin():
                events.add(_touch_event(2))
                examples.add(_derived_example("being_001:2"))
                raise RuntimeError("boom mid-unit")
    finally:
        session.close()

    verify = session_factory(engine)()
    try:
        assert verify.query(models.InteractionEvent).count() == 1
        assert verify.query(models.TrainingExample).count() == 1
        # the surviving rows are the committed unit's, not the rolled-back one's
        assert verify.query(models.InteractionEvent).one().tick == 1
        assert verify.query(models.TrainingExample).one().event_id == "being_001:1"
    finally:
        verify.close()
        engine.dispose()
