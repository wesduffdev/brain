"""Behavior of persisting interaction events and derived training examples (V0-7b).

As the simulation runs, every InteractionEvent it produces is written through a
repository port, and a TrainingExample is derived from it (encoded via the
ADR 0008 feature/label contract) and written through its own port. These tests
pin that behavior through the public surfaces:

- `Simulation.tick()` drives the being to act;
- the injected repository ports (`InteractionEventRepository`,
  `TrainingExampleRepository`) are the seam the writes go through, so a fake
  in-memory adapter is all the behavior suite needs — no database;
- a live Postgres round-trip runs the same ports against a real database when
  DATABASE_URL is reachable, and skips cleanly otherwise (`integration`, never
  faked).

Scope note (ADR 0007 / 0012): the being aggregate already had a port (V0-7);
this slice adds the event + training-example ports and wires the engine to feed
them per interaction.
"""
from __future__ import annotations

import os

import pytest

from app.config_service import ConfigService
from app.db.migrate import create_all, drop_all
from app.db import models
from app.db.session import create_db_engine, session_factory
from app.domain.interaction_event import InteractionEvent
from app.domain.training_example import TrainingExample
from app.ml.encode_features import FeatureEncoder
from app.repositories import (
    InMemoryInteractionEventRepository,
    InMemoryTrainingExampleRepository,
    PostgresInteractionEventRepository,
    PostgresTrainingExampleRepository,
)
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

# --- a focused world: one soft object the being always touches, so every tick
# produces exactly one affordance-based interaction (and therefore one training
# example). Needs are contextual (no drift) and there are no emotion rules, so
# the being's choice is a pure function of the config below.
_OUTCOME = {
    "labels": ["rolls", "bounces", "falls", "causes_pain", "makes_noise", "pleasant", "scary"],
    "context_features": ["surface_hard", "surface_soft"],
}
_OBJECTS = {
    "properties": ["soft", "round", "red"],
    "affordances": ["look", "touch", "push", "grab", "drop"],
    "objects": {
        "obj_soft": {"developerLabel": "Soft", "properties": ["soft"], "affordances": ["touch"]},
    },
}
_TOUCH_ONLY = {
    "actions": {
        "touch": {
            "affordance": "touch",
            "utility": {"base": 10.0, "needs": {}, "emotions": {}},
            "expected_outcomes": [],
            "property_outcomes": {"soft": ["pleasant"]},
            "reason": "reaching out to touch",
        }
    }
}
_APPROACH_ONLY = {
    "actions": {
        "approach": {
            "free": True,
            "utility": {"base": 10.0, "needs": {}, "emotions": {}},
            "expected_outcomes": [],
            "reason": "moving closer",
        }
    }
}


def _needs():
    levels = {"curiosity": 40, "safety": 80, "comfort": 70, "hunger": 30, "sleep": 30, "warmth": 50}
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _config(actions):
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": _needs()},
        {"rules": [], "default": "calm"},
        rooms={"room": {"id": "room_001", "contains": ["obj_soft"]}},
        objects=_OBJECTS,
        outcome=_OUTCOME,
        actions=actions,
        safety={"rules": []},
    )


# --- interaction events ----------------------------------------------------


def test_running_the_sim_writes_each_interaction_event_through_the_port():
    events = InMemoryInteractionEventRepository()
    sim = Simulation(_config(_TOUCH_ONLY), event_repo=events)

    for _ in range(5):
        sim.tick()

    persisted = events.all()
    assert len(persisted) == 5
    assert [e.action for e in persisted] == ["touch"] * 5
    assert {e.object_id for e in persisted} == {"obj_soft"}
    # the port shows the same events the in-memory interaction log does
    assert [e.event_id for e in persisted] == [f"being_001:{t}" for t in range(1, 6)]


# --- derived training examples ---------------------------------------------


