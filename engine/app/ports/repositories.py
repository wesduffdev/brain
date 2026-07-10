"""Repository ports — the persistence seam.

A repository stores and retrieves a domain aggregate, hiding *how* it is stored.
This is a genuine seam because two implementations vary across it: an in-memory
fake the tests drive, and a Postgres-backed adapter used in production
(`app.repositories`). Callers depend on the port, never on SQLAlchemy or a
connection string.

The being aggregate has a port, `BeingRepository` (V0-7). As the learning loop
produces real records, each gets its own port here, added when it is actually
needed rather than speculatively: `InteractionEventRepository` and
`TrainingExampleRepository` land with the event→example wiring (V0-7b, ADR 0012).
Events and examples are append-only facts, so their ports `add` and read back,
rather than upserting by id like the being's mutable snapshot.
"""
from __future__ import annotations

from typing import List, Optional, Protocol

from app.domain.being_state import BeingState
from app.domain.interaction_event import InteractionEvent
from app.domain.training_example import TrainingExample


class BeingRepository(Protocol):
    """Stores and retrieves beings by id."""

    def save(self, being: BeingState) -> None:
        """Persist ``being``, replacing any existing record with the same id."""
        ...

    def get(self, being_id: str) -> Optional[BeingState]:
        """The stored being with ``being_id``, or ``None`` if there is none."""
        ...


class InteractionEventRepository(Protocol):
    """Stores interaction events (append-only) and reads them back."""

    def add(self, event: InteractionEvent) -> None:
        """Persist one interaction event, keyed by its ``event_id``."""
        ...

    def all(self) -> List[InteractionEvent]:
        """Every stored event, oldest first."""
        ...


class TrainingExampleRepository(Protocol):
    """Stores training examples (append-only) and reads them back."""

    def add(self, example: TrainingExample) -> None:
        """Persist one training example derived from an interaction event."""
        ...

    def all(self) -> List[TrainingExample]:
        """Every stored training example, oldest first."""
        ...
