"""EventLogEntry — one domain event projected into the durable log (ADR 0028).

The ``event_log`` is the audit + learning projection of everything that flowed
across the event backbone: the relay (`app.outbox_relay`) publishes each staged
outbox envelope and then records it here. The projection is **idempotent on
``event_id``** — a replayed or duplicated envelope leaves the log at exactly one
row — which is also what lets the relay treat the log as its delivery ledger
(an already-logged event is neither re-published nor re-logged).

Like `OutboxEntry`, an entry pairs the topic an envelope travelled on with the
validated `DomainEvent`. Storing the whole envelope keeps the log replayable —
a consumer can rebuild the exact event off a stored row (`DomainEvent`'s
``snapshot``/``from_snapshot``), and the scalar envelope fields (type, being,
correlation) stay queryable in their own columns in the Postgres projection.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.event import DomainEvent


@dataclass(frozen=True)
class EventLogEntry:
    topic: str
    event: DomainEvent

    @property
    def event_id(self) -> str:
        """The projected envelope's stable identity — the log's idempotency key."""
        return self.event.event_id