def test_a_training_example_is_derived_and_persisted_per_interaction():
    events = InMemoryInteractionEventRepository()
    examples = InMemoryTrainingExampleRepository()
    config = _config(_TOUCH_ONLY)
    sim = Simulation(config, event_repo=events, training_repo=examples)

    for _ in range(5):
        sim.tick()

    derived = examples.all()
    assert len(derived) == 5
    # each derived example links back to the interaction event it came from
    assert {x.event_id for x in derived} == {e.event_id for e in events.all()}


def test_the_derived_example_encodes_the_observed_outcome_via_the_contract():
    examples = InMemoryTrainingExampleRepository()
    config = _config(_TOUCH_ONLY)
    sim = Simulation(config, training_repo=examples)

    sim.tick()

    encoder = FeatureEncoder.from_config(config)
    example = examples.all()[-1]
    # input carries the object's property and the affordance taken on it
    features = dict(zip(encoder.feature_names(), example.input_features))
    assert features["soft"] == 1.0
    assert features["touch"] == 1.0
    # label carries the observed outcome (touching something soft is pleasant)
    labels = dict(zip(encoder.label_names(), example.output_labels))
    assert labels["pleasant"] == 1.0
    assert labels["scary"] == 0.0


def test_a_free_action_is_recorded_as_an_event_but_yields_no_training_example():
    # A free action (approach/withdraw) has no affordance, so it is not an
    # object-property -> outcome interaction the predictor models: the event is
    # still persisted, but no training example is derived.
    events = InMemoryInteractionEventRepository()
    examples = InMemoryTrainingExampleRepository()
    sim = Simulation(_config(_APPROACH_ONLY), event_repo=events, training_repo=examples)

    for _ in range(4):
        sim.tick()

    assert [e.action for e in events.all()] == ["approach"] * 4
    assert examples.all() == []


def test_persistence_is_optional_the_sim_still_runs_without_repositories():
    # With no repository injected the write seam is a no-op: the being still acts
    # and logs its interactions in memory, and nothing raises.
    sim = Simulation(_config(_TOUCH_ONLY))

    for _ in range(3):
        sim.tick()

    assert len(sim.interactions()) == 3


# --- live Postgres round-trip (skipped when unreachable, never faked) -------


def _reachable_postgres_or_skip():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping live Postgres round-trip")
    try:
        engine = create_db_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connect failure means "skip, don't fake"
        pytest.skip(f"Postgres not reachable at DATABASE_URL ({type(exc).__name__}) — skipping")
    return engine


@pytest.mark.integration
def test_events_and_examples_persist_to_a_reachable_postgres():
    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so the query below sees only this run
    create_all(engine)
    session = session_factory(engine)()
    try:
        # Seed the parent rows the schema's foreign keys require, then run the
        # real simulation on the shipped config, wired to the Postgres adapters.
        config = ConfigService.from_files(_CONFIG_ROOT)
        session.add(models.Being(being_id="being_001", needs={}, emotion="calm"))
        for entity in config.object_catalog().values():
            session.add(
                models.ObjectRecord(
                    object_id=entity.object_id,
                    developer_label=entity.developer_label,
                    properties=list(entity.properties),
                    affordances=list(entity.affordances),
                )
            )
        session.commit()

        events = PostgresInteractionEventRepository(session)
        examples = PostgresTrainingExampleRepository(session)
        sim = Simulation(config, event_repo=events, training_repo=examples)
        for _ in range(80):
            sim.tick()

        stored_events = events.all()
        stored_examples = examples.all()
        # every interaction the being logged was written to Postgres
        assert len(stored_events) == len(sim.interactions())
        assert stored_events, "the being should have acted at least once"
        # a training example exists for each affordance-based interaction, and
        # links back to a persisted event
        policies = config.action_policies()
        affordance_events = [
            e for e in stored_events if policies[e.action].affordance is not None
        ]
        assert affordance_events, "the being should have taken at least one affordance action"
        assert len(stored_examples) == len(affordance_events)
        event_ids = {e.event_id for e in stored_events}
        assert all(x.event_id in event_ids for x in stored_examples)
    finally:
        session.close()
        engine.dispose()
