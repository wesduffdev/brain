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
from app.domain.concept_graph import GraphEdge, GraphNode
from app.domain.interaction_event import InteractionEvent
from app.domain.memory import Memory
from app.domain.model_run import ModelRun
from app.domain.prediction_record import PredictionRecord
from app.domain.similarity import ObjectSimilarityRecord
from app.domain.training_example import TrainingExample
from app.domain.event import DomainEvent
from app.domain.event_log import EventLogEntry
from app.domain.knowledge import KnowledgeChunk
from app.domain.conversation import ConversationTurn
from app.domain.instinct import (
    InstinctPrediction,
    InstinctReaction,
    InstinctTrainingExample,
)
from app.domain.outbox import OutboxEntry


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


def _node_from_row(row) -> GraphNode:
    return GraphNode(being_id=row.being_id, kind=row.kind, label=row.label)


def _edge_from_row(row) -> GraphEdge:
    return GraphEdge(
        being_id=row.being_id,
        kind=row.kind,
        source_id=row.source_id,
        target_id=row.target_id,
        confidence=row.confidence or 0.0,
        evidence_count=row.evidence_count or 0,
        last_updated_tick=row.last_updated_tick or 0,
        source_memory_ids=tuple(row.source_memory_ids or ()),
    )


class InMemoryGraphRepository:
    """A concept-graph store held in dicts keyed by ``node_id`` / ``edge_id`` — the
    seam the behavior suite drives, no database required. Nodes and edges are
    immutable value objects that upsert in place (``save_*`` replaces by id)."""

    def __init__(self) -> None:
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[str, GraphEdge] = {}

    def save_node(self, node: GraphNode) -> None:
        self._nodes[node.node_id] = node

    def save_edge(self, edge: GraphEdge) -> None:
        self._edges[edge.edge_id] = edge

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        return self._edges.get(edge_id)

    def nodes(self) -> List[GraphNode]:
        return list(self._nodes.values())

    def edges(self) -> List[GraphEdge]:
        return list(self._edges.values())


class PostgresGraphRepository:
    """A concept-graph store backed by Postgres via a SQLAlchemy ``Session``. A
    node is upserted by ``node_id`` and an edge by ``edge_id`` (``merge``), so both
    strengthen in place across interactions; ``get_edge`` reads an edge back so the
    service can reinforce it, and ``nodes``/``edges`` read the whole graph for
    traversal. Staged only — the caller's unit of work commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_node(self, node: GraphNode) -> None:
        self._session.merge(  # insert-or-update by node_id
            models.GraphNode(
                node_id=node.node_id,
                being_id=node.being_id,
                kind=node.kind,
                label=node.label,
            )
        )

    def save_edge(self, edge: GraphEdge) -> None:
        self._session.merge(  # insert-or-update by edge_id, so an edge strengthens in place
            models.GraphEdge(
                edge_id=edge.edge_id,
                being_id=edge.being_id,
                kind=edge.kind,
                source_id=edge.source_id,
                target_id=edge.target_id,
                confidence=edge.confidence,
                evidence_count=edge.evidence_count,
                last_updated_tick=edge.last_updated_tick,
                source_memory_ids=list(edge.source_memory_ids),
            )
        )

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        row = self._session.get(models.GraphEdge, edge_id)
        return _edge_from_row(row) if row is not None else None

    def nodes(self) -> List[GraphNode]:
        rows = self._session.query(models.GraphNode).order_by(models.GraphNode.node_id).all()
        return [_node_from_row(row) for row in rows]

    def edges(self) -> List[GraphEdge]:
        rows = self._session.query(models.GraphEdge).order_by(models.GraphEdge.edge_id).all()
        return [_edge_from_row(row) for row in rows]


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


# --- event backbone: transactional outbox + event-log projection (ADR 0028) ---
#
# The Postgres adapters flatten a `DomainEvent`'s scalar fields into their own
# queryable columns and store its timestamps as the ISO-8601 wire form; on read
# they rebuild the envelope through `DomainEvent.from_snapshot`, which re-validates
# it loudly (a stored row that has lost a field or a valid timestamp is rejected,
# not half-rebuilt) — the same discipline a Kafka consumer uses off the wire.


def _domain_event_columns(event: DomainEvent, topic: str) -> Dict:
    return dict(
        event_id=event.event_id,
        topic=topic,
        event_type=event.event_type,
        event_version=event.event_version,
        being_id=event.being_id,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        source_service=event.source_service,
        occurred_at=event.occurred_at.isoformat(),
        produced_at=event.produced_at.isoformat(),
        payload=dict(event.payload),
    )


def _domain_event_from_row(row) -> DomainEvent:
    return DomainEvent.from_snapshot(
        {
            "eventId": row.event_id,
            "eventType": row.event_type,
            "eventVersion": row.event_version,
            "occurredAt": row.occurred_at,
            "producedAt": row.produced_at,
            "sourceService": row.source_service,
            "beingId": row.being_id,
            "correlationId": row.correlation_id,
            "causationId": row.causation_id,
            "payload": dict(row.payload or {}),
        }
    )


class InMemoryOutboxRepository:
    """An append-only outbox held in a list — the test seam, no database. Entries
    are immutable value objects (`OutboxEntry`), stored and returned directly."""

    def __init__(self) -> None:
        self._entries: List[OutboxEntry] = []

    def add(self, entry: OutboxEntry) -> None:
        self._entries.append(entry)

    def all(self) -> List[OutboxEntry]:
        return list(self._entries)


class PostgresOutboxRepository:
    """An outbox backed by Postgres via a SQLAlchemy ``Session``. Append-only:
    each producer stages one row on the `event_outbox` table inside its unit of
    work (ADR 0017/0028), and ``all`` reads them back oldest-first as `OutboxEntry`
    value objects. Staged only — the caller's unit of work commits it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: OutboxEntry) -> None:
        self._session.add(models.EventOutbox(**_domain_event_columns(entry.event, entry.topic)))

    def all(self) -> List[OutboxEntry]:
        rows = self._session.query(models.EventOutbox).order_by(models.EventOutbox.id).all()
        return [OutboxEntry(topic=row.topic, event=_domain_event_from_row(row)) for row in rows]


