"""OutboxEntry — one domain event staged for atomic publication (ADR 0028).

The transactional-outbox pattern solves the Kafka+Postgres dual-write problem:
instead of publishing to the broker *and* writing the database (two systems that
can fail independently), a producer stages an **outbox row** in the *same*
``uow.begin()`` as its DB writes (ADR 0017). The row commits atomically with the
rest of the unit — so an event is never published without its data landing, and
data never lands without its event being queued. A separate **relay**
(`app.outbox_relay`) later publishes the queued envelopes and projects them into
the ``event_log`` (idempotent on ``event_id``); the domain code never touches the
broker inside its transaction.

An entry is just the pairing an outbox row records: the topic the envelope is
bound for and the validated `DomainEvent` itself. It is an append-only, immutable
fact — the relay uses the ``event_log`` as its idempotency ledger rather than
mutating outbox rows, so the entry needs no ``published`` flag.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.event import DomainEvent


@dataclass(frozen=True)
class OutboxEntry:
    topic: str
    event: DomainEvent

    @property
    def event_id(self) -> str:
        """The staged envelope's stable identity — the key the relay dedupes on
        so a replayed or duplicated entry projects into the log only once."""
        return self.event.event_id
