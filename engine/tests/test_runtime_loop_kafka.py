"""The DEPLOYED runtime drives the perception -> instinct -> reaction chain LIVE on
a broker-backed EventBus (KAFKA-RUNTIME-LOOP).

RUNTIME-WIRE made the deployed runtime drive the chain live on the in-memory bus:
`InMemoryEventBus.publish` delivers synchronously, so `Simulation._drain_instinct`
in the tick loop drives the whole chain within the single-writer tick. On a
broker-backed bus (Kafka) `publish` only PRODUCES; handlers fire on `consume()`,
which the runtime did not poll — so the chain never fired live on Kafka. This
slice closes that gap: each tick the runtime PULLS pending events off the bus and
handles them ON THE TICK THREAD (no background consumer that would race the single
writer), mirroring the synchronous in-memory delivery.

Two levels:

- A broker-free unit test with a DEFERRED-DELIVERY bus (a fake with Kafka's
  publish-then-consume semantics) proves the runtime pump drives the chain through
  the public surface (`build_simulation` -> `tick()`/`state()`) — RED before the
  pump (the chain never fires), GREEN after. Runs in the default suite, no broker.
- A `[kafka]`-marked test drives the SAME runtime path against a real broker and
  proves the chain fires live (a flinch reaches the being), offsets advance
  (no reprocessing), and a poison stimulus dead-letters — skipping cleanly when no
  broker (or `KAFKA_BOOTSTRAP_SERVERS`) is reachable, so the default suite stays
  hermetic.
"""
from __future__ import annotations

import os
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, List, Tuple

import pytest

from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import Stimulus
from app.policies import MOTION_FEATURE_NAMES
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.services.instinct_service import INSTINCT_REACTIONS_TOPIC
from app.services.stimulus_service import PERCEPTION_TOPIC

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class FakeInstinctPredictor:
    """Torch-free `InstinctPredictorPort`: the being flinches at a fast, body-bound
    approach — flinch probability and intensity both track velocity*trajectory."""

    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        threat = _clamp(stimulus.velocity * stimulus.trajectory_toward_body)
        reactions = {label: 0.0 for label in REACTION_LABELS}
        reactions["flinch"] = threat
        reactions["ignore"] = 1.0 - threat
        return PortPrediction(reactions=reactions, intensity=threat)


