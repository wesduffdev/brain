"""Repository adapters — the two implementations behind the persistence port.

`InMemoryBeingRepository` is a dict-backed fake with real store behavior (copies
in and out so callers can never alias the stored record); it is the seam the
behavior suite drives and needs no database. `PostgresBeingRepository` maps the
same port onto the SQLAlchemy ORM over a live session.

Both satisfy `app.ports.repositories.BeingRepository`. The event, training-
example, and model-run adapters (V0-7b/V0-8b, ADR 0012/0008) follow the same
shape behind their own ports; events, examples, and runs are append-only, so
those adapters `add` and read back rather than upserting by id. The Simulation
writes through the event/example ports as it runs; the trainer writes through the
model-run port. Neither caller touches the ORM.

Persistence is transactional *by unit of work* (ADR 0017): every Postgres adapter
only **stages** its write (``session.add``/``merge``) and never commits — the
caller opens one transaction per logical operation through the `UnitOfWork` seam
(`app.db.unit_of_work`), so an operation's rows commit together or roll back
together. An adapter that self-committed would break that atomicity.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.db import models
from app.db.models import Being
from app.domain.being_state import BeingState
from app.domain.interaction_event import InteractionEvent
from app.domain.model_run import ModelRun
from app.domain.prediction_record import PredictionRecord
from app.domain.training_example import TrainingExample


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


class PostgresPredictionRecordRepository:
    """A shadow-mode prediction store backed by Postgres via a SQLAlchemy
    ``Session``. Append-only, like the event/example adapters: each interaction
    adds one row on the `prediction_records` table (ADR 0011), and ``all`` reads
    them back oldest-first as immutable `PredictionRecord` value objects. The row
    links to the interaction it shadowed by ``event_id`` (``being:tick``)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: PredictionRecord) -> None:
        self._session.add(
            models.PredictionRecord(
                event_id=f"{record.being_id}:{record.tick}",
                being_id=record.being_id,
                tick=record.tick,
                object_id=record.object_id,
                action=record.action,
                predicted=list(record.model_outcome),
                probabilities=dict(record.probabilities),
                rule_expected=list(record.rule_expected),
                actual=list(record.actual_observed),
                correct=record.correct,
                prediction_error=record.prediction_error,
            )
        )

    def all(self) -> List[PredictionRecord]:
        rows = (
            self._session.query(models.PredictionRecord)
            .order_by(models.PredictionRecord.id)
            .all()
        )
        return [
            PredictionRecord(
                being_id=row.being_id,
                tick=row.tick,
                object_id=row.object_id,
                action=row.action,
                probabilities=dict(row.probabilities or {}),
                model_outcome=tuple(row.predicted or ()),
                rule_expected=tuple(row.rule_expected or ()),
                actual_observed=tuple(row.actual or ()),
                correct=bool(row.correct),
                prediction_error=row.prediction_error or 0.0,
            )
            for row in rows
        ]


class PostgresBeingRepository:
    """A being store backed by Postgres via a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, being: BeingState) -> None:
        self._session.merge(  # insert-or-update by primary key
            Being(being_id=being.being_id, needs=dict(being.needs), emotion=being.emotion)
        )

    def get(self, being_id: str) -> Optional[BeingState]:
        row = self._session.get(Being, being_id)
        if row is None:
            return None
        return BeingState(being_id=row.being_id, needs=dict(row.needs), emotion=row.emotion)


def _event_from_row(row) -> InteractionEvent:
    return InteractionEvent(
        being_id=row.being_id,
        tick=row.tick,
        object_id=row.object_id,
        action=row.action,
        expected_outcome=tuple(row.expected_outcome or ()),
        observed_outcome=tuple(row.observed_outcome or ()),
        emotion_before=row.emotion_before,
        emotion_after=row.emotion_after,
    )


class InMemoryInteractionEventRepository:
    """An append-only event store in a list — the test seam, no database."""

    def __init__(self) -> None:
        self._events: List[InteractionEvent] = []

    def add(self, event: InteractionEvent) -> None:
        self._events.append(event)

    def all(self) -> List[InteractionEvent]:
        return list(self._events)


class PostgresInteractionEventRepository:
    """An interaction-event store backed by Postgres via a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: InteractionEvent) -> None:
        self._session.merge(  # insert-or-update by event_id, so re-runs are idempotent
            models.InteractionEvent(
                event_id=event.event_id,
                being_id=event.being_id,
                object_id=event.object_id,
                action=event.action,
                expected_outcome=list(event.expected_outcome),
                observed_outcome=list(event.observed_outcome),
                emotion_before=event.emotion_before,
                emotion_after=event.emotion_after,
                tick=event.tick,
            )
        )

    def all(self) -> List[InteractionEvent]:
        rows = (
            self._session.query(models.InteractionEvent)
            .order_by(models.InteractionEvent.tick, models.InteractionEvent.event_id)
            .all()
        )
        return [_event_from_row(row) for row in rows]


class InMemoryTrainingExampleRepository:
    """An append-only training-example store in a list — the test seam."""

    def __init__(self) -> None:
        self._examples: List[TrainingExample] = []

    def add(self, example: TrainingExample) -> None:
        self._examples.append(example)

    def all(self) -> List[TrainingExample]:
        return list(self._examples)


class PostgresTrainingExampleRepository:
    """A training-example store backed by Postgres via a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, example: TrainingExample) -> None:
        self._session.add(
            models.TrainingExample(
                event_id=example.event_id,
                input_features=list(example.input_features),
                output_labels=list(example.output_labels),
            )
        )

    def all(self) -> List[TrainingExample]:
        rows = (
            self._session.query(models.TrainingExample)
            .order_by(models.TrainingExample.id)
            .all()
        )
        return [
            TrainingExample(
                event_id=row.event_id,
                input_features=tuple(row.input_features or ()),
                output_labels=tuple(row.output_labels or ()),
            )
            for row in rows
        ]


class InMemoryModelRunRepository:
    """An append-only model-run store in a list — the test seam, no database."""

    def __init__(self) -> None:
        self._runs: List[ModelRun] = []

    def add(self, run: ModelRun) -> None:
        self._runs.append(run)

    def all(self) -> List[ModelRun]:
        return list(self._runs)


class PostgresModelRunRepository:
    """A model-run store backed by Postgres via a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: ModelRun) -> None:
        self._session.add(
            models.ModelRun(
                artifact_path=run.artifact_path,
                metrics=dict(run.metrics),
                finished_at=run.finished_at,
            )
        )

    def all(self) -> List[ModelRun]:
        rows = self._session.query(models.ModelRun).order_by(models.ModelRun.id).all()
        return [
            ModelRun(
                artifact_path=row.artifact_path,
                finished_at=row.finished_at,
                metrics=dict(row.metrics or {}),
            )
            for row in rows
        ]
