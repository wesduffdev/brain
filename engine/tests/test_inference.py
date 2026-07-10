"""Behavior: real torch-backed shadow-mode inference (V0-9, ADR 0011).

Loading `outcome_predictor.pt` and running it against the SAME encode contract it
was trained on (ADR 0008) yields an outcome probability per label, which the
engine records in shadow mode. PyTorch is a training/inference-only dependency
kept out of the lean runtime, so this whole module is skipped where torch is
absent — the encoding contract and the shadow wiring are covered without it
(`test_encode_features.py`, `test_prediction_shadow_mode.py`). Kept fast: one
mini-epoch into a temp artifact, no database.
"""
from __future__ import annotations

import os

import pytest

torch = pytest.importorskip("torch")  # noqa: F841 — training/inference-only gate

from app.config_service import ConfigService
from app.ml import train_outcome_model as trainer
from app.ml.encode_features import Example, FeatureEncoder, FeatureSpec
from app.ml.inference import load_predictor
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _shipped_config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _train_shipped_artifact(tmp_path) -> str:
    """Train a tiny artifact whose contract matches the shipped config."""
    config = _shipped_config()
    encoder = FeatureEncoder.from_config(config)
    out = tmp_path / "outcome_predictor.pt"
    trainer.train_and_save(
        encoder=encoder,
        examples=trainer.synthetic_examples(config),
        output_path=str(out),
        epochs=5,
        hidden_size=8,
    )
    return str(out)


def test_a_loaded_predictor_returns_a_probability_per_outcome(tmp_path):
    config = _shipped_config()
    predictor = load_predictor(config=config, model_path=_train_shipped_artifact(tmp_path))
    assert predictor is not None

    probs = predictor.predict_outcomes(
        Example(properties=("round", "rubbery"), action="drop", context=("surface_hard",))
    )

    assert set(probs) == set(config.outcome_labels())
    assert all(0.0 <= p <= 1.0 for p in probs.values())


def test_the_engine_loads_the_model_and_records_real_predictions(tmp_path):
    config = _shipped_config()
    predictor = load_predictor(config=config, model_path=_train_shipped_artifact(tmp_path))

    sim = Simulation(config, predictor=predictor)
    for _ in range(15):
        sim.tick()

    predictions = sim.predictions()
    assert len(predictions) == len(sim.interactions())
    assert predictions, "expected the loaded model to record predictions in shadow mode"
    row = predictions[0]
    assert set(row["probabilities"]) == set(config.outcome_labels())
    assert "actualObserved" in row and "ruleExpected" in row and "correct" in row


def test_an_artifact_trained_on_a_different_vocabulary_is_rejected_not_silently_used(tmp_path):
    # ADR 0008: a stale artifact must never be silently paired with newer config.
    mismatched_encoder = FeatureEncoder(
        FeatureSpec(
            property_vocab=("round", "rubbery"),
            action_vocab=("push", "drop"),
            context_vocab=("surface_hard",),
            label_vocab=("rolls", "bounces"),
        )
    )
    out = tmp_path / "outcome_predictor.pt"
    trainer.train_and_save(
        encoder=mismatched_encoder,
        examples=[Example(("round",), "drop", ("surface_hard",), ("rolls",))],
        output_path=str(out),
        epochs=1,
        hidden_size=4,
    )

    with pytest.raises(ValueError):
        load_predictor(config=_shipped_config(), model_path=str(out))