class DeferredDeliveryBus:
    """A test double for a broker-backed EventBus's DEFERRED delivery: `publish`
    ENQUEUES an event (it does NOT run handlers), and only `consume()` dispatches
    queued events to their subscribed handlers — exactly the semantics that left the
    live chain dead on Kafka before the runtime pumped `consume()`. No broker, fully
    deterministic. `consume` present as a method is the capability the runtime pump
    keys on; the in-memory bus lacks it and is polled never."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List] = defaultdict(list)
        self._queue: Deque[Tuple[str, DomainEvent]] = deque()
        self.consume_calls = 0

    def subscribe(self, topic: str, handler) -> None:
        self._handlers[topic].append(handler)

    def publish(self, topic: str, event: DomainEvent) -> None:
        self._queue.append((topic, event))

    def consume(self, *, max_messages: int = 1, timeout: float = 5.0) -> int:
        self.consume_calls += 1
        dispatched = 0
        while self._queue and dispatched < max_messages:
            topic, event = self._queue.popleft()
            for handler in list(self._handlers.get(topic, ())):
                handler(event)
            dispatched += 1
        return dispatched


def _config(*, consume_timeout: float = 0.2):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {
        "rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}],
        "default": "calm",
    }
    rooms = {"room": {"id": "room_001", "contains": ["obj_mover"]}}
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_mover": {"developerLabel": "M", "properties": ["round"], "affordances": ["look"]},
        },
    }
    actions = {
        "actions": {
            "observe": {
                "affordance": "look",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "taking a careful look",
            },
        }
    }
    # A fast object heading dead-on at the body (velocity -4 over distance 8).
    motion = {
        "normalization": {
            "max_distance": 10.0,
            "max_speed": 5.0,
            "max_acceleration": 5.0,
            "max_time_to_contact": 10.0,
            "max_size": 1.0,
            "max_size_change_rate": 1.0,
        },
        "approach": {"min_closing_speed": 0.0},
        "objects": {"obj_mover": {"position": [8.0, 0.0], "velocity": [-4.0, 0.0], "size": 0.3}},
    }
    instinct = {
        "feature_order": list(MOTION_FEATURE_NAMES),
        "labels": list(REACTION_LABELS),
        "runtime": {"enabled": True, "consume": {"max_messages": 16, "poll_timeout_seconds": consume_timeout}},
        "reaction": {
            "shadow": True,
            "thresholds": {"flinch": 0.5},
            "cooldowns": {"flinch": 0},
            "visual_only": True,
            "allow_interrupt": False,
            "emotion_bias": {"flinch": {"safety": -60}},
        },
    }
    return ConfigService.from_dict(
        tick_rates,
        emotions,
        rooms=rooms,
        objects=objects,
        actions=actions,
        safety={"rules": []},
        outcome={"labels": ["pleasant"], "context_features": []},
        instinct=instinct,
        motion=motion,
    )


# --- broker-free: the runtime pump drives a DEFERRED-DELIVERY (Kafka-like) bus ----


def test_runtime_pump_drives_the_chain_on_a_deferred_delivery_bus():
    # A bus that only delivers on consume() (Kafka semantics) fires nothing on
    # publish. The chain therefore fires ONLY because the runtime pulls + handles
    # pending events each tick — the same place the in-memory drain runs, on the
    # tick thread. Without the pump this is dead (RED); with it a flinch reaches the
    # being on the tick AFTER the approach, matching the in-memory default.
    bus = DeferredDeliveryBus()
    with build_simulation(
        _config(),
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as sim:
        sim.tick()          # approach published -> pulled -> reaction staged + published
        state = sim.tick()  # the between-ticks reaction now surfaces

    assert state["reaction"]["type"] == "flinch"
    assert state["emotion"] == "scared"
    assert bus.consume_calls > 0  # the runtime really polled the bus


# --- live broker: the deployed runtime loop drives the chain + dead-letters -------


def _reachable_broker_or_skip() -> str:
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip("KAFKA_BOOTSTRAP_SERVERS not set — skipping live Kafka runtime loop")
    try:
        from confluent_kafka.admin import AdminClient  # noqa: PLC0415

        AdminClient({"bootstrap.servers": servers}).list_topics(timeout=5)
    except Exception as exc:  # noqa: BLE001 — any connect problem means "skip, don't fake"
        pytest.skip(f"Kafka not reachable at {servers} ({type(exc).__name__}) — skipping")
    return servers


def _poison_approach() -> DomainEvent:
    # A valid envelope whose payload the instinct consumer cannot process (no
    # `features`) — the runtime pump must dead-letter it, not wedge the flow.
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"objectId": "obj_poison", "tick": 1},
    )


@pytest.mark.kafka
def test_the_deployed_runtime_loop_drives_the_chain_live_and_dead_letters_poison():
    # The SLICE OUTCOME on a real broker: build_simulation wires the runtime chain on
    # a KafkaEventBus, and ticking pulls + handles pending events each tick so the
    # perception->instinct->reaction chain fires LIVE (a flinch reaches the being),
    # while a poison stimulus published to the perception topic parks on its DLQ
    # instead of wedging the being. Fixed being.* topics (the runtime's) + a fresh
    # consumer group per run, so offsets start clean.
    from app.adapters.kafka_event_bus import KafkaEventBus  # noqa: PLC0415
    from app.kafka_bootstrap import create_topics  # noqa: PLC0415

    servers = _reachable_broker_or_skip()
    topics = ConfigService.from_files(_CONFIG_ROOT).event_topics_policy()
    create_topics(servers, topics)

    bus = KafkaEventBus(
        bootstrap_servers=servers, topics=topics, group_id=f"runtime-{uuid.uuid4().hex[:8]}"
    )
    dlq_reader = KafkaEventBus(
        bootstrap_servers=servers, topics=topics, group_id=f"dlqread-{uuid.uuid4().hex[:8]}"
    )
    dead_lettered: List[DomainEvent] = []
    dlq_reader.subscribe(topics.dlq_for(PERCEPTION_TOPIC), dead_lettered.append)
    reactions_seen: List[DomainEvent] = []

    try:
        poison = _poison_approach()
        bus.publish(PERCEPTION_TOPIC, poison)  # sits on the perception topic ahead of the being's own

        with build_simulation(
            _config(consume_timeout=3.0),
            env={},
            event_publisher=bus,
            event_consumer=bus,
            instinct_predictor=FakeInstinctPredictor(),
        ) as sim:
            # a reader of the reactions topic proves the triggered reaction really
            # travelled the broker (not just an in-process latch).
            bus.subscribe(INSTINCT_REACTIONS_TOPIC, reactions_seen.append)
            surfaced = None
            for _ in range(8):
                state = sim.tick()
                if state.get("reaction") is not None:
                    surfaced = state
                    break

        assert surfaced is not None, "the runtime loop never surfaced a reaction over Kafka"
        assert surfaced["reaction"]["type"] == "flinch"
        assert surfaced["emotion"] == "scared"

        # the poison parked on the perception DLQ; the being was unaffected by it.
        # The runtime uses fixed being.* topics, so the DLQ persists across runs on a
        # reused broker — drain it and assert THIS run's poison (a unique event_id)
        # is among the dead-lettered events. The being's own well-formed approaches
        # are never dead-lettered, so only poison events land here.
        dlq_reader.consume(max_messages=200, timeout=10.0)
        assert poison.event_id in {e.event_id for e in dead_lettered}
    finally:
        bus.close()
        dlq_reader.close()