class InMemoryEventLogRepository:
    """An event-log projection held in a dict keyed by ``event_id`` — the seam the
    behavior suite drives, no database. ``add`` is idempotent on ``event_id`` (a
    replayed envelope leaves the log at one entry, keeping the first); ``all``
    reads them back in projection order."""

    def __init__(self) -> None:
        self._entries: Dict[str, EventLogEntry] = {}

    def add(self, entry: EventLogEntry) -> None:
        self._entries.setdefault(entry.event_id, entry)  # idempotent on event_id

    def all(self) -> List[EventLogEntry]:
        return list(self._entries.values())


class PostgresEventLogRepository:
    """An event-log projection backed by Postgres via a SQLAlchemy ``Session``.
    ``add`` is idempotent: it ``merge``s by the ``event_id`` primary key, so
    projecting the same envelope twice upserts in place rather than duplicating.
    Staged only — the relay's unit of work commits it (ADR 0017/0028)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: EventLogEntry) -> None:
        self._session.merge(  # insert-or-update by event_id, so replay is idempotent
            models.EventLog(**_domain_event_columns(entry.event, entry.topic))
        )

    def all(self) -> List[EventLogEntry]:
        rows = self._session.query(models.EventLog).order_by(models.EventLog.created_at, models.EventLog.event_id).all()
        return [EventLogEntry(topic=row.topic, event=_domain_event_from_row(row)) for row in rows]


# --- instinct capture: predictions, reactions, derived training rows (ADR 0026) ---


class InMemoryInstinctPredictionRepository:
    """An append-only instinct-prediction store in a list — the test seam, no
    database. Predictions are immutable value objects, stored and returned directly."""

    def __init__(self) -> None:
        self._predictions: List[InstinctPrediction] = []

    def add(self, prediction: InstinctPrediction) -> None:
        self._predictions.append(prediction)

    def all(self) -> List[InstinctPrediction]:
        return list(self._predictions)


class PostgresInstinctPredictionRepository:
    """An instinct-prediction store backed by Postgres via a SQLAlchemy ``Session``.
    Append-only: each inference stages one row on the `instinct_predictions` table.
    Staged only — the caller's unit of work commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, prediction: InstinctPrediction) -> None:
        self._session.add(
            models.InstinctPredictionRecord(
                event_id=prediction.event_id,
                being_id=prediction.being_id,
                tick=prediction.tick,
                features=list(prediction.features),
                reaction_probabilities=list(prediction.reaction_probabilities),
                reaction_intensity=prediction.reaction_intensity,
            )
        )

    def all(self) -> List[InstinctPrediction]:
        rows = (
            self._session.query(models.InstinctPredictionRecord)
            .order_by(models.InstinctPredictionRecord.id)
            .all()
        )
        return [
            InstinctPrediction(
                being_id=row.being_id,
                tick=row.tick,
                event_id=row.event_id,
                features=tuple(row.features or ()),
                reaction_probabilities=tuple(row.reaction_probabilities or ()),
                reaction_intensity=row.reaction_intensity or 0.0,
            )
            for row in rows
        ]


class InMemoryInstinctReactionRepository:
    """An append-only instinct-reaction store in a list — the test seam, no database."""

    def __init__(self) -> None:
        self._reactions: List[InstinctReaction] = []

    def add(self, reaction: InstinctReaction) -> None:
        self._reactions.append(reaction)

    def all(self) -> List[InstinctReaction]:
        return list(self._reactions)


