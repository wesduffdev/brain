"""InMemoryEventBus — the broker-free default EventBus (ADR 0024).

Implements *both* the `EventPublisher` and `EventConsumer` ports in a single
in-process object: `subscribe` registers a handler under a topic, `publish`
delivers an event synchronously to every handler currently subscribed to that
topic. It needs no broker, no network, and no configuration, so it is the default
the whole behavior suite runs on — the same role the in-memory repositories play
for persistence. The Kafka adapter (EVT-KAFKA) implements the same ports for the
runtime; nothing above the port changes when it is swapped in.

Delivery is synchronous and re-entrant-safe: a handler may itself publish (an
`A -> B` chain) because each topic's handler list is snapshotted before dispatch.
The bus carries only validated envelopes — publishing anything that is not a
`DomainEvent` is refused loudly, so a malformed message can never enter the flow.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from app.domain.event import DomainEvent
from app.ports.events import EventHandler


class InMemoryEventBus:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        self._require_topic(topic)
        self._handlers[topic].append(handler)

    def publish(self, topic: str, event: DomainEvent) -> None:
        if not isinstance(event, DomainEvent):
            raise TypeError(
                "publish expects a DomainEvent envelope, got "
                f"{type(event).__name__}"
            )
        self._require_topic(topic)
        # Snapshot the handler list so a handler that publishes onto this same
        # topic (or unsubscribes) cannot mutate the sequence mid-dispatch.
        for handler in list(self._handlers.get(topic, ())):
            handler(event)

    @staticmethod
    def _require_topic(topic: str) -> None:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError(f"topic must be a non-empty string (got {topic!r})")
