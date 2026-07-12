"""REACTION-EVENTS-PERSIST (ADR 0042): the being's active-reaction events —
`EmotionBiasApplied` and `ActionInterrupted` — are now DURABLE.

ADR 0029 shipped them as transient signals published straight to the bus. This
slice routes them through the transactional outbox instead (ADR 0028): a triggered
reaction STAGES its event into an outbox in the tick's unit of work (ADR 0017), and
a relay publishes it and projects it into an idempotent event log — atomic with the
tick's writes, no dual-write.

Asserted through the public surface only — `Simulation.tick()`, `Simulation.state()`,
`Simulation.event_log()` (the durable projection), and the events on the in-memory
bus — plus a DB-free atomicity proof over the Postgres repositories on SQLite
(mirroring `test_transactional_outbox.py`): a reaction event and an interaction
commit or roll back TOGETHER. No torch, no broker, no live database.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all
from app.db.session import session_factory
from app.db.unit_of_work import SessionUnitOfWork
from app.domain.event import DomainEvent
from app.domain.interaction_event import InteractionEvent
from app.domain.outbox import OutboxEntry
from app.outbox_relay import drain_outbox
from app.repositories import (
    InMemoryEventLogRepository,
    InMemoryOutboxRepository,
    PostgresInteractionEventRepository,
    PostgresOutboxRepository,
)
from app.simulation import Simulation
from app.services.reaction_response_service import (
    ACTION_EVENTS_TOPIC,
    ACTION_INTERRUPTED,
    EMOTION_BIAS_APPLIED,
    INSTINCT_REACTIONS_TOPIC,
    REACTION_TRIGGERED,
    STATE_EVENTS_TOPIC,
)

# --- config identical in shape to the INS-ACT behaviour suite -----------------
_EMOTIONS = {
    "rules": [
        {"emotion": "scared", "need": "safety", "op": "<=", "value": 30},
        {"emotion": "curious", "need": "curiosity", "op": ">=", "value": 70},
    ],
    "default": "calm",
}
_OBJECTS = {
    "properties": ["soft", "hard"],
    "affordances": ["look", "touch"],
    "objects": {
        "obj_soft": {"developerLabel": "Soft Thing", "properties": ["soft"], "affordances": ["look", "touch"]},
    },
}
_ACTIONS = {
    "actions": {
        "observe": {
            "affordance": "look",
            "utility": {"base": 10.0, "needs": {}, "emotions": {}},
            "expected_outcomes": ["pleasant"],
            "reason": "taking a careful look",
        },
    }
}


def _needs(**overrides):
    levels = {"curiosity": 40, "safety": 80, "comfort": 70, "hunger": 30, "sleep": 30, "warmth": 50}
    levels.update(overrides)
    needs = {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }
    needs["pain"] = {"direction": "decrease", "amount": 2, "every_ticks": 4, "min": 0, "max": 100, "start": 0}
    return needs


def _reaction_block(*, visual_only=False, allow_interrupt=False):
    return {
        "labels": ["flinch", "freeze", "orient", "withdraw", "ignore"],
        "reaction": {
            "thresholds": {"flinch": 0.5},
            "cooldowns": {"flinch": 5},
            "shadow": True,
            "visual_only": visual_only,
            "allow_interrupt": allow_interrupt,
            "emotion_bias": {"flinch": {"safety": -60}},
            "interrupt": {
                "intensity_threshold": 0.7,
                "interruptible_actions": ["observe", "touch"],
                "protective_action": "withdraw",
            },
        },
    }


def _config(*, contains=(), visual_only=False, allow_interrupt=False):
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": _needs()},
        _EMOTIONS,
        rooms={"room": {"id": "room_001", "contains": list(contains)}},
        objects=_OBJECTS,
        outcome={"labels": ["pleasant"], "context_features": []},
        actions=_ACTIONS,
        safety={"rules": []},
        instinct=_reaction_block(visual_only=visual_only, allow_interrupt=allow_interrupt),
    )


def _sim(config):
    bus = InMemoryEventBus()
    return Simulation(config, event_publisher=bus, event_consumer=bus), bus


def _recorder(bus, topic):
    seen = []
    bus.subscribe(topic, seen.append)
    return seen


def _flinch(*, intensity=0.9, object_id="obj_soft", tick=1):
    return DomainEvent.create(
        event_type=REACTION_TRIGGERED,
        event_version=1,
        source_service="instinct-service",
        being_id="being_001",
        payload={"objectId": object_id, "tick": tick, "reaction": "flinch",
                 "intensity": intensity, "triggered": True},
    )


# --- durable projection through the public surface ----------------------------


def test_a_triggered_interruption_is_projected_into_the_durable_event_log():
    sim, bus = _sim(_config(contains=("obj_soft",), visual_only=True, allow_interrupt=True))
    action_events = _recorder(bus, ACTION_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.95))

    state = sim.tick()

    # behaviour unchanged: the action is broken off and ActionInterrupted still reaches the bus
    assert "currentAction" not in state
    assert [e.event_type for e in action_events] == [ACTION_INTERRUPTED]
    # NEW: the event is DURABLE — projected into the idempotent event log exactly once
    interrupted = [e for e in sim.event_log() if e["eventType"] == ACTION_INTERRUPTED]
    assert len(interrupted) == 1
    assert interrupted[0]["payload"]["action"] == "observe"


def test_an_emotion_bias_applied_event_is_projected_into_the_durable_event_log():
    sim, bus = _sim(_config(contains=(), visual_only=True))
    state_events = _recorder(bus, STATE_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.9))

    sim.tick()

    assert [e.event_type for e in state_events] == [EMOTION_BIAS_APPLIED]
    biases = [e for e in sim.event_log() if e["eventType"] == EMOTION_BIAS_APPLIED]
    assert len(biases) == 1
    assert biases[0]["payload"]["reaction"] == "flinch"


def test_the_reaction_event_log_keeps_one_row_when_the_relay_replays():
    # The outbox is append-only and re-drained every tick; an already-logged event is
    # neither re-published nor re-projected — idempotent on event_id (ADR 0028).
    sim, bus = _sim(_config(contains=("obj_soft",), visual_only=True, allow_interrupt=True))
    action_events = _recorder(bus, ACTION_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.95))

    sim.tick()                       # tick 1: interruption + bias staged, relayed, projected
    logged_after_first = len(sim.event_log())
    sim.tick()                       # tick 2: no new reaction -> relay re-drains the same rows
    sim.tick()                       # tick 3: likewise

    assert logged_after_first == 2   # one EmotionBiasApplied + one ActionInterrupted
    assert len(sim.event_log()) == logged_after_first
    assert [e.event_type for e in action_events].count(ACTION_INTERRUPTED) == 1


def test_no_reaction_no_event_log_rows():
    # A being that never receives a reaction stages nothing — the durable log stays empty.
    sim, _bus = _sim(_config(contains=("obj_soft",), visual_only=True, allow_interrupt=True))
    sim.tick()
    sim.tick()
    assert sim.event_log() == []


# --- atomicity proof: a reaction event and an interaction share the unit of work ---


def _sqlite_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    session = session_factory(engine)()
    session.add(models.Being(being_id="being_001", needs={}, emotion="calm"))
    session.add(models.ObjectRecord(object_id="obj_soft", developer_label="Soft",
                                    properties=["soft"], affordances=["touch"]))
    session.commit()
    return engine, session


def _interaction(tick):
    return InteractionEvent(being_id="being_001", tick=tick, object_id="obj_soft",
                            action="touch", expected_outcome=("pleasant",),
                            observed_outcome=("pleasant",), emotion_before="calm",
                            emotion_after="calm")


def _action_interrupted_event(tick, event_id=None):
    return DomainEvent.create(
        event_type=ACTION_INTERRUPTED, event_version=1,
        source_service="reaction-response-service", being_id="being_001",
        payload={"action": "observe", "targetId": "obj_soft", "reaction": "flinch",
                 "intensity": 0.9, "tick": tick},
        event_id=event_id,
    )


def test_an_interaction_and_its_action_interrupted_outbox_row_commit_together():
    engine, session = _sqlite_session()
    try:
        events = PostgresInteractionEventRepository(session)
        outbox = PostgresOutboxRepository(session)
        uow = SessionUnitOfWork(session)
        with uow.begin():
            events.add(_interaction(1))
            outbox.add(OutboxEntry(topic=ACTION_EVENTS_TOPIC, event=_action_interrupted_event(1)))
        assert len(events.all()) == 1
        assert len(outbox.all()) == 1
    finally:
        session.close()
        engine.dispose()


def test_a_failed_unit_drops_both_the_interaction_and_the_action_interrupted_row():
    engine, session = _sqlite_session()
    try:
        events = PostgresInteractionEventRepository(session)
        outbox = PostgresOutboxRepository(session)
        uow = SessionUnitOfWork(session)
        with pytest.raises(RuntimeError):
            with uow.begin():
                events.add(_interaction(1))
                outbox.add(OutboxEntry(topic=ACTION_EVENTS_TOPIC, event=_action_interrupted_event(1)))
                raise RuntimeError("boom mid-unit")
        # a mid-unit failure drops BOTH — no reaction event without its data, no orphan row
        assert events.all() == []
        assert outbox.all() == []
    finally:
        session.close()
        engine.dispose()


class _RecordingPublisher:
    def __init__(self):
        self.published = []

    def publish(self, topic, event):
        self.published.append((topic, event))


def test_draining_a_staged_reaction_event_projects_one_log_row_idempotently():
    outbox = InMemoryOutboxRepository()
    event_log = InMemoryEventLogRepository()
    publisher = _RecordingPublisher()
    outbox.add(OutboxEntry(topic=ACTION_EVENTS_TOPIC, event=_action_interrupted_event(1, event_id="ai-1")))

    assert drain_outbox(outbox=outbox, event_log=event_log, publisher=publisher) == 1
    assert [e.event_id for e in event_log.all()] == ["ai-1"]
    # replay: neither re-published nor re-logged
    assert drain_outbox(outbox=outbox, event_log=event_log, publisher=publisher) == 0
    assert len(publisher.published) == 1
    assert len(event_log.all()) == 1
