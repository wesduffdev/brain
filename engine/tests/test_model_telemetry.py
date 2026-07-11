"""Behaviors of the ModelTelemetry observability observer (EVT-VALID, realizes the
v14 observability slot under ADR 0024 — no new ADR).

`ModelTelemetryService` is a READ-ONLY observer of the instinct chain: it
subscribes to `being.perception.events`, `being.instinct.predictions`, and
`being.instinct.reactions`, pairs each prediction with the reaction it produced,
and publishes a `being.model.telemetry` record of the prediction VS the observed
outcome (accepted when the reaction fired, suppressed when it did not). It also
surfaces a simple consumer-lag gauge (predictions still awaiting their reaction)
and logs a structured correlation trace per hop. It never touches the decision,
emotion, or instinct-selection path — the only thing it writes back to the bus is
the telemetry stream, so a telemetry record can no more shape behavior than a
shadow prediction can.

Everything is asserted through the public surface: publish onto the in-memory bus,
observe the telemetry stream and `lag()`. No torch, no broker, no database.
"""
from __future__ import annotations

import logging

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.domain.event import DomainEvent
from app.services.instinct_service import (
    INSTINCT_PREDICTIONS_TOPIC,
    INSTINCT_REACTIONS_TOPIC,
    PERCEPTION_TOPIC,
    PREDICTION_MADE,
    REACTION_SUPPRESSED,
    REACTION_TRIGGERED,
)
from app.services.model_telemetry_service import (
    TELEMETRY_RECORDED,
    TELEMETRY_TOPIC,
    ModelTelemetryService,
)


def _recorder(bus, topic):
    seen = []
    bus.subscribe(topic, seen.append)
    return seen


def _service(bus):
    return ModelTelemetryService(consumer=bus, publisher=bus, being_id="being_001")


def _root(*, object_id="obj_1", tick=1) -> DomainEvent:
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"objectId": object_id, "tick": tick, "features": {}},
    )


def _prediction(root, *, flinch=0.8, ignore=0.2, intensity=0.8) -> DomainEvent:
    return root.causes(
        event_type=PREDICTION_MADE,
        source_service="instinct-service",
        payload={
            "objectId": "obj_1",
            "tick": 1,
            "reactions": {"flinch": flinch, "ignore": ignore},
            "intensity": intensity,
        },
    )


def _reaction(root, *, label="flinch", intensity=0.8, triggered=True) -> DomainEvent:
    return root.causes(
        event_type=REACTION_TRIGGERED if triggered else REACTION_SUPPRESSED,
        source_service="instinct-service",
        payload={
            "objectId": "obj_1",
            "tick": 1,
            "reaction": label,
            "intensity": intensity,
            "triggered": triggered,
        },
    )


# --- one telemetry record per prediction/observed-outcome pair ----------------


def test_a_prediction_paired_with_its_reaction_emits_one_telemetry_record():
    bus = InMemoryEventBus()
    telemetry = _recorder(bus, TELEMETRY_TOPIC)
    svc = _service(bus)
    root = _root()

    bus.publish(INSTINCT_PREDICTIONS_TOPIC, _prediction(root, flinch=0.8, intensity=0.8))
    bus.publish(INSTINCT_REACTIONS_TOPIC, _reaction(root, label="flinch", intensity=0.8, triggered=True))

    assert len(telemetry) == 1
    record = telemetry[0]
    assert record.event_type == TELEMETRY_RECORDED
    assert record.payload["reaction"] == "flinch"
    assert record.payload["probability"] == 0.8
    assert record.payload["intensity"] == 0.8
    # the reaction fired => the model's prediction was ACCEPTED
    assert record.payload["outcome"] == "accepted"


def test_a_suppressed_reaction_records_the_outcome_as_suppressed():
    bus = InMemoryEventBus()
    telemetry = _recorder(bus, TELEMETRY_TOPIC)
    svc = _service(bus)
    root = _root()

    bus.publish(INSTINCT_PREDICTIONS_TOPIC, _prediction(root, flinch=0.4))
    bus.publish(INSTINCT_REACTIONS_TOPIC, _reaction(root, label="flinch", triggered=False))

    assert len(telemetry) == 1
    assert telemetry[0].payload["outcome"] == "suppressed"


def test_the_telemetry_record_keeps_the_root_correlation_id():
    # observability must be traceable end-to-end: the telemetry record rides the
    # same correlation chain as the perception root that started it.
    bus = InMemoryEventBus()
    telemetry = _recorder(bus, TELEMETRY_TOPIC)
    svc = _service(bus)
    root = _root()

    bus.publish(INSTINCT_PREDICTIONS_TOPIC, _prediction(root))
    bus.publish(INSTINCT_REACTIONS_TOPIC, _reaction(root))

    assert telemetry[0].correlation_id == root.correlation_id


# --- consumer lag: predictions still awaiting their reaction ------------------


def test_lag_counts_a_prediction_that_has_not_yet_seen_its_reaction():
    bus = InMemoryEventBus()
    svc = _service(bus)
    root = _root()

    assert svc.lag() == 0
    bus.publish(INSTINCT_PREDICTIONS_TOPIC, _prediction(root))
    assert svc.lag() == 1  # the consumer is one prediction behind its reactions

    bus.publish(INSTINCT_REACTIONS_TOPIC, _reaction(root))
    assert svc.lag() == 0  # caught up once the reaction lands
    assert svc.processed() == 1


# --- read-only: it writes ONLY the telemetry stream ---------------------------


def test_the_observer_never_writes_back_onto_the_instinct_chain_topics():
    bus = InMemoryEventBus()
    perception = _recorder(bus, PERCEPTION_TOPIC)
    predictions = _recorder(bus, INSTINCT_PREDICTIONS_TOPIC)
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    svc = _service(bus)
    root = _root()

    bus.publish(PERCEPTION_TOPIC, root)
    bus.publish(INSTINCT_PREDICTIONS_TOPIC, _prediction(root))
    bus.publish(INSTINCT_REACTIONS_TOPIC, _reaction(root))

    # exactly what the test published — the observer added nothing to the chain
    assert len(perception) == 1
    assert len(predictions) == 1
    assert len(reactions) == 1


# --- correlation trace logging across the hops --------------------------------


def test_each_hop_logs_a_structured_correlation_trace(caplog):
    bus = InMemoryEventBus()
    svc = _service(bus)
    root = _root()

    with caplog.at_level(logging.INFO, logger="being.telemetry.trace"):
        bus.publish(PERCEPTION_TOPIC, root)
        bus.publish(INSTINCT_PREDICTIONS_TOPIC, _prediction(root))
        bus.publish(INSTINCT_REACTIONS_TOPIC, _reaction(root))

    traced = [r for r in caplog.records if r.name == "being.telemetry.trace"]
    # a structured line per hop, each carrying the SAME correlation id back to root
    types = {getattr(r, "event_type", None) for r in traced}
    assert "being.perception.object_approached" in types
    assert PREDICTION_MADE in types
    assert REACTION_TRIGGERED in types
    assert all(getattr(r, "correlation_id") == root.correlation_id for r in traced)
    # the reaction hop points back to the perception root via causation
    reaction_line = next(r for r in traced if getattr(r, "event_type") == REACTION_TRIGGERED)
    assert getattr(reaction_line, "causation_id") == root.event_id
