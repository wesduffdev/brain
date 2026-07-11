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
