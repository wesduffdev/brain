"""SQLAlchemy models — the v0 database schema (BRIEF §15).

Seven tables, kept deliberately small, hold the simulation's dynamic and learned
data (BRIEF §8: Postgres is for learned/dynamic data, not authored config):

- ``beings``              — being identity and current snapshot.
- ``objects``             — object definitions and known developer data.
- ``interaction_events``  — meaningful events (written from V0-4 onward).
- ``training_examples``   — model-ready rows derived from events.
- ``prediction_records``  — model predictions, for comparison against actuals.
- ``model_runs``          — training-run metadata.
- ``memories``            — durable per-interaction memories with a salience.
- ``concept_schemas``     — learned generalizations keyed on a perceived property.
- ``concept_evidence``    — append-only interactions that reinforced a concept.
- ``beliefs``             — per-object predictions inherited from concepts.
- ``object_similarity_records`` — perceived-property similarity between objects.
- ``graph_nodes``         — object/property/outcome nodes of the concept graph.
- ``graph_edges``         — typed, confidence-bearing edges of the concept graph.
- ``event_outbox``        — domain events staged for atomic publication (ADR 0028).
- ``event_log``           — the durable, idempotent projection of published events.
- ``instinct_predictions``       — per-stimulus instinct inferences (ADR 0026).
- ``instinct_reactions``         — the reaction triggered/suppressed per stimulus.
- ``instinct_training_examples`` — model-ready instinct rows for training.
- ``knowledge_chunks``    — embedded passages of the growing knowledge store (R3).

These are the *schema*, not the interface. Callers persist and read through the
repository port (`app.ports.repositories`); the ORM is an implementation detail
of the Postgres adapter. Classic ``Column`` declarative style is used so the
models resolve cleanly under ``from __future__ import annotations`` on the
supported Python versions.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Being(Base):
    """A being's identity and last-known snapshot (BRIEF §9 BeingState)."""

    __tablename__ = "beings"

    being_id = Column(String, primary_key=True)
    needs = Column(JSON, nullable=False, default=dict)
    emotion = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ObjectRecord(Base):
    """An object's true definition (BRIEF §9 ObjectEntity). ``developer_label``
    is human-only metadata the being never perceives (ADR 0002)."""

    __tablename__ = "objects"

    object_id = Column(String, primary_key=True)
    developer_label = Column(String, nullable=False, default="")
    properties = Column(JSON, nullable=False, default=list)
    affordances = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InteractionEvent(Base):
    """A meaningful event: an action on an object with expected vs. observed
    outcome and the emotion around it (BRIEF §9). Not written until V0-4."""

    __tablename__ = "interaction_events"

    event_id = Column(String, primary_key=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=False, index=True)
    object_id = Column(String, ForeignKey("objects.object_id"), nullable=True, index=True)
    action = Column(String, nullable=False)
    expected_outcome = Column(JSON, nullable=False, default=list)
    observed_outcome = Column(JSON, nullable=False, default=list)
    emotion_before = Column(String, nullable=True)
    emotion_after = Column(String, nullable=True)
    prediction_error = Column(Float, nullable=True)
    tick = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TrainingExample(Base):
    """A model-ready row derived from an interaction event (BRIEF §9)."""

    __tablename__ = "training_examples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, ForeignKey("interaction_events.event_id"), nullable=True, index=True)
    input_features = Column(JSON, nullable=False, default=dict)
    output_labels = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PredictionRecord(Base):
    """A model prediction recorded for later comparison against the actual
    outcome (shadow mode, BRIEF §11, ADR 0011).

    Columns mirror the domain `PredictionRecord` so a stored row round-trips:
    ``predicted`` holds the thresholded model outcome, ``probabilities`` the raw
    per-label probabilities, ``rule_expected`` what the rule layer expected, and
    ``actual`` what was observed; ``correct``/``prediction_error`` are the
    exact-match verdict and the continuous error. ``event_id`` links back to the
    interaction it shadowed (``being:tick``); ``model_run_id`` is unset until a
    trained run owns the prediction."""

    __tablename__ = "prediction_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, ForeignKey("interaction_events.event_id"), nullable=True, index=True)
    model_run_id = Column(Integer, ForeignKey("model_runs.id"), nullable=True, index=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    tick = Column(Integer, nullable=True)
    object_id = Column(String, ForeignKey("objects.object_id"), nullable=True, index=True)
    action = Column(String, nullable=True)
    predicted = Column(JSON, nullable=False, default=list)
    probabilities = Column(JSON, nullable=False, default=dict)
    rule_expected = Column(JSON, nullable=False, default=list)
    actual = Column(JSON, nullable=True)
    correct = Column(Boolean, nullable=True)
    prediction_error = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ModelRun(Base):
    """Metadata for one training run; the weights live in a ``.pt`` artifact on
    disk, this row tracks where and how well (BRIEF §8, §11)."""

    __tablename__ = "model_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    artifact_path = Column(String, nullable=True)
    metrics = Column(JSON, nullable=False, default=dict)
    notes = Column(String, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)


class Memory(Base):
    """A durable memory of one interaction (card v1): the object as the being
    PERCEIVED it, the action, expected vs. observed outcome, emotion before/after,
    the prediction error the moment carried, and a config-driven ``priority``
    (salience). ``event_id`` links back to the interaction_event it was formed
    from (``being:tick``); the row is written inside that interaction's unit of
    work so it commits atomically with the event (ADR 0017). ``perceived_properties``
    is the being's view of the object — there is deliberately no developer_label
    (ADR 0002)."""

    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, ForeignKey("interaction_events.event_id"), nullable=True, index=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    tick = Column(Integer, nullable=True)
    object_id = Column(String, ForeignKey("objects.object_id"), nullable=True, index=True)
    action = Column(String, nullable=True)
    perceived_properties = Column(JSON, nullable=False, default=list)
    expected_outcome = Column(JSON, nullable=False, default=list)
    observed_outcome = Column(JSON, nullable=False, default=list)
    emotion_before = Column(String, nullable=True)
    emotion_after = Column(String, nullable=True)
    prediction_error = Column(Float, nullable=True)
    priority = Column(Float, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConceptSchema(Base):
    """A learned generalization (card v2): the being perceives ``feature`` (a
    property, never a developer_label — ADR 0002), takes ``action``, and observes
    ``outcome``, with a ``confidence`` that rises as ``evidence_count`` interactions
    confirm it. ``concept_id`` (``being|feature|action|outcome``) is the primary
    key, so a concept is upserted in place as it strengthens rather than appended.
    Keyed on perception alone — there is deliberately no developer_label column."""

    __tablename__ = "concept_schemas"

    concept_id = Column(String, primary_key=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    feature = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    name = Column(String, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    evidence_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConceptEvidence(Base):
    """One interaction's contribution to a concept (card v2), append-only. Links
    the ``interaction_events`` row it was formed from (``being:tick``) — the
    enforced cross-aggregate FK — to the concept it reinforced, so a concept is
    always reconcilable to the lived experiences behind it. Written inside the
    interaction's unit of work, so it commits atomically with the event it
    references (ADR 0017).

    ``concept_id`` is a plain indexed logical link to ``concept_schemas`` (its own
    aggregate), deliberately *not* a DB foreign key: the concept and its evidence
    are staged together in one unit and a natural-key FK between them only forces a
    brittle intra-unit insert ordering without adding integrity the unit does not
    already guarantee."""

    __tablename__ = "concept_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    concept_id = Column(String, nullable=False, index=True)
    event_id = Column(String, ForeignKey("interaction_events.event_id"), nullable=True, index=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    tick = Column(Integer, nullable=True)
    feature = Column(String, nullable=False)
    action = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Belief(Base):
    """A per-object prediction inherited from concepts (card v2), append-only: the
    being expects ``action`` on ``object_id`` to produce ``outcome`` with
    ``confidence``, formed purely from the object's PERCEIVED properties so a
    never-seen object inherits an expectation. ``object_id`` is perception-scoped
    (no FK): a belief may concern any perceived object, catalogued or not."""

    __tablename__ = "beliefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    tick = Column(Integer, nullable=True)
    object_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ObjectSimilarityRecord(Base):
    """How similar the being finds two objects by their PERCEIVED properties (card
    v2), append-only. ``similarity`` is in ``[0, 1]``. Object ids are
    perception-scoped (no FK) — the record is a signal about what the being
    senses, not a catalog relationship."""

    __tablename__ = "object_similarity_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    tick = Column(Integer, nullable=True)
    object_id = Column(String, nullable=True, index=True)
    other_object_id = Column(String, nullable=True, index=True)
    similarity = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GraphNode(Base):
    """One node of the being's CONCEPT GRAPH (card v7): a ``kind``
    (OBJECT/PROPERTY/OUTCOME) and the perceived ``label`` it stands for.
    ``node_id`` (``being|kind|label``) is the primary key, so a node the being
    meets again is upserted in place rather than duplicated. Keyed on perceived
    tokens — there is deliberately no developer_label column (ADR 0002)."""

    __tablename__ = "graph_nodes"

    node_id = Column(String, primary_key=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    kind = Column(String, nullable=False, index=True)
    label = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GraphEdge(Base):
    """One typed, directed edge of the concept graph (card v7): a ``kind``
    (``HAS_PROPERTY``/``PREDICTS``/``PRODUCED``/``SIMILAR_TO``) from ``source_id``
    to ``target_id`` (graph_node ids), with a ``confidence`` that rises as
    ``evidence_count`` interactions confirm it, the ``last_updated_tick`` it last
    strengthened, and ``source_memory_ids`` — the interactions (``being:tick``)
    behind it, so the edge is reconcilable to the memories that formed it (card
    v1). ``edge_id`` (``being|kind|source|target``) is the primary key, so an edge
    strengthens in place across interactions.

    ``source_id``/``target_id`` are plain indexed logical links to
    ``graph_nodes`` (its own aggregate), deliberately *not* DB foreign keys: node
    and edge are staged together in one unit of work, and a natural-key FK between
    them only forces a brittle intra-unit insert ordering without adding integrity
    the unit does not already guarantee (the same reasoning as
    ``concept_evidence.concept_id``, ADR 0019)."""

    __tablename__ = "graph_edges"

    edge_id = Column(String, primary_key=True)
    being_id = Column(String, ForeignKey("beings.being_id"), nullable=True, index=True)
    kind = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False, index=True)
    target_id = Column(String, nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    evidence_count = Column(Integer, nullable=False, default=0)
    last_updated_tick = Column(Integer, nullable=True)
    source_memory_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# --- event backbone: transactional outbox + durable log projection (ADR 0028) ---
#
# FK discipline (like ``beliefs`` and ``concept_evidence.concept_id``, ADR 0019):
# an event is a self-contained, replayable *fact*, not a catalog relationship, so
# ``being_id`` here is a plain **indexed** column, not a DB foreign key. Coupling
# the log's separate-unit projection write to the ``beings`` catalog would force a
# brittle cross-unit insert ordering without adding integrity the envelope's own
# ``event_id`` identity does not already carry. Envelope timestamps are stored as
# ISO-8601 strings (the same wire form ``DomainEvent.snapshot`` uses), so an event
# round-trips through ``from_snapshot`` re-validation identically off any dialect.


class EventOutbox(Base):
    """A domain event staged for publication, committed in the *same* unit of work
    as the DB writes it accompanies (ADR 0017/0028) — the producer half of the
    transactional outbox. Append-only: the relay (`app.outbox_relay`) drains it
    and uses the ``event_log`` as its idempotency ledger, so no ``published`` flag
    is mutated here. The scalar envelope fields are kept queryable; ``payload`` is
    the free-form body and ``occurred_at``/``produced_at`` are ISO-8601 strings."""

    __tablename__ = "event_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False, index=True)
    topic = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    event_version = Column(Integer, nullable=False, default=1)
    being_id = Column(String, nullable=True, index=True)
    correlation_id = Column(String, nullable=True, index=True)
    causation_id = Column(String, nullable=True)
    source_service = Column(String, nullable=True)
    occurred_at = Column(String, nullable=False)
    produced_at = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EventLog(Base):
    """The durable projection of every published domain event (ADR 0028) — the
    consumer/relay half of the outbox. ``event_id`` is the primary key, so the
    projection is **idempotent**: a replayed or duplicated envelope upserts in
    place and the log never grows a second row for it. Stores the full envelope so
    the log is replayable, with the scalar fields queryable in their own columns."""

    __tablename__ = "event_log"

    event_id = Column(String, primary_key=True)
    topic = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    event_version = Column(Integer, nullable=False, default=1)
    being_id = Column(String, nullable=True, index=True)
    correlation_id = Column(String, nullable=True, index=True)
    causation_id = Column(String, nullable=True)
    source_service = Column(String, nullable=True)
    occurred_at = Column(String, nullable=False)
    produced_at = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- instinct capture: predictions, reactions, and derived training rows --------
#
# ``event_id`` on each is the id of the perception/approach ``DomainEvent`` that
# prompted the instinct (ADR 0024/0026/0027), which lives on the event backbone
# rather than in ``interaction_events`` — so it is a plain indexed link, not a DB
# foreign key (the outcome model's ``training_examples.event_id`` FK points at
# ``interaction_events`` and would be the wrong parent here).


class InstinctPredictionRecord(Base):
    """One instinct inference (ADR 0026): the being's ``features`` for a stimulus,
    the per-reaction ``reaction_probabilities`` (in the frozen label order), and
    the scalar ``reaction_intensity``. Append-only, one row per prediction."""

    __tablename__ = "instinct_predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=True, index=True)
    being_id = Column(String, nullable=True, index=True)
    tick = Column(Integer, nullable=True)
    features = Column(JSON, nullable=False, default=list)
    reaction_probabilities = Column(JSON, nullable=False, default=list)
    reaction_intensity = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InstinctReactionRecord(Base):
    """The reaction the being had to a stimulus (ADR 0026): which ``reaction`` at
    what ``intensity``, and whether it was ``triggered`` (past threshold) or
    suppressed. Append-only, one row per reaction decision."""

    __tablename__ = "instinct_reactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=True, index=True)
    being_id = Column(String, nullable=True, index=True)
    tick = Column(Integer, nullable=True)
    reaction = Column(String, nullable=False)
    intensity = Column(Float, nullable=True)
    triggered = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InstinctTrainingExampleRecord(Base):
    """A model-ready instinct row (ADR 0026): the ``input_features`` the model saw
    paired with the ``output_labels`` the being actually reacted with, linked to
    the perception ``event_id`` it was derived from. Append-only."""

    __tablename__ = "instinct_training_examples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=True, index=True)
    input_features = Column(JSON, nullable=False, default=list)
    output_labels = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# --- reading: the growing knowledge store (reading R3, ADR 0038) ----------------
#
# `source` is a plain string (the document the passage came from), not a DB
# foreign key — a knowledge chunk is a self-contained, replayable fact about text
# the being read, not a catalog relationship (the same FK discipline as the event
# backbone and beliefs, ADR 0019). The `embedding` is the passage's vector, stored
# as a JSON float list today and pgvector-ready tomorrow: moving to a native
# `vector` column + ANN index (roadmap v11) is an adapter change on this one table,
# not a domain change. Append-only + cumulative — reading a document adds chunks.


class KnowledgeChunk(Base):
    """One embedded passage of the being's growing knowledge store (reading R3, ADR
    0038): the `source` document it came from (for citation), the chunk `text`, and
    its `embedding` vector. Append-only: each ingested document stages its chunks in
    one unit of work (ADR 0017) and never replaces earlier ones, so knowledge
    accumulates across every document read."""

    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False, index=True)
    text = Column(String, nullable=False)
    embedding = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
