"""Behavior of the Kafka runtime EventBus (EVT-KAFKA, ADR 0024).

The `EventPublisher` / `EventConsumer` ports gain a broker-backed implementation
so the SAME sim code runs on the in-process fake (the whole suite) or on Kafka
(the runtime), with nothing above the seam changing. These pin the behavior that
can be observed WITHOUT a broker — the topic topology config wiring and the
snapshot serialization the adapter puts on the wire — plus one `[kafka]`-marked
integration test that drives a real publish -> consume, dedupe, and DLQ against a
live broker. The live test SKIPS when no broker (or `KAFKA_BOOTSTRAP_SERVERS`) is
reachable, so the default suite stays hermetic and green with no broker.
"""
from __future__ import annotations

import os
import uuid
from typing import List

import pytest

from app.adapters.kafka_event_bus import (
    KafkaEventBus,
    bootstrap_servers_from_env,
    deserialize_event,
    serialize_event,
)
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.policies import EventTopicsPolicy

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _object_approached() -> DomainEvent:
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"object_id": "obj_red_ball", "time_to_contact": 0.4},
    )


# --- topic topology comes from config, not the adapter (broker-free) --------


def test_config_wires_the_being_topic_catalogue_with_partitions_and_dlq_suffix():
    policy = ConfigService.from_files(_CONFIG_ROOT).event_topics_policy()

    assert "being.perception.events" in policy.names
    assert "being.model.telemetry" in policy.names
    # Sized for a single being (queue guardrail), and being.* never npc.*.
    assert policy.partitions == 1
    assert all(name.startswith("being.") for name in policy.names)
    assert policy.dlq_suffix == ".dlq"


def test_every_catalogue_topic_gets_a_dlq_companion_in_the_bootstrap_set():
    policy = EventTopicsPolicy(names=("being.perception.events", "being.action.events"))

    assert policy.dlq_for("being.perception.events") == "being.perception.events.dlq"
    # bootstrap provisions each topic followed by its .dlq companion.
    assert policy.bootstrap_topics() == (
        "being.perception.events",
        "being.perception.events.dlq",
        "being.action.events",
        "being.action.events.dlq",
    )


# --- the wire form the adapter serializes (broker-free) ---------------------


def test_an_event_round_trips_through_the_kafka_serialization():
    event = _object_approached()

    restored = deserialize_event(serialize_event(event))

    assert restored == event
    assert restored.payload["object_id"] == "obj_red_ball"


def test_serialization_preserves_the_correlation_and_causation_chain():
    origin = _object_approached()
    downstream = origin.causes(
        event_type="being.instinct.prediction_made",
        source_service="instinct-service",
        payload={"reaction": "flinch"},
    )

    restored = deserialize_event(serialize_event(downstream))

    # The trace survives the wire: B still points back to A.
    assert restored.correlation_id == origin.correlation_id
    assert restored.causation_id == origin.event_id


def test_a_corrupt_message_is_rejected_loudly_so_the_consumer_can_dead_letter_it():
    # The signal the consumer uses to route a poison message to the DLQ instead of
    # carrying garbage onward.
    with pytest.raises((ValueError, TypeError)):
        deserialize_event(b"this is not a valid event envelope")


# --- broker URL is env config, never authored YAML (broker-free) ------------


def test_broker_url_is_read_from_the_environment_and_refuses_to_guess():
    assert bootstrap_servers_from_env({"KAFKA_BOOTSTRAP_SERVERS": "broker:9092"}) == "broker:9092"
    with pytest.raises(RuntimeError):
        bootstrap_servers_from_env({})  # unset is a config error, not a silent default


def test_publishing_a_non_event_is_refused_before_touching_the_broker():
    # Port parity with the in-memory fake: a raw dict is not an event, and an empty
    # topic is invalid — both fail loudly before any producer is opened, so this
    # needs no broker.
    bus = KafkaEventBus(bootstrap_servers="unused:9092", topics=EventTopicsPolicy())
    with pytest.raises(TypeError):
        bus.publish("being.perception.events", {"event_type": "nope"})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        bus.publish("   ", _object_approached())


