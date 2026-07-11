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
from app.domain.belief import Belief
from app.domain.concept import ConceptEvidence, ConceptSchema
from app.domain.concept_graph import GraphEdge, GraphNode
from app.domain.interaction_event import InteractionEvent
from app.domain.memory import Memory
from app.domain.model_run import ModelRun
from app.domain.prediction_record import PredictionRecord
from app.domain.similarity import ObjectSimilarityRecord
from app.domain.training_example import TrainingExample
from app.domain.event_log import EventLogEntry
from app.domain.knowledge import KnowledgeChunk
from app.domain.conversation import ConversationTurn
from app.domain.instinct import (
    InstinctPrediction,
    InstinctReaction,
    InstinctTrainingExample,
)
from app.domain.outbox import OutboxEntry


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


class MemoryRepository(Protocol):
    """Stores the being's durable memories (append-only) and reads them back
    (card v1). One memory is formed per interaction and staged inside that
    interaction's unit of work, so it commits atomically with the
    interaction_event it links to (ADR 0017). Like the other learned-fact ports,
    the in-memory fake (`app.repositories`) is the seam the behavior suite drives;
    a Postgres-backed adapter onto the `memories` table follows for the runtime."""

    def add(self, memory: Memory) -> None:
        """Append ``memory`` to the store."""
        ...

    def all(self) -> List[Memory]:
        """Every stored memory, oldest first."""
        ...


class ConceptRepository(Protocol):
    """Stores the being's CONCEPT SCHEMAS and their evidence (card v2).

    Unlike the append-only learned-fact ports, a concept is *upserted*: it is
    looked up by ``concept_id``, strengthened, and saved back in place as more
    interactions confirm it, so its confidence accumulates rather than duplicating.
    ``add_evidence`` records the append-only trace of the interactions behind a
    concept. Both writes go through the interaction's unit of work (ADR 0017). The
    in-memory fake (`app.repositories`) is the seam the behavior suite drives; a
    Postgres-backed adapter follows for the runtime."""

    def get(self, concept_id: str) -> Optional[ConceptSchema]:
        """The stored concept with ``concept_id``, or ``None`` if there is none."""
        ...

    def save(self, concept: ConceptSchema) -> None:
        """Persist ``concept``, replacing any existing one with the same id."""
        ...

    def add_evidence(self, evidence: ConceptEvidence) -> None:
        """Append one piece of evidence for a concept (append-only)."""
        ...

    def all(self) -> List[ConceptSchema]:
        """Every stored concept."""
        ...


class BeliefRepository(Protocol):
    """Stores the being's per-object BELIEFS (append-only, card v2). Each is a
    prediction inherited from concepts about a perceived object; one is added per
    prediction, inside the interaction's unit of work."""

    def add(self, belief: Belief) -> None:
        """Append ``belief`` to the store."""
        ...

    def all(self) -> List[Belief]:
        """Every stored belief, oldest first."""
        ...


class SimilarityRepository(Protocol):
    """Stores object-similarity records (append-only, card v2): how alike the
    being finds two objects by their perceived properties, laid down as it
    perceives its world."""

    def add(self, record: ObjectSimilarityRecord) -> None:
        """Append ``record`` to the store."""
        ...

    def all(self) -> List[ObjectSimilarityRecord]:
        """Every stored similarity record, oldest first."""
        ...


class GraphRepository(Protocol):
    """Stores the being's CONCEPT GRAPH — its nodes and edges (card v7).

    Both nodes and edges are *upserted*: a node is saved by ``node_id`` and an
    edge by ``edge_id``, so the same object/property/outcome or the same typed
    relationship is strengthened in place across interactions rather than
    duplicated. ``get_edge`` reads an edge's current state so the
    KnowledgeGraphService can reinforce its confidence and evidence; ``nodes`` and
    ``edges`` read the whole graph back for traversal (`ConceptPathService`). All
    writes stage inside the interaction's unit of work (ADR 0017). The in-memory
    fake (`app.repositories`) is the seam the behavior suite drives; a
    Postgres-backed adapter follows for the runtime."""

    def save_node(self, node: GraphNode) -> None:
        """Persist ``node``, replacing any existing one with the same ``node_id``."""
        ...

    def save_edge(self, edge: GraphEdge) -> None:
        """Persist ``edge``, replacing any existing one with the same ``edge_id``."""
        ...

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        """The stored edge with ``edge_id``, or ``None`` if there is none."""
        ...

    def nodes(self) -> List[GraphNode]:
        """Every stored node."""
        ...

    def edges(self) -> List[GraphEdge]:
        """Every stored edge."""
        ...


