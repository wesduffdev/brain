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
from app.domain.belief import Belief
from app.domain.concept import ConceptEvidence, ConceptSchema
from app.domain.interaction_event import InteractionEvent
from app.domain.memory import Memory
from app.domain.model_run import ModelRun
from app.domain.prediction_record import PredictionRecord
from app.domain.similarity import ObjectSimilarityRecord
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


class InMemoryMemoryRepository:
    """A durable-memory store held in a list — the seam the behavior suite
    drives, no database required. Memories are immutable value objects
    (`Memory`), so it stores and returns them directly."""

    def __init__(self) -> None:
        self._memories: List[Memory] = []

    def add(self, memory: Memory) -> None:
        self._memories.append(memory)

    def all(self) -> List[Memory]:
        return list(self._memories)


class PostgresMemoryRepository:
    """A durable-memory store backed by Postgres via a SQLAlchemy ``Session``.
    Append-only, like the event/example/prediction adapters: each interaction
    stages one row on the `memories` table (card v1), and ``all`` reads them back
    oldest-first as immutable `Memory` value objects. The row links to the
    interaction it was formed from by ``event_id`` (``being:tick``)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, memory: Memory) -> None:
        self._session.add(
            models.Memory(
                event_id=memory.event_id,
                being_id=memory.being_id,
                tick=memory.tick,
                object_id=memory.object_id,
                action=memory.action,
                perceived_properties=list(memory.perceived_properties),
                expected_outcome=list(memory.expected_outcome),
                observed_outcome=list(memory.observed_outcome),
                emotion_before=memory.emotion_before,
                emotion_after=memory.emotion_after,
                prediction_error=memory.prediction_error,
                priority=memory.priority,
            )
        )

    def all(self) -> List[Memory]:
        rows = self._session.query(models.Memory).order_by(models.Memory.id).all()
        return [
            Memory(
                being_id=row.being_id,
                tick=row.tick,
                object_id=row.object_id,
                action=row.action,
                perceived_properties=tuple(row.perceived_properties or ()),
                expected_outcome=tuple(row.expected_outcome or ()),
                observed_outcome=tuple(row.observed_outcome or ()),
                emotion_before=row.emotion_before,
                emotion_after=row.emotion_after,
                prediction_error=row.prediction_error or 0.0,
                priority=row.priority or 0.0,
            )
            for row in rows
        ]


def _concept_from_row(row) -> ConceptSchema:
    return ConceptSchema(
        being_id=row.being_id,
        feature=row.feature,
        action=row.action,
        outcome=row.outcome,
        confidence=row.confidence or 0.0,
        evidence_count=row.evidence_count or 0,
    )


class InMemoryConceptRepository:
    """A concept store held in a dict keyed by ``concept_id`` — the seam the
    behavior suite drives, no database required. Concepts are immutable value
    objects that upsert in place (``save`` replaces by id); evidence is kept in an
    append-only list."""

    def __init__(self) -> None:
        self._concepts: Dict[str, ConceptSchema] = {}
        self._evidence: List[ConceptEvidence] = []

    def get(self, concept_id: str) -> Optional[ConceptSchema]:
        return self._concepts.get(concept_id)

    def save(self, concept: ConceptSchema) -> None:
        self._concepts[concept.concept_id] = concept

    def add_evidence(self, evidence: ConceptEvidence) -> None:
        self._evidence.append(evidence)

    def all(self) -> List[ConceptSchema]:
        return list(self._concepts.values())


class PostgresConceptRepository:
    """A concept store backed by Postgres via a SQLAlchemy ``Session``. A concept
    is upserted by ``concept_id`` (``merge``) so its confidence accumulates in
    place across interactions; evidence is appended. Staged only — the caller's
    unit of work commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, concept_id: str) -> Optional[ConceptSchema]:
        row = self._session.get(models.ConceptSchema, concept_id)
        return _concept_from_row(row) if row is not None else None

    def save(self, concept: ConceptSchema) -> None:
        self._session.merge(  # insert-or-update by concept_id, so a concept strengthens in place
            models.ConceptSchema(
                concept_id=concept.concept_id,
                being_id=concept.being_id,
                feature=concept.feature,
                action=concept.action,
                outcome=concept.outcome,
                name=concept.name,
                confidence=concept.confidence,
                evidence_count=concept.evidence_count,
            )
        )

    def add_evidence(self, evidence: ConceptEvidence) -> None:
        self._session.add(
            models.ConceptEvidence(
                concept_id=evidence.concept_id,
                event_id=evidence.event_id,
                being_id=evidence.being_id,
                tick=evidence.tick,
                feature=evidence.feature,
                action=evidence.action,
                outcome=evidence.outcome,
            )
        )

    def all(self) -> List[ConceptSchema]:
        rows = self._session.query(models.ConceptSchema).order_by(models.ConceptSchema.concept_id).all()
        return [_concept_from_row(row) for row in rows]


class InMemoryBeliefRepository:
    """An append-only belief store in a list — the test seam, no database.
    Beliefs are immutable value objects, stored and returned directly."""

    def __init__(self) -> None:
        self._beliefs: List[Belief] = []

    def add(self, belief: Belief) -> None:
        self._beliefs.append(belief)

    def all(self) -> List[Belief]:
        return list(self._beliefs)


class PostgresBeliefRepository:
    """A belief store backed by Postgres via a SQLAlchemy ``Session``. Append-only:
    each prediction stages one row on the `beliefs` table. Staged only — the
    caller's unit of work commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, belief: Belief) -> None:
        self._session.add(
            models.Belief(
                being_id=belief.being_id,
                tick=belief.tick,
                object_id=belief.object_id,
                action=belief.action,
                outcome=belief.outcome,
                confidence=belief.confidence,
            )
        )

    def all(self) -> List[Belief]:
        rows = self._session.query(models.Belief).order_by(models.Belief.id).all()
        return [
            Belief(
                being_id=row.being_id,
                tick=row.tick,
                object_id=row.object_id,
                action=row.action,
                outcome=row.outcome,
                confidence=row.confidence or 0.0,
            )
            for row in rows
        ]


class InMemorySimilarityRepository:
    """An append-only object-similarity store in a list — the test seam, no
    database. Records are immutable value objects, stored and returned directly."""

    def __init__(self) -> None:
        self._records: List[ObjectSimilarityRecord] = []

    def add(self, record: ObjectSimilarityRecord) -> None:
        self._records.append(record)

    def all(self) -> List[ObjectSimilarityRecord]:
        return list(self._records)


class PostgresSimilarityRepository:
    """An object-similarity store backed by Postgres via a SQLAlchemy ``Session``.
    Append-only: each comparison stages one row on the `object_similarity_records`
    table. Staged only — the caller's unit of work commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: ObjectSimilarityRecord) -> None:
        self._session.add(
            models.ObjectSimilarityRecord(
                being_id=record.being_id,
                tick=record.tick,
                object_id=record.object_id,
                other_object_id=record.other_object_id,
                similarity=record.similarity,
            )
        )

    def all(self) -> List[ObjectSimilarityRecord]:
        rows = (
            self._session.query(models.ObjectSimilarityRecord)
            .order_by(models.ObjectSimilarityRecord.id)
            .all()
        )
        return [
            ObjectSimilarityRecord(
                being_id=row.being_id,
                tick=row.tick,
                object_id=row.object_id,
                other_object_id=row.other_object_id,
                similarity=row.similarity or 0.0,
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
