"""Repository ports — the persistence seam.

A repository stores and retrieves a domain aggregate, hiding *how* it is stored.
This is a genuine seam because two implementations vary across it: an in-memory
fake the tests drive, and a Postgres-backed adapter used in production
(`app.repositories`). Callers depend on the port, never on SQLAlchemy or a
connection string.

Two aggregates have a port so far: the being (`BeingRepository`) and, from V0-9,
shadow-mode predictions (`PredictionRecordRepository`). Each real domain record
gets its own port here, added when it is actually needed rather than
speculatively.
"""
from __future__ import annotations

from typing import List, Optional, Protocol

from app.domain.being_state import BeingState
from app.domain.prediction_record import PredictionRecord


class BeingRepository(Protocol):
    """Stores and retrieves beings by id."""

    def save(self, being: BeingState) -> None:
        """Persist ``being``, replacing any existing record with the same id."""
        ...

    def get(self, being_id: str) -> Optional[BeingState]:
        """The stored being with ``being_id``, or ``None`` if there is none."""
        ...


class PredictionRecordRepository(Protocol):
    """Stores shadow-mode prediction records for later comparison (ADR 0011).

    Append-only: each interaction adds one record. The in-memory fake
    (`app.repositories`) is the seam the behavior suite drives; a Postgres-backed
    adapter onto the `prediction_records` table follows with the persistence
    wiring (V0-7)."""

    def add(self, record: PredictionRecord) -> None:
        """Append ``record`` to the store."""
        ...

    def all(self) -> List[PredictionRecord]:
        """Every stored record, oldest first."""
        ...
