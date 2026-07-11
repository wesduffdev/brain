"""`[kafka]`-marked integration: the perception -> instinct -> reaction chain runs
over a REAL Kafka broker, with consumer idempotency and DLQ routing (EVT-VALID).

These mirror the `[postgres]` split: they exercise the live broker end of the
`EventBus` seam and SKIP cleanly when no broker (or `KAFKA_BOOTSTRAP_SERVERS`) is
reachable, so the default suite stays hermetic and green with no broker. Each run
uses freshly, uniquely-named topics so it starts from empty offsets and cannot
collide with another run.

The shadow `InstinctService` (INS-RT) is wired to consume `ObjectApproached` off a
live topic and stage its reaction; a torch-free fake predictor stands in for the
trained model, so these need a broker but not torch.
"""
from __future__ import annotations

import os
import uuid
from typing import List, Tuple

import pytest

from app.adapters.kafka_event_bus import KafkaEventBus
from app.db.unit_of_work import NullUnitOfWork
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import InstinctFeatureEncoder, InstinctSpec, Stimulus
from app.outbox_relay import drain_outbox
from app.policies import MOTION_FEATURE_NAMES, EventTopicsPolicy, InstinctRuntimePolicy
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.repositories import (
    InMemoryEventLogRepository,
    InMemoryInstinctPredictionRepository,
    InMemoryInstinctReactionRepository,
    InMemoryOutboxRepository,
)
from app.services.instinct_service import InstinctService


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class FakeInstinctPredictor:
    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        threat = _clamp(stimulus.velocity * stimulus.trajectory_toward_body)
        reactions = {label: 0.0 for label in REACTION_LABELS}
        reactions["flinch"] = threat
        reactions["ignore"] = 1.0 - threat
        return PortPrediction(reactions=reactions, intensity=threat)


def _encoder() -> InstinctFeatureEncoder:
    return InstinctFeatureEncoder(
        InstinctSpec(feature_order=MOTION_FEATURE_NAMES, label_vocab=REACTION_LABELS)
    )


def _policy() -> InstinctRuntimePolicy:
    return InstinctRuntimePolicy(thresholds={"flinch": 0.5}, cooldowns={"flinch": 0}, shadow=True)


def _approach(*, event_id=None, tick=1, **feature_overrides) -> DomainEvent:
    features = {name: 0.0 for name in MOTION_FEATURE_NAMES}
    features.update(feature_overrides)
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"objectId": "obj_1", "tick": tick, "features": features},
        event_id=event_id,
    )


def _reachable_broker_or_skip() -> str:
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip("KAFKA_BOOTSTRAP_SERVERS not set — skipping live Kafka chain")
    try:
        from confluent_kafka.admin import AdminClient  # noqa: PLC0415

        AdminClient({"bootstrap.servers": servers}).list_topics(timeout=5)
    except Exception as exc:  # noqa: BLE001 — any connect problem means "skip, don't fake"
        pytest.skip(f"Kafka not reachable at {servers} ({type(exc).__name__}) — skipping")
    return servers


@pytest.fixture
def live_chain():
    """A reachable broker plus fresh, uniquely-named perception + reaction topics
    (and their .dlq companions) so a run starts from empty offsets."""
    from app.kafka_bootstrap import create_topics  # noqa: PLC0415

    servers = _reachable_broker_or_skip()
    suffix = uuid.uuid4().hex[:8]
    perception = f"being.test.perc.{suffix}"
    reactions = f"being.test.react.{suffix}"
    policy = EventTopicsPolicy(names=(perception, reactions), partitions=1, dlq_suffix=".dlq")
    create_topics(servers, policy)
    return servers, perception, reactions, policy


def _service(bus, *, perception_topic):
    predictions = InMemoryInstinctPredictionRepository()
    reactions = InMemoryInstinctReactionRepository()
    outbox = InMemoryOutboxRepository()
    service = InstinctService(
        consumer=bus,
        publisher=bus,
        predictor=FakeInstinctPredictor(),
        encoder=_encoder(),
        policy=_policy(),
        being_id="being_001",
        predictions=predictions,
        reactions=reactions,
        outbox=outbox,
        unit_of_work=NullUnitOfWork(),
        source_topic=perception_topic,
    )
    return service, predictions, reactions, outbox


