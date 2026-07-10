"""Repository ports — the persistence seam.

A repository stores and retrieves a domain aggregate, hiding *how* it is stored.
This is a genuine seam because two implementations vary across it: an in-memory
fake the tests drive, and a Postgres-backed adapter used in production
(`app.repositories`). Callers depend on the port, never on SQLAlchemy or a
connection string.

Today the only aggregate that exists is the being, so this defines one port,
`BeingRepository`. As later slices add real domain records — InteractionEvent
and TrainingExample first (V0-4) — each gets its own port here, added when it is
actually needed rather than speculatively.
"""
from __future__ import annotations

from typing import Optional, Protocol

from app.domain.being_state import BeingState


class BeingRepository(Protocol):
    """Stores and retrieves beings by id."""

    def save(self, being: BeingState) -> None:
        """Persist ``being``, replacing any existing record with the same id."""
        ...

    def get(self, being_id: str) -> Optional[BeingState]:
        """The stored being with ``being_id``, or ``None`` if there is none."""
        ...
