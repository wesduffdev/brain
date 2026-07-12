"""KafkaEventBus — the runtime EventBus backed by a Kafka broker (EVT-KAFKA, ADR 0024).

This implements the same `EventPublisher` / `EventConsumer` ports as
`InMemoryEventBus`, so **nothing above the seam changes** when the sim runs on a
real broker instead of the in-process fake — exactly as the Postgres repository
adapter stands in for the in-memory one (ADR 0007). The whole behavior suite
still runs on the fake with no broker; this adapter is the runtime path.

What it adds over the fake, the concerns the queue pins to the broker (ADR 0024
§Consequences) rather than to the port:

- **Broker URL from the environment.** `KAFKA_BOOTSTRAP_SERVERS` is deploy config,
  read from the env only (never authored YAML), the same category as
  `DATABASE_URL`. Topic NAMES and partition/DLQ conventions come from config
  (`EventTopicsPolicy`); this adapter hardcodes none of them.
- **Snapshot serialization.** An event travels as the JSON of its `snapshot()` —
  the stable camelCase wire form the envelope already defines — keyed by
  `being_id` so one being's events keep per-key order on its partition. A consumer
  rebuilds it with `from_snapshot`, which re-validates loudly, so a malformed
  message can never enter the flow.
- **Idempotent, at-least-once consume.** Kafka redelivers on retry; the consumer
  dedupes on `event_id`, so a re-seen event is dropped rather than handled twice.
- **DLQ on failure.** A message a handler cannot process — its handler raised, or
  the bytes would not deserialize into a valid envelope — is routed to the topic's
  `<topic>.dlq` companion (`EventTopicsPolicy.dlq_for`) and consumption continues,
  so one poison message parks to the side instead of wedging the whole flow.

`confluent_kafka` is imported **lazily** (inside the producer/consumer factories),
the same discipline `ConfigService` uses for `yaml` and the predictor for `torch`:
this module imports with no C extension loaded, and the pure serialization helpers
below are usable — and testable — with no broker present.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from typing import Dict, List, Optional

from app.domain.event import DomainEvent
from app.policies import EventTopicsPolicy
from app.ports.events import EventHandler

# The env var the broker URL is read from — deploy config, never authored YAML.
BOOTSTRAP_ENV = "KAFKA_BOOTSTRAP_SERVERS"

_LOG = logging.getLogger("being.events.kafka")


def serialize_event(event: DomainEvent) -> bytes:
    """A domain event as the JSON bytes of its stable `snapshot()` wire form."""
    if not isinstance(event, DomainEvent):
        raise TypeError(
            f"serialize_event expects a DomainEvent, got {type(event).__name__}"
        )
    return json.dumps(event.snapshot()).encode("utf-8")


def deserialize_event(data: bytes) -> DomainEvent:
    """Rebuild a domain event from its serialized snapshot, re-validating loudly.
    Raises `ValueError` (via `from_snapshot`) on bytes that are not a valid,
    complete envelope — the signal the consumer uses to route a poison message to
    the DLQ rather than carry it onward."""
    return DomainEvent.from_snapshot(json.loads(data.decode("utf-8")))


def bootstrap_servers_from_env(env: Optional[Dict[str, str]] = None) -> str:
    """The broker URL from `KAFKA_BOOTSTRAP_SERVERS`. Like `DATABASE_URL`, it is
    read from the environment only and refuses to guess a default — an unset URL is
    a configuration error, not a silent fallback to some local broker."""
    env = os.environ if env is None else env
    url = env.get(BOOTSTRAP_ENV)
    if not url:
        raise RuntimeError(
            f"{BOOTSTRAP_ENV} is not set — the Kafka broker is configured from the "
            f"environment only (see .env.example)"
        )
    return url


class KafkaEventBus:
    """A broker-backed EventBus (both ports) — see the module docstring.

    Construct with an explicit `bootstrap_servers`, or `KafkaEventBus.from_env(...)`
    to read it from `KAFKA_BOOTSTRAP_SERVERS`. The producer and consumer are built
    lazily on first use, so constructing the bus touches no broker; a runtime that
    only publishes never opens a consumer, and vice versa.
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topics: EventTopicsPolicy,
        group_id: str = "being-eventbus",
    ) -> None:
        self._bootstrap = bootstrap_servers
        self._topics = topics
        self._group_id = group_id
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._seen_event_ids: set = set()
        self._producer = None
        self._consumer = None

    @classmethod
    def from_env(
        cls,
        *,
        topics: EventTopicsPolicy,
        group_id: str = "being-eventbus",
        env: Optional[Dict[str, str]] = None,
    ) -> "KafkaEventBus":
        """Build a bus whose broker URL comes from `KAFKA_BOOTSTRAP_SERVERS`."""
        return cls(
            bootstrap_servers=bootstrap_servers_from_env(env),
            topics=topics,
            group_id=group_id,
        )

    # --- EventPublisher --------------------------------------------------

    def publish(self, topic: str, event: DomainEvent) -> None:
        """Serialize `event` and produce it to `topic`, keyed by its being so one
        being's events keep per-key order. Mirrors the fake's fail-loud guards: a
        non-`DomainEvent` and an empty topic are refused before anything reaches
        the wire."""
        if not isinstance(event, DomainEvent):
            raise TypeError(
                "publish expects a DomainEvent envelope, got "
                f"{type(event).__name__}"
            )
        self._require_topic(topic)
        producer = self._get_producer()
        producer.produce(topic, value=serialize_event(event), key=event.being_id)
        producer.flush()

    # --- EventConsumer ---------------------------------------------------

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Register `handler` for `topic` and (re)subscribe the consumer to every
        topic subscribed so far, so one bus can fan a single poll loop across the
        being.* topics it cares about."""
        self._require_topic(topic)
        self._handlers[topic].append(handler)
        self._get_consumer().subscribe(list(self._handlers.keys()))

    def consume(self, *, max_messages: int = 1, timeout: float = 5.0) -> int:
        """Drive the poll loop: dispatch up to `max_messages` events to their
        subscribed handlers and return how many were dispatched, giving up after
        `timeout` seconds of no new message. This is the runtime driver the port
        does not mandate (a live runtime loops it; a test calls it once). Each
        message is deduped on `event_id` (a redelivery is dropped) and, if it
        cannot be deserialized or its handler raises, routed to the topic's DLQ so
        consumption is never wedged by one bad event. Its offset is committed only
        AFTER it is resolved (handled, deduped, or dead-lettered), so the runtime that
        drives this loop each tick has at-least-once delivery."""
        consumer = self._get_consumer()
        dispatched = 0
        while dispatched < max_messages:
            message = consumer.poll(timeout)
            if message is None:
                break  # no message within the timeout — stop waiting
            if message.error():
                # A poll result can carry a librdkafka SIGNAL instead of a payload.
                # TWO are transient and must NOT crash the consumer — skip them and
                # keep polling within the timeout budget:
                #   * _PARTITION_EOF — reached the end of a partition (benign).
                #   * UNKNOWN_TOPIC_OR_PART — a freshly-created topic (or a brand-new
                #     consumer) whose metadata has not yet propagated to THIS client.
                #     On a FRESH broker the bootstrap has already created the being.*
                #     topics, so this is a metadata-propagation lag, not a missing
                #     topic; librdkafka refreshes metadata and delivery then proceeds.
                # Any OTHER error is a genuine broker/transport problem the caller
                # should see, and stays fatal.
                from confluent_kafka import KafkaError  # noqa: PLC0415

                code = message.error().code()
                if code == KafkaError.UNKNOWN_TOPIC_OR_PART:
                    _LOG.debug(
                        "tolerating transient %s (topic=%s) — metadata not yet "
                        "propagated; continuing to poll",
                        message.error(),
                        message.topic(),
                    )
                    continue
                if code == KafkaError._PARTITION_EOF:
                    continue
                raise RuntimeError(f"kafka consume error: {message.error()}")
            handled = self._handle(message)
            # Commit the offset only AFTER the message is fully resolved — dispatched,
            # deduped, or dead-lettered. A handler failure never reaches here
            # unresolved: `_handle` routes it to the DLQ and returns. So a crash before
            # this commit reprocesses the event rather than skipping it (at-least-once);
            # the `event_id` dedupe drops any resulting redelivery.
            consumer.commit(message=message, asynchronous=False)
            if handled:
                dispatched += 1
        return dispatched

    def close(self) -> None:
        """Release broker resources — flush any buffered produces and close the
        consumer group membership. Safe to call when neither was opened."""
        if self._producer is not None:
            self._producer.flush()
        if self._consumer is not None:
            self._consumer.close()

    # --- internals -------------------------------------------------------

    def _handle(self, message) -> bool:
        """Process one polled message; return True when it was dispatched to a
        handler, False when it was deduped or dead-lettered. A raw message that
        will not deserialize, and a handler that raises, both route the original
        bytes to the topic's DLQ."""
        topic = message.topic()
        raw = message.value()
        try:
            event = deserialize_event(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            self._to_dlq(topic, raw)
            return False

        if event.event_id in self._seen_event_ids:
            return False  # idempotent: a redelivered event is dropped
        self._seen_event_ids.add(event.event_id)

        try:
            for handler in list(self._handlers.get(topic, ())):
                handler(event)
        except Exception:  # noqa: BLE001 — any handler failure dead-letters, never wedges
            self._to_dlq(topic, raw)
            return False
        return True

    def _to_dlq(self, topic: str, raw: bytes) -> None:
        producer = self._get_producer()
        producer.produce(self._topics.dlq_for(topic), value=raw)
        producer.flush()

    def _get_producer(self):
        if self._producer is None:
            from confluent_kafka import Producer  # noqa: PLC0415 — lazy: no C ext at import

            self._producer = Producer({"bootstrap.servers": self._bootstrap})
        return self._producer

    def _get_consumer(self):
        if self._consumer is None:
            from confluent_kafka import Consumer  # noqa: PLC0415 — lazy: no C ext at import

            self._consumer = Consumer(
                {
                    "bootstrap.servers": self._bootstrap,
                    "group.id": self._group_id,
                    # Read a topic from its start so a consumer that subscribes
                    # after a publish still sees the event (the single-being sim
                    # is not a high-throughput live tail).
                    "auto.offset.reset": "earliest",
                    # Commit offsets MANUALLY, only after a message is handled (see
                    # `consume`) — not on a timer — so the runtime loop is at-least-once:
                    # a crash mid-handling reprocesses rather than skips.
                    "enable.auto.commit": False,
                }
            )
        return self._consumer

    @staticmethod
    def _require_topic(topic: str) -> None:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError(f"topic must be a non-empty string (got {topic!r})")