# --- live broker: publish -> consume, dedupe, DLQ (skips with no broker) -----


def _reachable_broker_or_skip() -> str:
    """The KAFKA_BOOTSTRAP_SERVERS broker, or skip with a clear reason. Never
    fakes a broker: an unset env var or an unreachable broker skips this live
    variant rather than substituting one — the same discipline the live-Postgres
    round-trips use."""
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip("KAFKA_BOOTSTRAP_SERVERS not set — skipping live Kafka round-trip")
    try:
        from confluent_kafka.admin import AdminClient  # noqa: PLC0415

        AdminClient({"bootstrap.servers": servers}).list_topics(timeout=5)
    except Exception as exc:  # noqa: BLE001 — any connect problem means "skip, don't fake"
        pytest.skip(f"Kafka not reachable at {servers} ({type(exc).__name__}) — skipping")
    return servers


@pytest.fixture
def live_topics(request):
    """A fresh, uniquely-named topic + its .dlq on a reachable broker, so each run
    starts from empty offsets and cannot collide with another run. Skips when no
    broker is reachable."""
    from app.kafka_bootstrap import create_topics  # noqa: PLC0415

    servers = _reachable_broker_or_skip()
    suffix = uuid.uuid4().hex[:8]
    policy = EventTopicsPolicy(names=(f"being.test.{suffix}",), partitions=1, dlq_suffix=".dlq")
    create_topics(servers, policy)
    return servers, policy


@pytest.mark.kafka
def test_publish_then_consume_delivers_the_event_over_a_live_broker(live_topics):
    servers, policy = live_topics
    topic = policy.names[0]
    bus = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"test-{uuid.uuid4().hex[:8]}"
    )
    received: List[DomainEvent] = []
    bus.subscribe(topic, received.append)
    try:
        event = _object_approached()
        bus.publish(topic, event)

        dispatched = bus.consume(max_messages=1, timeout=15.0)

        assert dispatched == 1
        assert received[0].event_id == event.event_id
        assert received[0].payload["object_id"] == "obj_red_ball"
    finally:
        bus.close()


@pytest.mark.kafka
def test_a_redelivered_event_is_deduped_on_event_id(live_topics):
    servers, policy = live_topics
    topic = policy.names[0]
    bus = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"test-{uuid.uuid4().hex[:8]}"
    )
    received: List[DomainEvent] = []
    bus.subscribe(topic, received.append)
    try:
        event = _object_approached()
        bus.publish(topic, event)
        bus.publish(topic, event)  # the same event_id, delivered twice

        first = bus.consume(max_messages=1, timeout=15.0)
        second = bus.consume(max_messages=1, timeout=10.0)

        assert first == 1  # handled once
        assert second == 0  # the redelivery is dropped, not handled again
        assert len(received) == 1
    finally:
        bus.close()


@pytest.mark.kafka
def test_a_handler_failure_routes_the_event_to_the_topic_dlq(live_topics):
    servers, policy = live_topics
    topic = policy.names[0]
    consumer_bus = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"test-{uuid.uuid4().hex[:8]}"
    )

    def boom(_event: DomainEvent) -> None:
        raise RuntimeError("handler cannot process this event")

    consumer_bus.subscribe(topic, boom)

    # A separate bus reads the DLQ companion to prove the poison event landed there.
    dlq_bus = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"dlq-{uuid.uuid4().hex[:8]}"
    )
    dead_lettered: List[DomainEvent] = []
    dlq_bus.subscribe(policy.dlq_for(topic), dead_lettered.append)

    try:
        event = _object_approached()
        consumer_bus.publish(topic, event)

        # The handler raises, so the event is NOT dispatched — it is dead-lettered
        # and consumption is not wedged.
        dispatched = consumer_bus.consume(max_messages=1, timeout=15.0)
        assert dispatched == 0

        # The original event bytes are now on the DLQ topic.
        recovered = dlq_bus.consume(max_messages=1, timeout=15.0)
        assert recovered == 1
        assert dead_lettered[0].event_id == event.event_id
    finally:
        consumer_bus.close()
        dlq_bus.close()
