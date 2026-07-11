"""Repository ports — the persistence seam.

A repository stores and retrieves a domain aggregate, hiding *how* it is stored.
This is a genuine seam because two implementations vary across it: an in-memory
fake the tests drive, and a Postgres-backed adapter used in production
(`app.repositories`). Callers depend on the port, never on SQLAlchemy or a
connection string.

The being aggregate has a port, `BeingRepository` (V0-7). As the learning loop
produces real records, each gets its own port here, added when it is actually
needed rather than speculatively: `InteractionEventRepository` and
`TrainingExampleRepository` land with the event→example wiring (V0-7b, ADR 0012),
`PredictionRecordRepository` with shadow mode (V0-9, ADR 0011), and
`ModelRunRepository` when the trainer records a run (V0-8b, ADR 0008). Events,
examples, predictions, and model runs are append-only facts, so their ports
`add` and read back, rather than upserting by id like the being's mutable
snapshot.
"""
from __future__ import annotations

from typing import ContextManager, List, Optional, Protocol

from app.domain.being_state import BeingState
from app.domain.interaction_event import InteractionEvent
from app.domain.model_run import ModelRun
from app.domain.prediction_record import PredictionRecord
from app.domain.training_example import TrainingExample


class UnitOfWork(Protocol):
    """A transaction boundary owned by the caller — the atomicity seam.

    Repositories only *stage* writes (``add``/``merge``); the caller groups the
    writes of one logical operation inside ``with uow.begin(): ...`` so they
    persist atomically. A clean exit commits every staged row together; any
    exception rolls the whole unit back, leaving no orphan child rows (ADR 0017).

    Two implementations vary across the seam (`app.db.unit_of_work`): a no-op
    context for the in-memory fakes (no database), and one real transaction over
    a SQLAlchemy ``Session`` for the Postgres path."""

    def begin(self) -> ContextManager[None]:
        """Open one unit of work: a context that commits its staged writes on a
        clean exit and rolls them all back on any exception."""
        ...


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


class PredictionRecordRepository(Protocol):
    """Stores shadow-mode prediction records for later comparison (ADR 0011).

    Append-only: each interaction adds one record. The in-memory fake
    (`app.repositories`) is the seam the behavior suite drives; a Postgres-backed
    adapter onto the `prediction_records` table follows with the persistence
    wiring."""

    def add(self, record: PredictionRecord) -> None:
        """Append ``record`` to the store."""
        ...

    def all(self) -> List[PredictionRecord]:
        """Every stored record, oldest first."""
        ...


class ModelRunRepository(Protocol):
    """Stores training-run metadata (append-only) and reads it back."""

    def add(self, run: ModelRun) -> None:
        """Persist the metadata of one training run."""
        ...

    def all(self) -> List[ModelRun]:
        """Every recorded model run, oldest first."""
        ...
