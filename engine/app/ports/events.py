"""Event ports — the domain-event backbone seam (ADR 0024).

The being's services will stop calling each other directly and instead
**publish** and **subscribe** to versioned `DomainEvent`s on named `being.*`
topics. These two Protocol ports are the *only* surface the sim binds to: a
producer depends on `EventPublisher`, a reactor on `EventConsumer`, and neither
knows whether the event travels through an in-process fake or a broker. There is
deliberately **no Kafka symbol here** — the runtime broker (EVT-KAFKA) is an
adapter *below* this seam, exactly as `PredictorPort` hides torch and
`BeingRepository` hides SQLAlchemy.

The seam is justified by two real implementations, not speculation: the
broker-free `InMemoryEventBus` (`app.adapters.in_memory_event_bus`) the whole
suite runs on, and the Kafka adapter that follows — mirroring how the fast suite
and the `[postgres]`/`[kafka]` integration paths share one port.
"""
from __future__ import annotations

from typing import Callable, Protocol

from app.domain.event import DomainEvent

# A reactor called with each delivered event. Handlers return nothing; a raising
# handler surfaces to the publisher (the broker adapter will route failures to a
# DLQ — EVT-KAFKA).
EventHandler = Callable[[DomainEvent], None]


class EventPublisher(Protocol):
    """Publishes a validated domain event onto a named topic."""

    def publish(self, topic: str, event: DomainEvent) -> None:
        """Deliver ``event`` to every consumer subscribed to ``topic``."""
        ...


class EventConsumer(Protocol):
    """Subscribes a handler to the events on a named topic."""

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Call ``handler`` with each event published to ``topic``."""
        ...
