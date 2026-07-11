"""Unit of work — the two implementations behind the transaction-boundary seam.

Persistence is transactional *by unit of work* (ADR 0017): the repository
adapters only stage writes, and the caller opens one transaction per logical
operation through this seam. That keeps an interaction's rows — its
``interaction_event``, the derived ``training_example``, the ``prediction_record``
— committing together, and rolls the whole unit back on a mid-unit failure so no
orphan child row is ever left behind.

`NullUnitOfWork` is the in-memory context the behavior suite drives: a
transparent no-op, because the in-memory fakes apply each write as it happens and
there is no database transaction to open. `SessionUnitOfWork` opens one real
``session.begin()`` transaction over a live SQLAlchemy ``Session``.

Both satisfy `app.ports.repositories.UnitOfWork`. Callers depend on that port,
never on SQLAlchemy — the in-memory path needs no database, and the ORM never
leaks above the seam. This generalizes the resource-lifecycle ownership ADR 0016
introduced (`BuiltSimulation.close`): 0016 owns *when the session closes*, 0017
owns *when its writes commit*.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # import only for typing — the in-memory path needs no SQLAlchemy
    from sqlalchemy.orm import Session


class NullUnitOfWork:
    """The in-memory unit of work: a transparent no-op context.

    The in-memory repositories apply each ``add``/``merge`` as it happens, so
    there is no transaction to open — the ``with`` block only *groups* the writes
    of one logical operation structurally. It never swallows an error raised
    inside it. This is the seam the behavior suite drives with no database."""

    @contextmanager
    def begin(self) -> Iterator[None]:
        yield


class SessionUnitOfWork:
    """One database transaction per logical operation, over a SQLAlchemy session.

    ``begin()`` opens a ``session.begin()`` transaction that commits every staged
    write on a clean exit and rolls the whole unit back on any exception — so an
    operation's rows persist atomically or not at all. Postgres runs at its
    default READ COMMITTED isolation, which is sufficient for the single-writer
    simulation (ADR 0017).

    A read between units (e.g. a repository's ``all()``) autobegins its own,
    read-only, transaction on the session; that is ended before the next unit so
    ``session.begin()`` starts from a clean state. Because every write happens
    inside a unit, nothing uncommitted is ever discarded by that reset."""

    def __init__(self, session: "Session") -> None:
        self._session = session

    @contextmanager
    def begin(self) -> Iterator[None]:
        if self._session.in_transaction():
            # End a transaction autobegun by a prior read so begin() starts clean.
            self._session.rollback()
        with self._session.begin():
            yield
