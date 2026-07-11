"""Behavior of the domain-event backbone (EVT-BUS, ADR 0024).

The being's world will be driven by **domain events** — versioned facts one
service produces and others react to (`being.perception.events`,
`being.instinct.predictions`, ...). This slice lays the seam: a validated
`DomainEvent` envelope, an `EventPublisher`/`EventConsumer` port pair, and an
in-memory bus that implements both so the whole suite runs with **no broker**.
Kafka is a later runtime impl behind the same port (EVT-KAFKA).

These pin the behavior through the public surface — the `DomainEvent` envelope
and the `InMemoryEventBus` implementing the ports:

- publishing an event delivers it to a consumer subscribed to that topic (and
  only that topic);
- the `correlation_id`/`causation_id` chain is preserved across a two-hop
  publish (event A causes event B, end-to-end on the bus);
- a malformed envelope is rejected **loudly**, never silently carried.

No broker, no torch, no database is touched — the bus is pure in-process.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.domain.event import DomainEvent

_PERCEPTION_TOPIC = "being.perception.events"
_INSTINCT_TOPIC = "being.instinct.predictions"


def _object_approached() -> DomainEvent:
    """A root `being.*` perception event — its own fresh correlation chain."""
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"object_id": "obj_red_ball", "time_to_contact": 0.4},
    )


# --- publishing delivers to a subscribed consumer ---------------------------


def test_publishing_an_event_delivers_it_to_a_subscribed_consumer():
    bus = InMemoryEventBus()
    received: List[DomainEvent] = []
    bus.subscribe(_PERCEPTION_TOPIC, received.append)

    event = _object_approached()
    bus.publish(_PERCEPTION_TOPIC, event)

    assert len(received) == 1
    delivered = received[0]
    assert delivered.event_id == event.event_id
    assert delivered.event_type == "being.perception.object_approached"
    assert delivered.payload["object_id"] == "obj_red_ball"


def test_a_consumer_receives_only_events_for_its_own_topic():
    bus = InMemoryEventBus()
    perception: List[DomainEvent] = []
    instinct: List[DomainEvent] = []
    bus.subscribe(_PERCEPTION_TOPIC, perception.append)
    bus.subscribe(_INSTINCT_TOPIC, instinct.append)

    bus.publish(_PERCEPTION_TOPIC, _object_approached())

    assert len(perception) == 1
    assert instinct == []  # a different topic's consumer is never touched


def test_a_root_event_starts_its_own_correlation_chain():
    event = _object_approached()

    # A fresh event heads its own trace: it correlates to itself and nothing
    # caused it.
    assert event.correlation_id == event.event_id
    assert event.causation_id is None


# --- correlation/causation preserved across a two-hop publish ---------------


def test_correlation_and_causation_chain_is_preserved_across_a_two_hop_publish():
    bus = InMemoryEventBus()
    downstream: List[DomainEvent] = []

    # Hop 2 consumer: records whatever lands on the instinct topic.
    bus.subscribe(_INSTINCT_TOPIC, downstream.append)

    # Hop 1 consumer: on a perception event, the instinct service reacts by
    # publishing a *caused* event onto the next topic.
    def react(event: DomainEvent) -> None:
        caused = event.causes(
            event_type="being.instinct.prediction_made",
            source_service="instinct-service",
            payload={"reaction": "flinch"},
        )
        bus.publish(_INSTINCT_TOPIC, caused)

    bus.subscribe(_PERCEPTION_TOPIC, react)

    origin = _object_approached()
    bus.publish(_PERCEPTION_TOPIC, origin)

    assert len(downstream) == 1
    effect = downstream[0]
    # B shares A's correlation chain and points back to A as its cause.
    assert effect.correlation_id == origin.correlation_id
    assert effect.causation_id == origin.event_id
    assert effect.being_id == origin.being_id  # the same being carries through


# --- a malformed envelope is rejected loudly --------------------------------


def test_an_empty_event_type_is_rejected_loudly():
    with pytest.raises(ValueError):
        DomainEvent.create(
            event_type="",
            event_version=1,
            source_service="perception-service",
            being_id="being_001",
            payload={},
        )


def test_a_non_positive_event_version_is_rejected_loudly():
    with pytest.raises(ValueError):
        DomainEvent.create(
            event_type="being.perception.object_approached",
            event_version=0,
            source_service="perception-service",
            being_id="being_001",
            payload={},
        )


def test_a_non_mapping_payload_is_rejected_loudly():
    with pytest.raises((ValueError, TypeError)):
        DomainEvent.create(
            event_type="being.perception.object_approached",
            event_version=1,
            source_service="perception-service",
            being_id="being_001",
            payload=["not", "a", "mapping"],  # type: ignore[arg-type]
        )


def test_an_inbound_snapshot_missing_a_required_field_is_rejected_loudly():
    # A realistic inbound event (as a Kafka consumer would rebuild it) that has
    # lost a required field must be refused, never carried onward.
    good = _object_approached().snapshot()
    broken = {key: value for key, value in good.items() if key != "sourceService"}
    with pytest.raises(ValueError):
        DomainEvent.from_snapshot(broken)


def test_publishing_a_non_event_is_rejected_loudly():
    # The port carries validated envelopes only — a raw dict is not an event.
    bus = InMemoryEventBus()
    with pytest.raises(TypeError):
        bus.publish(_PERCEPTION_TOPIC, {"event_type": "nope"})  # type: ignore[arg-type]


# --- the envelope round-trips for the wire ----------------------------------


def test_an_envelope_round_trips_through_its_snapshot():
    event = _object_approached()

    restored = DomainEvent.from_snapshot(event.snapshot())

    assert restored == event
    # timestamps survive as timezone-aware datetimes
    assert isinstance(restored.occurred_at, datetime)
    assert restored.occurred_at.tzinfo is not None
    assert restored.occurred_at.astimezone(timezone.utc) == event.occurred_at
