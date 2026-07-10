"""Repository adapters — the two implementations behind the persistence port.

`InMemoryBeingRepository` is a dict-backed fake with real store behavior (copies
in and out so callers can never alias the stored record); it is the seam the
behavior suite drives and needs no database. `PostgresBeingRepository` maps the
same port onto the SQLAlchemy ORM over a live session.

Both satisfy `app.ports.repositories.BeingRepository`. Nothing writes beings
into the tick loop yet — this delivers the seam; wiring events through it waits
for V0-4, when InteractionEvents first exist.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Being
from app.domain.being_state import BeingState
from app.domain.prediction_record import PredictionRecord


def _copy(being: BeingState) -> BeingState:
    """A detached copy: a fresh needs dict so the store and the caller never
    share mutable state."""
    return BeingState(being_id=being.being_id, needs=dict(being.needs), emotion=being.emotion)


class InMemoryBeingRepository:
    """A being store held in a dict — the test seam, no database required."""

    def __init__(self) -> None:
        self._beings: Dict[str, BeingState] = {}

    def save(self, being: BeingState) -> None:
        self._beings[being.being_id] = _copy(being)

    def get(self, being_id: str) -> Optional[BeingState]:
        stored = self._beings.get(being_id)
        return _copy(stored) if stored is not None else None


class InMemoryPredictionRecordRepository:
    """A shadow-mode prediction store held in a list — the seam the behavior
    suite drives, no database required. Records are immutable value objects
    (`PredictionRecord`), so it stores and returns them directly."""

    def __init__(self) -> None:
        self._records: List[PredictionRecord] = []

    def add(self, record: PredictionRecord) -> None:
        self._records.append(record)

    def all(self) -> List[PredictionRecord]:
        return list(self._records)


class PostgresBeingRepository:
    """A being store backed by Postgres via a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, being: BeingState) -> None:
        self._session.merge(  # insert-or-update by primary key
            Being(being_id=being.being_id, needs=dict(being.needs), emotion=being.emotion)
        )
        self._session.commit()

    def get(self, being_id: str) -> Optional[BeingState]:
        row = self._session.get(Being, being_id)
        if row is None:
            return None
        return BeingState(being_id=row.being_id, needs=dict(row.needs), emotion=row.emotion)
