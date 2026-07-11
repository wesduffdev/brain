"""Behavior: loading `instinct.pt` behind the InstinctPredictorPort runs the tiny
net against the SAME encode contract it was trained on (ADR 0026) and yields a
reaction probability per label plus an intensity — and a stale artifact whose
feature/label contract disagrees with the current config is rejected loudly,
never silently paired with newer config (the ADR 0008 discipline instinct reuses).

PyTorch is a training/inference-only dependency kept out of the lean runtime, so
this module is skipped where torch is absent — the encoding contract is covered
without it (`test_instinct_encoder.py`). Kept fast: one tiny artifact, no database.
"""
from __future__ import annotations

import os

import pytest

torch = pytest.importorskip("torch")  # noqa: F841 — training/inference-only gate

from app.config_service import ConfigService
from app.ml import train_instinct_model as trainer
from app.ml.instinct_encoder import InstinctFeatureEncoder, InstinctSpec, Stimulus
from app.ml.instinct_inference import load_instinct_predictor
from app.ports.instinct import InstinctPrediction

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _shipped_config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _train_shipped_artifact(tmp_path) -> str:
    config = _shipped_config()
    out = tmp_path / "instinct.pt"
    trainer.train_and_save(
        encoder=InstinctFeatureEncoder.from_config(config),
        examples=trainer.synthetic_examples(config),
        output_path=str(out),
        epochs=5,
        hidden_size=8,
    )
    return str(out)


def test_a_loaded_predictor_returns_a_probability_per_reaction_and_an_intensity(tmp_path):
    config = _shipped_config()
    predictor = load_instinct_predictor(config=config, model_path=_train_shipped_artifact(tmp_path))
    assert predictor is not None

    prediction = predictor.predict_reactions(
        Stimulus(velocity=0.9, trajectory_toward_body=0.9, time_to_contact=0.05, size_change_rate=0.8)
    )

    assert isinstance(prediction, InstinctPrediction)
    assert set(prediction.reactions) == set(config.instinct_labels())
    assert all(0.0 <= p <= 1.0 for p in prediction.reactions.values())
    assert 0.0 <= prediction.intensity <= 1.0


def test_missing_artifact_loads_gracefully_as_none(tmp_path):
    # No artifact on disk -> None (instinct off), never an error.
    assert load_instinct_predictor(config=_shipped_config(), model_path=str(tmp_path / "absent.pt")) is None


def test_an_artifact_trained_on_a_different_contract_is_rejected_not_silently_used(tmp_path):
    # A model trained against a DIFFERENT feature/label vocabulary must not be
    # paired with the shipped config — that is a stale artifact (ADR 0026/0008).
    mismatched = InstinctFeatureEncoder(
        InstinctSpec(
            feature_order=("distance", "velocity"),
            label_vocab=("flinch", "ignore"),
        )
    )
    out = tmp_path / "instinct.pt"
    examples = [
        trainer.LabeledStimulus(Stimulus(distance=0.1, velocity=0.9), ("flinch",), 0.9),
        trainer.LabeledStimulus(Stimulus(distance=0.9, velocity=0.05), ("ignore",), 0.05),
    ]
    trainer.train_and_save(
        encoder=mismatched,
        examples=examples,
        output_path=str(out),
        epochs=1,
        hidden_size=4,
    )

    with pytest.raises(ValueError):
        load_instinct_predictor(config=_shipped_config(), model_path=str(out))