@pytest.mark.kafka
def test_the_perception_to_reaction_chain_runs_over_a_live_broker(live_chain):
    servers, perception, reactions_topic, policy = live_chain
    bus = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"chain-{uuid.uuid4().hex[:8]}"
    )
    _, _, reactions_repo, outbox = _service(bus, perception_topic=perception)
    try:
        root = _approach(velocity=1.0, trajectory_toward_body=1.0)
        bus.publish(perception, root)

        # drive the poll loop: the consumer runs the model + selection on data
        # delivered over the real broker and stages one reaction.
        dispatched = bus.consume(max_messages=1, timeout=20.0)
        assert dispatched == 1
        assert len(reactions_repo.all()) == 1
        assert reactions_repo.all()[0].triggered is True
        assert reactions_repo.all()[0].reaction == "flinch"

        # the staged reaction round-trips a real reactions topic, keeping the trace.
        for entry in outbox.all():
            bus.publish(reactions_topic, entry.event)
        reader = KafkaEventBus(
            bootstrap_servers=servers, topics=policy, group_id=f"read-{uuid.uuid4().hex[:8]}"
        )
        seen: List[DomainEvent] = []
        reader.subscribe(reactions_topic, seen.append)
        try:
            reader.consume(max_messages=len(outbox.all()), timeout=20.0)
        finally:
            reader.close()
        triggered = [e for e in seen if e.correlation_id == root.correlation_id and e.payload.get("triggered")]
        assert triggered, "the triggered reaction should travel the real reactions topic"
    finally:
        bus.close()


@pytest.mark.kafka
def test_a_duplicate_object_approached_yields_exactly_one_reaction_over_a_live_broker(live_chain):
    servers, perception, _reactions_topic, policy = live_chain
    bus = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"idem-{uuid.uuid4().hex[:8]}"
    )
    _, predictions, reactions_repo, _ = _service(bus, perception_topic=perception)
    try:
        approach = _approach(event_id="evt-dup", velocity=1.0, trajectory_toward_body=1.0)
        bus.publish(perception, approach)
        bus.publish(perception, approach)  # a redelivery of the same event_id

        bus.consume(max_messages=2, timeout=20.0)

        # deduped end-to-end: one prediction, one reaction, no double effect.
        assert len(predictions.all()) == 1
        assert len(reactions_repo.all()) == 1
    finally:
        bus.close()


@pytest.mark.kafka
def test_a_poison_stimulus_routes_to_the_dlq_over_a_live_broker(live_chain):
    servers, perception, _reactions_topic, policy = live_chain
    bus = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"dlq-{uuid.uuid4().hex[:8]}"
    )
    _, predictions, reactions_repo, outbox = _service(bus, perception_topic=perception)

    # a fresh reader on the perception topic's DLQ companion
    dlq_reader = KafkaEventBus(
        bootstrap_servers=servers, topics=policy, group_id=f"dlqread-{uuid.uuid4().hex[:8]}"
    )
    dead_lettered: List[DomainEvent] = []
    dlq_reader.subscribe(policy.dlq_for(perception), dead_lettered.append)
    try:
        malformed = DomainEvent.create(
            event_type="being.perception.object_approached",
            event_version=1,
            source_service="perception-service",
            being_id="being_001",
            payload={"objectId": "obj_1", "tick": 1},  # no `features` -> unprocessable
        )
        bus.publish(perception, malformed)

        # the consumer cannot process it: nothing is staged, and it is dead-lettered
        # (the poison stimulus parks off to the side instead of wedging the flow).
        bus.consume(max_messages=1, timeout=20.0)
        assert predictions.all() == []
        assert reactions_repo.all() == []

        recovered = dlq_reader.consume(max_messages=1, timeout=20.0)
        assert recovered == 1
        assert dead_lettered[0].event_id == malformed.event_id
    finally:
        bus.close()
        dlq_reader.close()
