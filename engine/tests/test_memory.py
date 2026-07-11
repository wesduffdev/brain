"""Behavior of durable MEMORY records (card v1).

Every meaningful interaction the being has writes one durable memory: a snapshot
of what it PERCEIVED (properties, never a developer label), the action it took,
what it expected vs. observed, its emotion before and after, the prediction error
when a predictor is watching, and a config-driven PRIORITY (salience) — how
strongly later learning should attend to the experience. High surprise (a large
prediction error) or high emotional intensity raise the priority; retuning that
salience is a config change only.

These pin the behavior through public surfaces:

- the `Simulation` — a run writes one memory per interaction, keyed on perceived
  properties, never a developer label, and reads them back via `memories()`;
- the `MemoryService` — priority rises with prediction error and with emotional
  intensity;
- the `ConfigService` — retuning the priority weighting is config-only (the same
  interaction yields a different priority purely from `learning_rates.yaml`);
- a live-Postgres round-trip — a memory row lands FK-linked to its
  interaction_event (skipped, never faked, when Postgres is unreachable).
"""
from __future__ import annotations

import os
from typing import Dict

import pytest

from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.db import models
from app.db.migrate import create_all, drop_all
from app.db.session import create_db_engine, session_factory
from app.domain.interaction_event import InteractionEvent
from app.domain.prediction_record import PredictionRecord
from app.ml.encode_features import Example
from app.repositories import InMemoryMemoryRepository
from app.services.memory_service import MemoryService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_OUTCOME_LABELS = (
    "rolls",
    "bounces",
    "falls",
    "causes_pain",
    "makes_noise",
    "pleasant",
    "scary",
)


def _event(*, emotion_before: str = "calm", emotion_after: str = "calm") -> InteractionEvent:
    return InteractionEvent(
        being_id="being_001",
        tick=1,
        object_id="obj_red_ball",
        action="touch",
        expected_outcome=("bounces",),
        observed_outcome=("bounces",),
        emotion_before=emotion_before,
        emotion_after=emotion_after,
    )


def _prediction(prediction_error: float) -> PredictionRecord:
    return PredictionRecord(
        being_id="being_001",
        tick=1,
        object_id="obj_red_ball",
        action="touch",
        prediction_error=prediction_error,
    )


class _FakePredictor:
    """A PredictorPort returning fixed probabilities — turns shadow mode on
    without torch or an artifact, so a prediction (and its error) rides along
    with each interaction."""

    def __init__(self, probabilities: Dict[str, float]):
        self._probabilities = probabilities

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        return dict(self._probabilities)


def _fake_predictor() -> _FakePredictor:
    return _FakePredictor({label: 0.5 for label in _OUTCOME_LABELS})


# --- through the Simulation: an interaction is remembered --------------------


def test_an_interaction_writes_one_memory_per_interaction():
    config = ConfigService.from_files(_CONFIG_ROOT)
    memories = InMemoryMemoryRepository()

    sim = Simulation(config, memory_repository=memories)
    for _ in range(80):
        sim.tick()

    assert len(sim.interactions()) > 0, "the being should have acted at least once"
    # every meaningful interaction leaves exactly one durable memory
    assert len(sim.memories()) == len(sim.interactions())


def test_a_memory_keys_on_perceived_properties_never_a_developer_label():
    config = ConfigService.from_files(_CONFIG_ROOT)
    memories = InMemoryMemoryRepository()

    sim = Simulation(config, memory_repository=memories)
    for _ in range(80):
        sim.tick()

    remembered = sim.memories()
    assert remembered, "the being should have remembered at least one interaction"
    for memory in remembered:
        # the object snapshot is what the being PERCEIVED, never the developer's
        # private label (ADR 0002)
        assert "perceivedProperties" in memory
        assert "developerLabel" not in memory


# --- through the MemoryService: priority is salience -------------------------


def test_higher_prediction_error_yields_higher_priority():
    config = ConfigService.from_files(_CONFIG_ROOT)
    service = MemoryService(InMemoryMemoryRepository(), config.memory_priority_policy())

    low = service.remember(_event(), perceived_properties=("round",), prediction=_prediction(0.1))
    high = service.remember(_event(), perceived_properties=("round",), prediction=_prediction(0.9))

    assert high.priority > low.priority


def test_higher_emotional_intensity_yields_higher_priority():
    config = ConfigService.from_files(_CONFIG_ROOT)
    service = MemoryService(InMemoryMemoryRepository(), config.memory_priority_policy())

    calm = service.remember(
        _event(emotion_before="calm", emotion_after="calm"), perceived_properties=("round",)
    )
    afraid = service.remember(
        _event(emotion_before="calm", emotion_after="scared"), perceived_properties=("round",)
    )

    assert afraid.priority > calm.priority


def test_retuning_memory_priority_is_config_only():
    # The SAME interaction (same event, same prediction error) yields a different
    # priority purely from config — proving salience is tuned in
    # learning_rates.yaml, never in service code.
    event = _event()
    prediction = _prediction(0.5)

    quiet = ConfigService.from_dict(
        tick_rates={},
        emotions={},
        learning_rates={"memory": {"priority": {"prediction_error_weight": 0.0}}},
    )
    loud = ConfigService.from_dict(
        tick_rates={},
        emotions={},
        learning_rates={"memory": {"priority": {"prediction_error_weight": 2.0}}},
    )

    quiet_memory = MemoryService(
        InMemoryMemoryRepository(), quiet.memory_priority_policy()
    ).remember(event, perceived_properties=("round",), prediction=prediction)
    loud_memory = MemoryService(
        InMemoryMemoryRepository(), loud.memory_priority_policy()
    ).remember(event, perceived_properties=("round",), prediction=prediction)

    assert loud_memory.priority > quiet_memory.priority


# --- live Postgres round-trip (skipped when unreachable, never faked) --------


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
def test_a_memory_row_lands_fk_linked_to_its_interaction_event():
    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so the counts below see only this run
    create_all(engine)

    # The bootstrap opens its own session, seeds the parent rows, and wires the
    # Postgres adapters — including the memory adapter. A fake predictor turns
    # shadow mode on so each memory carries a real prediction error.
    config = ConfigService.from_files(_CONFIG_ROOT)
    built = build_simulation(
        config,
        env={"DATABASE_URL": os.environ["DATABASE_URL"]},
        predictor=_fake_predictor(),
    )
    sim = built.simulation
    try:
        for _ in range(80):
            sim.tick()

        session = session_factory(engine)()
        try:
            memory_count = session.query(models.Memory).count()
            event_ids = {row.event_id for row in session.query(models.InteractionEvent).all()}

            # one memory per interaction, all persisted
            assert memory_count == len(sim.interactions()) > 0
            # every memory row is FK-linked to a real interaction_event and carries
            # its config-driven priority
            for row in session.query(models.Memory).all():
                assert row.event_id in event_ids
                assert row.priority is not None
        finally:
            session.close()
    finally:
        built.close()
        engine.dispose()
