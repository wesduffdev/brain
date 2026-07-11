"""The outbox relay — publish staged events, then project them, exactly once.

The transactional outbox (ADR 0028) splits atomic event publication into two
steps that never share a transaction. Producers stage an `OutboxEntry` in the
same unit of work as their DB writes (ADR 0017); this relay is the second step:
it drains the outbox, publishes each envelope through the `EventPublisher` port,
and records it in the ``event_log``.

`drain_outbox` is deliberately small and hides the two rules that make the
pattern correct:

- **Publication happens outside any DB transaction.** A broker call is never made
  inside the unit that staged the outbox row — that is the whole point of the
  outbox, and a hang or failure on the broker must not hold a database
  transaction open.
- **Projection is idempotent, and the log is the delivery ledger.** The
  ``event_log`` is keyed on ``event_id``, so an event already logged is neither
  re-published nor re-logged. Delivery is therefore at-least-once with an
  idempotent projection: if the process dies after publishing but before the log
  write commits, the next drain re-publishes and the log still ends at one row.

The relay depends only on the ports (`app.ports.repositories`,
`app.ports.events`), so it runs on the in-memory fakes + a fake publisher with no
broker and no database, and unchanged against Postgres + Kafka.
"""
from __future__ import annotations

from typing import Optional

from app.db.unit_of_work import NullUnitOfWork
from app.domain.event_log import EventLogEntry
from app.ports.events import EventPublisher
from app.ports.repositories import EventLogRepository, OutboxRepository, UnitOfWork


def drain_outbox(
    *,
    outbox: OutboxRepository,
    event_log: EventLogRepository,
    publisher: EventPublisher,
    unit_of_work: Optional[UnitOfWork] = None,
) -> int:
    """Publish each not-yet-projected outbox entry and project it into the event
    log, exactly once. Returns the number of entries drained (newly published).

    Each projection write goes through one unit of work (ADR 0017): a no-op for
    the in-memory path, one committed transaction per row for Postgres. The
    ``publish`` call is made *before* opening that unit, so it never runs inside a
    DB transaction."""
    uow = unit_of_work or NullUnitOfWork()
    already_logged = {entry.event_id for entry in event_log.all()}
    drained = 0
    for entry in outbox.all():
        if entry.event_id in already_logged:
            continue
        publisher.publish(entry.topic, entry.event)  # never inside a DB transaction
        with uow.begin():
            event_log.add(EventLogEntry(topic=entry.topic, event=entry.event))
        already_logged.add(entry.event_id)
        drained += 1
    return drained