class OutboxRepository(Protocol):
    """Stages domain events for atomic publication — the transactional-outbox seam
    (ADR 0028). ``add`` stages one `OutboxEntry` inside the *same* unit of work as
    the DB writes it accompanies (ADR 0017), so the event queues atomically with
    its data; ``all`` reads the queue back for the relay to drain. Append-only:
    the relay (`app.outbox_relay`) treats the ``event_log`` as its idempotency
    ledger rather than mutating outbox rows, so there is no ``published`` state to
    flip here. The in-memory fake (`app.repositories`) is the seam the behavior
    suite drives; a Postgres-backed adapter follows for the runtime."""

    def add(self, entry: OutboxEntry) -> None:
        """Stage one outbox entry, to commit with the current unit of work."""
        ...

    def all(self) -> List[OutboxEntry]:
        """Every staged outbox entry, oldest first."""
        ...


class EventLogRepository(Protocol):
    """Stores the durable projection of published domain events (ADR 0028).

    ``add`` is **idempotent on ``event_id``**: projecting the same envelope twice
    leaves the log at one entry, which is what lets the relay use the log as its
    delivery ledger. ``all`` reads the log back (the relay reads it to know which
    events are already delivered, and callers query it as the audit trail). The
    in-memory fake (`app.repositories`) is the seam the behavior suite drives; a
    Postgres-backed adapter follows for the runtime."""

    def add(self, entry: EventLogEntry) -> None:
        """Project one event into the log, idempotent on its ``event_id``."""
        ...

    def all(self) -> List[EventLogEntry]:
        """Every logged event, oldest first."""
        ...


class InstinctPredictionRepository(Protocol):
    """Stores per-stimulus instinct inferences (append-only, ADR 0026) and reads
    them back — one row per prediction the instinct model makes."""

    def add(self, prediction: InstinctPrediction) -> None:
        """Append one instinct prediction to the store."""
        ...

    def all(self) -> List[InstinctPrediction]:
        """Every stored prediction, oldest first."""
        ...


class InstinctReactionRepository(Protocol):
    """Stores the reactions the being had to stimuli (append-only, ADR 0026):
    which reaction, at what intensity, triggered or suppressed."""

    def add(self, reaction: InstinctReaction) -> None:
        """Append one instinct reaction to the store."""
        ...

    def all(self) -> List[InstinctReaction]:
        """Every stored reaction, oldest first."""
        ...


class InstinctTrainingExampleRepository(Protocol):
    """Stores model-ready instinct training rows (append-only, ADR 0026): the
    stimulus features paired with the observed reaction labels, for the trainer."""

    def add(self, example: InstinctTrainingExample) -> None:
        """Append one instinct training example to the store."""
        ...

    def all(self) -> List[InstinctTrainingExample]:
        """Every stored instinct training example, oldest first."""
        ...


class KnowledgeChunkRepository(Protocol):
    """Stores the being's GROWING KNOWLEDGE STORE — the embedded passages of every
    document it has read (reading R3, ADR 0038). Append-only and CUMULATIVE, like
    the other learned-fact ports: each ingested document `add`s its chunks (staged
    in one unit of work, ADR 0017) and never replaces what came before, and `all`
    reads them back for a retrieval to rank. The in-memory fake (`app.repositories`)
    is the seam the behavior suite drives; a Postgres-backed adapter onto the
    `knowledge_chunks` table serves the runtime (pgvector-ready — roadmap v11)."""

    def add(self, chunk: KnowledgeChunk) -> None:
        """Append one embedded passage to the store."""
        ...

    def all(self) -> List[KnowledgeChunk]:
        """Every stored passage, oldest first."""
        ...


class ConversationTurnRepository(Protocol):
    """Stores the turns of the being's MULTI-TURN conversations about what it has READ
    (reading R6, extends ADR 0039). Append-only and CUMULATIVE, like the other
    learned-fact ports: each turn (`add`) is one exchange kept so later turns can
    resolve references to earlier ones, staged in one unit of work (ADR 0017), and
    never replaces what came before. `history` reads back ONE conversation's turns,
    oldest-first, so the conversation is durable across turns and beings can hold
    several at once. The in-memory fake (`app.repositories`) is the seam the behavior
    suite drives; a Postgres-backed adapter onto the `conversation_turns` table serves
    the runtime."""

    def add(self, turn: ConversationTurn) -> None:
        """Append one conversation turn to the store."""
        ...

    def history(self, conversation_id: str) -> List[ConversationTurn]:
        """Every stored turn of ``conversation_id``, oldest first."""
        ...
