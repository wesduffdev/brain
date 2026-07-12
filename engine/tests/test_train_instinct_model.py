"""Behavior: training the tiny instinct model on its synthetic rule-labeled seed
set writes a versioned artifact that reloads with its feature/label contract,
predicts a probability per reaction plus an intensity, and — for a stimulus that
is a fast object incoming toward the body — scores `flinch` above `ignore`
(ADR 0026).

PyTorch is a training-only dependency kept out of the lean runtime image, so this
whole module is skipped where torch is not installed — the encoding contract in
`test_instinct_encoder.py` is covered without it. Kept fast: a tiny net on the
small synthetic seed, into a temp path.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

torch = pytest.importorskip("torch")  # noqa: F841 — training-only dep gate

from app.config_service import ConfigService
from app.domain.instinct import InstinctTrainingExample
from app.ml import train_instinct_model as trainer
from app.ml.instinct_encoder import InstinctFeatureEncoder, Stimulus
from app.ml.instinct_model import load_instinct_model
from app.repositories import (
    InMemoryInstinctTrainingExampleRepository,
    InMemoryModelRunRepository,
)

import os

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_FIXED_TIME = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)


def _shipped_config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _fast_incoming_object() -> Stimulus:
    """A large object rushing straight at the body, about to make contact —
    the textbook flinch stimulus."""
    return Stimulus(
        distance=0.08,
        velocity=0.95,
        acceleration=0.8,
        trajectory_toward_body=0.97,
        time_to_contact=0.04,
        object_size=0.6,
        size_change_rate=0.9,
        unexpectedness=0.7,
        visibility_confidence=0.7,
    )


def test_a_fast_incoming_object_scores_flinch_above_ignore():
    config = _shipped_config()
    encoder = InstinctFeatureEncoder.from_config(config)
    params = config.instinct_model_policy()

    model, _ = trainer.train(
        encoder=encoder,
        examples=trainer.synthetic_examples(config),
        epochs=params.epochs,
        hidden_size=params.hidden_size,
        learning_rate=params.learning_rate,
        seed=params.seed,
    )

    probs, intensity = model.predict_one(encoder.encode_features(_fast_incoming_object()))
    reactions = dict(zip(encoder.label_names(), probs))

    assert reactions["flinch"] > reactions["ignore"]
    assert 0.0 <= intensity <= 1.0
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_training_writes_a_reloadable_artifact_with_its_contract(tmp_path):
    config = _shipped_config()
    encoder = InstinctFeatureEncoder.from_config(config)
    out = tmp_path / "instinct.pt"

    metrics = trainer.train_and_save(
        encoder=encoder,
        examples=trainer.synthetic_examples(config),
        output_path=str(out),
        epochs=5,
        hidden_size=8,
    )

    assert out.exists()
    assert metrics["num_examples"] > 0
    assert "final_loss" in metrics
    assert "intensity_mae" in metrics

    model, contract = load_instinct_model(str(out))
    assert tuple(contract["feature_names"]) == encoder.feature_names()
    assert tuple(contract["label_names"]) == encoder.label_names()


def test_run_training_records_a_model_run_row_through_the_port(tmp_path):
    config = _shipped_config()
    runs = InMemoryModelRunRepository()
    out = tmp_path / "instinct.pt"

    metrics = trainer.run_training(
        config=config,
        output_path=str(out),
        model_run_repo=runs,
        timestamp=_FIXED_TIME,
        epochs=3,
        hidden_size=8,
    )

    assert out.exists()
    assert metrics["source"] == "synthetic"
    recorded = runs.all()
    assert len(recorded) == 1
    assert recorded[0].artifact_path == str(out)
    assert recorded[0].finished_at == _FIXED_TIME
    assert recorded[0].metrics["num_examples"] == metrics["num_examples"]


def test_run_training_runs_standalone_with_no_repositories(tmp_path):
    config = _shipped_config()
    out = tmp_path / "instinct.pt"

    metrics = trainer.run_training(
        config=config,
        output_path=str(out),
        timestamp=_FIXED_TIME,
        epochs=1,
        hidden_size=4,
    )

    assert out.exists()
    assert metrics["source"] == "synthetic"


# --- run_training on persisted examples (INS-RETRAIN) ------------------------
#
# Closing the instinct learning loop: when the `instinct_training_examples` table
# holds rows (EVT-PERSIST), `run_training` trains on THEM through the repository
# port instead of the synthetic seed, mirroring how the outcome trainer already
# uses persisted `training_examples`. The torch run itself is gated with the rest
# of this module; the pure dataset SELECTION is covered torch-free in
# `test_train_instinct_dataset.py`.


def test_run_training_trains_on_persisted_examples_and_records_the_run(tmp_path):
    config = _shipped_config()
    encoder = InstinctFeatureEncoder.from_config(config)
    stored = InMemoryInstinctTrainingExampleRepository()
    for i, (stim, reactions) in enumerate(
        [
            (Stimulus(velocity=0.9, trajectory_toward_body=0.9, time_to_contact=0.1), ("flinch",)),
            (Stimulus(sound_spike_intensity=0.9, unexpectedness=0.8, visibility_confidence=0.2), ("freeze",)),
            (Stimulus(), ("ignore",)),
        ]
    ):
        stored.add(
            InstinctTrainingExample(
                event_id=f"being_001:{i}",
                input_features=encoder.encode_features(stim),
                output_labels=encoder.encode_labels(reactions),
            )
        )
    runs = InMemoryModelRunRepository()
    out = tmp_path / "instinct.pt"

    metrics = trainer.run_training(
        config=config,
        output_path=str(out),
        training_repo=stored,
        model_run_repo=runs,
        timestamp=_FIXED_TIME,
        epochs=3,
        hidden_size=8,
    )

    assert out.exists()
    # trained on the PERSISTED examples, not the synthetic seed
    assert metrics["source"] == "instinct_training_examples"
    assert metrics["num_examples"] == 3
    recorded = runs.all()
    assert len(recorded) == 1
    assert recorded[0].metrics["source"] == "instinct_training_examples"
    # the artifact still carries + validates the current encoder's contract
    _model, contract = load_instinct_model(str(out))
    assert tuple(contract["feature_names"]) == encoder.feature_names()
    assert tuple(contract["label_names"]) == encoder.label_names()