class PostgresInstinctReactionRepository:
    """An instinct-reaction store backed by Postgres via a SQLAlchemy ``Session``.
    Append-only: each reaction decision stages one row on the `instinct_reactions`
    table. Staged only — the caller's unit of work commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, reaction: InstinctReaction) -> None:
        self._session.add(
            models.InstinctReactionRecord(
                event_id=reaction.event_id,
                being_id=reaction.being_id,
                tick=reaction.tick,
                reaction=reaction.reaction,
                intensity=reaction.intensity,
                triggered=reaction.triggered,
            )
        )

    def all(self) -> List[InstinctReaction]:
        rows = (
            self._session.query(models.InstinctReactionRecord)
            .order_by(models.InstinctReactionRecord.id)
            .all()
        )
        return [
            InstinctReaction(
                being_id=row.being_id,
                tick=row.tick,
                event_id=row.event_id,
                reaction=row.reaction,
                intensity=row.intensity or 0.0,
                triggered=bool(row.triggered),
            )
            for row in rows
        ]


class InMemoryInstinctTrainingExampleRepository:
    """An append-only instinct training-example store in a list — the test seam."""

    def __init__(self) -> None:
        self._examples: List[InstinctTrainingExample] = []

    def add(self, example: InstinctTrainingExample) -> None:
        self._examples.append(example)

    def all(self) -> List[InstinctTrainingExample]:
        return list(self._examples)


class PostgresInstinctTrainingExampleRepository:
    """An instinct training-example store backed by Postgres via a SQLAlchemy
    ``Session``. Append-only: each derived row stages on the
    `instinct_training_examples` table. Staged only — the caller's unit of work
    commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, example: InstinctTrainingExample) -> None:
        self._session.add(
            models.InstinctTrainingExampleRecord(
                event_id=example.event_id,
                input_features=list(example.input_features),
                output_labels=list(example.output_labels),
            )
        )

    def all(self) -> List[InstinctTrainingExample]:
        rows = (
            self._session.query(models.InstinctTrainingExampleRecord)
            .order_by(models.InstinctTrainingExampleRecord.id)
            .all()
        )
        return [
            InstinctTrainingExample(
                event_id=row.event_id,
                input_features=tuple(row.input_features or ()),
                output_labels=tuple(row.output_labels or ()),
            )
            for row in rows
        ]


# --- reading: the growing knowledge store (reading R3, ADR 0038) ----------------


class InMemoryKnowledgeChunkRepository:
    """A growing-knowledge store held in a list — the seam the behavior suite
    drives, no database required. Chunks are immutable value objects
    (`KnowledgeChunk`), stored and returned directly; append-only and cumulative."""

    def __init__(self) -> None:
        self._chunks: List[KnowledgeChunk] = []

    def add(self, chunk: KnowledgeChunk) -> None:
        self._chunks.append(chunk)

    def all(self) -> List[KnowledgeChunk]:
        return list(self._chunks)


class PostgresKnowledgeChunkRepository:
    """A growing-knowledge store backed by Postgres via a SQLAlchemy ``Session``.
    Append-only: each ingested document stages its chunks on the `knowledge_chunks`
    table, and ``all`` reads them back oldest-first as immutable `KnowledgeChunk`
    value objects. The `embedding` persists as a JSON float list — pgvector-ready
    (roadmap v11): swapping in a native vector column + ANN index is a change here,
    behind the unchanged port. Staged only — the caller's unit of work commits it
    (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, chunk: KnowledgeChunk) -> None:
        self._session.add(
            models.KnowledgeChunk(
                source=chunk.source,
                text=chunk.text,
                embedding=list(chunk.embedding),
            )
        )

    def all(self) -> List[KnowledgeChunk]:
        rows = (
            self._session.query(models.KnowledgeChunk)
            .order_by(models.KnowledgeChunk.id)
            .all()
        )
        return [
            KnowledgeChunk(
                source=row.source,
                text=row.text,
                embedding=tuple(row.embedding or ()),
            )
            for row in rows
        ]


# --- reading: multi-turn conversation turns (reading R6, extends ADR 0039) ------


class InMemoryConversationTurnRepository:
    """A conversation-turn store held in a list — the seam the behavior suite drives,
    no database required. Turns are immutable value objects (`ConversationTurn`),
    stored and returned directly; append-only and cumulative. `history` filters to one
    conversation, preserving insertion (oldest-first) order."""

    def __init__(self) -> None:
        self._turns: List[ConversationTurn] = []

    def add(self, turn: ConversationTurn) -> None:
        self._turns.append(turn)

    def history(self, conversation_id: str) -> List[ConversationTurn]:
        return [turn for turn in self._turns if turn.conversation_id == conversation_id]


class PostgresConversationTurnRepository:
    """A conversation-turn store backed by Postgres via a SQLAlchemy ``Session``.
    Append-only: each turn stages one row on the `conversation_turns` table, and
    `history` reads one conversation's turns back oldest-first (by insertion id) as
    immutable `ConversationTurn` value objects. Staged only — the caller's unit of
    work commits it (ADR 0017)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, turn: ConversationTurn) -> None:
        self._session.add(
            models.ConversationTurn(
                conversation_id=turn.conversation_id,
                user_message=turn.user_message,
                answer=turn.answer,
            )
        )

    def history(self, conversation_id: str) -> List[ConversationTurn]:
        rows = (
            self._session.query(models.ConversationTurn)
            .filter(models.ConversationTurn.conversation_id == conversation_id)
            .order_by(models.ConversationTurn.id)
            .all()
        )
        return [
            ConversationTurn(
                conversation_id=row.conversation_id,
                user_message=row.user_message,
                answer=row.answer,
            )
            for row in rows
        ]
