"""Behavior of the transactional outbox, event-log projection, and instinct
persistence (EVT-PERSIST, ADR 0028).

A domain event must reach the bus *atomically* with the DB writes of the same
logical operation — Kafka+Postgres dual-write is solved by staging an **outbox**
row in the *same* ``uow.begin()`` as the interaction write (ADR 0017), never
publishing inside the transaction. A **relay** later drains the outbox, publishes
each envelope through the ``EventPublisher`` port, and projects it into the
``event_log`` — idempotent on ``event_id`` so a replayed or duplicated row leaves
the log at one row. Instinct predictions/reactions/training-examples get their own
append-only ports so the learning substrate is queryable.

These pin that behavior through the public port surfaces:

- the atomicity proof runs the Postgres adapters against a real (in-memory SQLite)
  session with the ``UnitOfWork`` seam — DB-free, so it runs in the default suite
  (the same DB-free pattern ``test_unit_of_work.py`` uses);
- the relay / projection / instinct behavior runs on the in-memory fakes with a
  recording publisher fake — no broker, no database;
- a live-Postgres round-trip runs the same ports against a real database when
  ``DATABASE_URL`` is reachable, and skips cleanly otherwise (``integration``,
  never faked).
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

from app.db import models
from app.db.migrate import create_all, drop_all
from app.db.session import create_db_engine, session_factory
from app.db.unit_of_work import NullUnitOfWork, SessionUnitOfWork
from app.domain.event import DomainEvent
from app.domain.event_log import EventLogEntry
from app.domain.instinct import (
    InstinctPrediction,
    InstinctReaction,
    instinct_training_example,
)
from app.domain.interaction_event import InteractionEvent
from app.domain.outbox import OutboxEntry
from app.outbox_relay import drain_outbox
from app.repositories import (
    InMemoryEventLogRepository,
    InMemoryInstinctPredictionRepository,
    InMemoryInstinctReactionRepository,
    InMemoryInstinctTrainingExampleRepository,
    InMemoryInteractionEventRepository,
    InMemoryOutboxRepository,
    PostgresEventLogRepository,
    PostgresInstinctPredictionRepository,
    PostgresInstinctReactionRepository,
    PostgresInstinctTrainingExampleRepository,
    PostgresInteractionEventRepository,
    PostgresOutboxRepository,
)

_TOPIC = "being.perception.events"


class _RecordingPublisher:
    """An ``EventPublisher`` fake that records every ``(topic, event)`` it
    delivers, so a test can assert an outbox entry is published exactly once."""

    def __init__(self) -> None:
        self.published = []

    def publish(self, topic, event) -> None:
        self.published.append((topic, event))


def _event(tick: int, event_id=None) -> DomainEvent:
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception",
        being_id="being_001",
        payload={"tick": tick},
        event_id=event_id,
    )


def _outbox_entry(tick: int, event_id=None) -> OutboxEntry:
    return OutboxEntry(topic=_TOPIC, event=_event(tick, event_id))


def _interaction(tick: int) -> InteractionEvent:
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


def _prediction(tick: int, event_id: str) -> InstinctPrediction:
    return InstinctPrediction(
        being_id="being_001",
        tick=tick,
        event_id=event_id,
        features=tuple(0.05 * i for i in range(14)),
        reaction_probabilities=(0.9, 0.1, 0.2, 0.3, 0.05),
        reaction_intensity=0.8,
    )


# --- atomicity: the event and its outbox row commit (or roll back) together ---


def _sqlite_session():
    """A real session over in-memory SQLite with the v0 schema and the being +
    object parent rows the interaction_events foreign keys require — a real
    collaborator below the seam, so atomicity is exercised without Postgres."""
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
    return engine, session


def test_an_interaction_event_and_its_outbox_row_commit_together():
    engine, session = _sqlite_session()
    try:
        events = PostgresInteractionEventRepository(session)
        outbox = PostgresOutboxRepository(session)
        uow = SessionUnitOfWork(session)

        with uow.begin():
            events.add(_interaction(1))
            outbox.add(_outbox_entry(1))

        assert len(events.all()) == 1
        assert len(outbox.all()) == 1
    finally:
        session.close()
        engine.dispose()


def test_a_failed_unit_drops_both_the_event_and_its_outbox_row():
    engine, session = _sqlite_session()
    try:
        events = PostgresInteractionEventRepository(session)
        outbox = PostgresOutboxRepository(session)
        uow = SessionUnitOfWork(session)

        with pytest.raises(RuntimeError):
            with uow.begin():
                events.add(_interaction(1))  # parent staged
                outbox.add(_outbox_entry(1))  # outbox row staged in the SAME unit
                raise RuntimeError("boom mid-unit")

        # a mid-unit failure drops BOTH — no event published without its row,
        # no orphan outbox row without its event
        assert events.all() == []
        assert outbox.all() == []
    finally:
        session.close()
        engine.dispose()


def test_the_null_unit_stages_the_event_and_outbox_row_together():
    events = InMemoryInteractionEventRepository()
    outbox = InMemoryOutboxRepository()
    uow = NullUnitOfWork()

    with uow.begin():
        events.add(_interaction(1))
        outbox.add(_outbox_entry(1))

    assert len(events.all()) == 1
    assert len(outbox.all()) == 1


# --- the relay: publish once, project into the event log, idempotently --------


def test_draining_a_committed_outbox_row_publishes_once_and_writes_one_event_log_row():
    outbox = InMemoryOutboxRepository()
    event_log = InMemoryEventLogRepository()
    publisher = _RecordingPublisher()
    outbox.add(_outbox_entry(1, event_id="evt-1"))

    drained = drain_outbox(outbox=outbox, event_log=event_log, publisher=publisher)

    assert drained == 1
    assert len(publisher.published) == 1
    assert publisher.published[0][0] == _TOPIC
    assert [e.event_id for e in event_log.all()] == ["evt-1"]

    # draining again republishes nothing and adds no new log row
    assert drain_outbox(outbox=outbox, event_log=event_log, publisher=publisher) == 0
    assert len(publisher.published) == 1
    assert len(event_log.all()) == 1


def test_replaying_the_same_event_id_leaves_one_event_log_row():
    event_log = InMemoryEventLogRepository()
    entry = EventLogEntry(topic=_TOPIC, event=_event(1, event_id="evt-1"))

    event_log.add(entry)
    event_log.add(entry)  # replay of the same event_id

    assert [e.event_id for e in event_log.all()] == ["evt-1"]


def test_a_duplicated_outbox_row_is_published_and_logged_once():
    outbox = InMemoryOutboxRepository()
    event_log = InMemoryEventLogRepository()
    publisher = _RecordingPublisher()
    outbox.add(OutboxEntry(topic=_TOPIC, event=_event(1, event_id="evt-1")))
    outbox.add(OutboxEntry(topic=_TOPIC, event=_event(1, event_id="evt-1")))  # same id

    drain_outbox(outbox=outbox, event_log=event_log, publisher=publisher)

    assert len(publisher.published) == 1
    assert len(event_log.all()) == 1


# --- instinct capture: predictions, reactions, and derived training examples --


def test_an_instinct_prediction_and_observed_outcome_build_one_training_example():
    examples = InMemoryInstinctTrainingExampleRepository()
    prediction = _prediction(1, "evt-approach-1")
    observed = (1.0, 0.0, 0.0, 0.0, 0.0)  # the being actually flinched

    example = instinct_training_example(prediction, observed)
    examples.add(example)

    stored = examples.all()
    assert len(stored) == 1
    assert stored[0].event_id == "evt-approach-1"
    assert stored[0].input_features == prediction.features
    assert stored[0].output_labels == observed


def test_instinct_predictions_and_reactions_are_queryable_through_the_ports():
    predictions = InMemoryInstinctPredictionRepository()
    reactions = InMemoryInstinctReactionRepository()

    predictions.add(_prediction(1, "evt-1"))
    reactions.add(
        InstinctReaction(
            being_id="being_001",
            tick=1,
            event_id="evt-1",
            reaction="flinch",
            intensity=0.8,
            triggered=True,
        )
    )

    assert [p.event_id for p in predictions.all()] == ["evt-1"]
    assert [(r.reaction, r.triggered) for r in reactions.all()] == [("flinch", True)]


# --- live Postgres round-trip (skipped when unreachable, never faked) ---------


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
def test_outbox_log_and_instinct_tables_round_trip_through_postgres():
    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so the queries below see only this run
    create_all(engine)
    session = session_factory(engine)()
    try:
        session.add(models.Being(being_id="being_001", needs={}, emotion="calm"))
        session.commit()

        outbox = PostgresOutboxRepository(session)
        event_log = PostgresEventLogRepository(session)
        predictions = PostgresInstinctPredictionRepository(session)
        reactions = PostgresInstinctReactionRepository(session)
        examples = PostgresInstinctTrainingExampleRepository(session)
        uow = SessionUnitOfWork(session)
        publisher = _RecordingPublisher()

        # stage an outbox row in its own unit, then relay it: publish + project
        with uow.begin():
            outbox.add(_outbox_entry(1, event_id="evt-1"))
        drain_outbox(outbox=outbox, event_log=event_log, publisher=publisher, unit_of_work=uow)

        # instinct capture in its own unit
        with uow.begin():
            predictions.add(_prediction(1, "evt-1"))
            reactions.add(
                InstinctReaction(
                    being_id="being_001",
                    tick=1,
                    event_id="evt-1",
                    reaction="flinch",
                    intensity=0.8,
                    triggered=True,
                )
            )
            examples.add(instinct_training_example(_prediction(1, "evt-1"), (1.0, 0.0, 0.0, 0.0, 0.0)))

        assert len(outbox.all()) == 1
        assert [e.event_id for e in event_log.all()] == ["evt-1"]
        assert len(publisher.published) == 1
        # the projected envelope round-trips through from_snapshot re-validation
        assert event_log.all()[0].event.event_type == "being.perception.object_approached"

        # replaying the relay is idempotent — still one event_log row, no re-publish
        drain_outbox(outbox=outbox, event_log=event_log, publisher=publisher, unit_of_work=uow)
        assert len(event_log.all()) == 1
        assert len(publisher.published) == 1

        assert [p.event_id for p in predictions.all()] == ["evt-1"]
        assert [r.reaction for r in reactions.all()] == ["flinch"]
        assert len(examples.all()) == 1
        assert examples.all()[0].output_labels == (1.0, 0.0, 0.0, 0.0, 0.0)
    finally:
        session.close()
        engine.dispose()
