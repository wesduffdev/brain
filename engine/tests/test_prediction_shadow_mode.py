"""Behavior of prediction shadow mode (V0-9, ADR 0011).

The being runs a learned outcome predictor *alongside* its rule layer: for each
interaction the model's predicted outcomes are recorded next to the rule's
expected outcome and the actual observed outcome, and marked right or wrong —
but the prediction never touches what the being does. These tests pin that
behavior through the public surface (PredictionService, the repository port, and
Simulation), driving the predictor seam with a behaving fake so torch is not
needed here. Real torch-backed inference is covered in `test_inference.py`.
"""
from __future__ import annotations

import os
from typing import Dict

from app.config_service import ConfigService
from app.domain.interaction_event import InteractionEvent
from app.ml.encode_features import Example
from app.ml.inference import load_predictor
from app.repositories import InMemoryPredictionRecordRepository
from app.services.prediction_service import PredictionService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


class FakePredictor:
    """A PredictorPort that returns fixed probabilities — the seam the shadow
    tests drive so behavior is pinned without torch or an artifact."""

    def __init__(self, probabilities: Dict[str, float]):
        self._probabilities = probabilities
        self.calls = 0

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        self.calls += 1
        return dict(self._probabilities)


def _event(**overrides) -> InteractionEvent:
    base = dict(
        being_id="being_001",
        tick=5,
        object_id="obj_red_ball",
        action="drop",
        expected_outcome=("bounces",),
        observed_outcome=("bounces",),
        emotion_before="curious",
        emotion_after="curious",
    )
    base.update(overrides)
    return InteractionEvent(**base)


# --- the shadow-mode record: model vs rule vs actual, marked right/wrong -----


def test_model_predicts_bounce_and_actual_bounces_marks_the_record_correct():
    # BRIEF §16: model predicts bounce, actual is bounce -> record marked correct.
    predictor = FakePredictor({"bounces": 0.9, "falls": 0.2, "rolls": 0.1})
    repo = InMemoryPredictionRecordRepository()
    service = PredictionService(predictor, repo, threshold=0.5)

    service.record(_event(observed_outcome=("bounces",)), properties=("round", "rubbery"))

    (record,) = repo.all()
    assert "bounces" in record.model_outcome
    assert record.actual_observed == ("bounces",)
    assert record.correct is True


def test_a_wrong_prediction_is_marked_incorrect_with_a_nonzero_error():
    predictor = FakePredictor({"bounces": 0.9, "falls": 0.1, "rolls": 0.1})
    repo = InMemoryPredictionRecordRepository()
    service = PredictionService(predictor, repo, threshold=0.5)

    service.record(_event(observed_outcome=("falls",)), properties=("heavy",))

    (record,) = repo.all()
    assert record.correct is False
    assert record.prediction_error > 0.0


def test_the_record_keeps_model_prediction_rule_expectation_and_actual_side_by_side():
    predictor = FakePredictor({"bounces": 0.9, "falls": 0.8, "rolls": 0.1})
    repo = InMemoryPredictionRecordRepository()
    service = PredictionService(predictor, repo, threshold=0.5)

    service.record(
        _event(expected_outcome=("rolls",), observed_outcome=("bounces", "falls")),
        properties=("round", "rubbery"),
    )

    (record,) = repo.all()
    snapshot = record.snapshot()
    assert set(snapshot["modelOutcome"]) == {"bounces", "falls"}  # what the model said
    assert snapshot["ruleExpected"] == ["rolls"]  # what the rule layer expected
    assert set(snapshot["actualObserved"]) == {"bounces", "falls"}  # ground truth
    assert snapshot["probabilities"]["bounces"] == 0.9


# --- shadow mode wired through the Simulation --------------------------------


def _fresh(**kwargs) -> Simulation:
    return Simulation(ConfigService.from_files(_CONFIG_ROOT), **kwargs)


def test_the_engine_records_a_prediction_for_each_interaction():
    predictor = FakePredictor({label: 0.5 for label in ("rolls", "bounces", "falls",
                                                        "causes_pain", "makes_noise",
                                                        "pleasant", "scary")})
    sim = _fresh(predictor=predictor)
    for _ in range(30):
        sim.tick()

    assert len(sim.interactions()) > 0
    assert len(sim.predictions()) == len(sim.interactions())


def test_the_being_behaves_identically_whether_the_predictor_is_on_or_off():
    # The shadow invariant: a recorded prediction never feeds the decision, so
    # the action stream and state must be byte-identical predictor on vs off.
    predictor = FakePredictor({label: 0.7 for label in ("rolls", "bounces", "falls",
                                                        "causes_pain", "makes_noise",
                                                        "pleasant", "scary")})
    on = _fresh(predictor=predictor)
    off = _fresh()  # shadow off — no predictor

    on_states, off_states = [], []
    for tick in range(40):
        if tick == 10:  # a world event both runs feel identically
            on.change_environment(light="dark")
            off.change_environment(light="dark")
        on_states.append(on.tick())
        off_states.append(off.tick())

    assert on_states == off_states
    assert on.interactions() == off.interactions()
    # And the predictor genuinely ran (the invariant is not vacuously true).
    assert len(on.predictions()) > 0
    assert off.predictions() == []


def test_without_a_predictor_shadow_mode_records_nothing():
    sim = _fresh()
    for _ in range(20):
        sim.tick()

    assert sim.predictions() == []


# --- graceful degradation: no artifact, no torch, no shadow -----------------


def test_a_missing_model_artifact_yields_no_predictor():
    config = ConfigService.from_files(_CONFIG_ROOT)
    predictor = load_predictor(config=config, model_path="/nonexistent/outcome_predictor.pt")
    assert predictor is None
