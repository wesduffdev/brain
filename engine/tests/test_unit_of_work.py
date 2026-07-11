"""Behavior of the unit-of-work seam (TXN-UOW, ADR 0017).

A single logical operation persists atomically or not at all. Repositories only
*stage* writes (``add``/``merge``); the caller opens one transaction per unit of
work through the ``UnitOfWork`` seam, so the rows of one operation commit
together and a failure mid-unit rolls the whole unit back — no orphan child rows.

Two implementations satisfy the seam and are pinned here:

- ``NullUnitOfWork`` — the in-memory, no-database context the behavior suite
  drives: a transparent no-op that still lets any error inside it propagate.
- ``SessionUnitOfWork`` — a real transaction over a SQLAlchemy ``Session``. Its
  atomicity is proven against a real (in-memory SQLite) database with the real
  Postgres adapters staging into it: a completed unit commits every staged row,
  a failed unit persists none of them. (The live-Postgres round-trip, which also
  exercises foreign-key enforcement, lives in ``test_runtime_persistence.py``.)
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app.db import models
from app.db.migrate import create_all
from app.db.session import session_factory
from app.db.unit_of_work import NullUnitOfWork, SessionUnitOfWork
from app.domain.interaction_event import InteractionEvent
from app.domain.training_example import TrainingExample
from app.repositories import (
    InMemoryInteractionEventRepository,
    PostgresInteractionEventRepository,
    PostgresTrainingExampleRepository,
)


def _event(event_tick: int) -> InteractionEvent:
    return InteractionEvent(
        being_id="being_001",
        tick=event_tick,
        object_id="obj_soft",
        action="touch",
        expected_outcome=("pleasant",),
        observed_outcome=("pleasant",),
        emotion_before="calm",
        emotion_after="calm",
    )


def _example(event_id: str) -> TrainingExample:
    return TrainingExample(event_id=event_id, input_features=(1.0,), output_labels=(1.0,))


@pytest.fixture()
def sql_session():
    """A real session over an in-memory SQLite database with the v0 schema — a
    real collaborator below the seam, so the unit-of-work's transaction behavior
    is exercised without Docker or Postgres.

    The being + object parent rows the interaction_events foreign keys require
    are seeded first (as the runtime bootstrap does), so the units below stage
    FK-correct writes — SQLite now enforces foreign keys like Postgres (TEST-FK)."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    session = session_factory(engine)()
    session.add(models.Being(being_id="being_001", needs={}, emotion="calm"))
    session.add(
        models.ObjectRecord(
            object_id="obj_soft",
            developer_label="Soft",
            properties=["soft"],
            affordances=["touch"],
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# --- the in-memory (null) unit of work: a transparent no-op ------------------


def test_the_null_unit_of_work_lets_staged_writes_land():
    events = InMemoryInteractionEventRepository()
    uow = NullUnitOfWork()

    with uow.begin():
        events.add(_event(1))

    assert [e.tick for e in events.all()] == [1]


def test_the_null_unit_of_work_does_not_swallow_an_error_inside_it():
    uow = NullUnitOfWork()

    with pytest.raises(RuntimeError):
        with uow.begin():
            raise RuntimeError("boom")


# --- the session unit of work: one transaction per logical op ----------------


def test_a_completed_unit_commits_every_staged_row_together(sql_session):
    events = PostgresInteractionEventRepository(sql_session)
    examples = PostgresTrainingExampleRepository(sql_session)
    uow = SessionUnitOfWork(sql_session)

    with uow.begin():
        events.add(_event(1))
        examples.add(_example("being_001:1"))

    # a fresh session sees the committed rows — the whole unit landed
    verify = session_factory(sql_session.get_bind())()
    try:
        assert [e.tick for e in events.all()] == [1]
        assert len(examples.all()) == 1
    finally:
        verify.close()


def test_a_failure_mid_unit_persists_no_rows_from_that_unit(sql_session):
    events = PostgresInteractionEventRepository(sql_session)
    examples = PostgresTrainingExampleRepository(sql_session)
    uow = SessionUnitOfWork(sql_session)

    with pytest.raises(RuntimeError):
        with uow.begin():
            events.add(_event(1))  # parent row staged
            examples.add(_example("being_001:1"))  # child row staged
            raise RuntimeError("boom mid-unit")

    # nothing from the failed unit survives — no orphan parent, no orphan child
    assert events.all() == []
    assert examples.all() == []


def test_units_are_independent_a_committed_unit_survives_a_later_rollback(sql_session):
    events = PostgresInteractionEventRepository(sql_session)
    uow = SessionUnitOfWork(sql_session)

    with uow.begin():
        events.add(_event(1))  # first unit commits cleanly

    with pytest.raises(RuntimeError):
        with uow.begin():
            events.add(_event(2))  # second unit rolls back
            raise RuntimeError("boom")

    assert [e.tick for e in events.all()] == [1]
