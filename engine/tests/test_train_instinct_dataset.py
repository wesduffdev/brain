"""Behavior: the instinct trainer's DATASET SELECTION — which examples it learns
from — mirrors the outcome trainer (`train_outcome_model`): the persisted
`instinct_training_examples` read through the repository port when the table holds
any, else the config-derived synthetic seed set, byte-identical to before.

This is the pure, torch-free half of the trainer (choosing the data, not running
the net), so it is covered WITHOUT PyTorch — the torch training run stays gated in
`test_train_instinct_model.py`. Driven through the public `training_rows` surface.
"""
from __future__ import annotations

import os

from app.config_service import ConfigService
from app.domain.instinct import InstinctTrainingExample
from app.ml import train_instinct_model as trainer
from app.ml.instinct_encoder import InstinctFeatureEncoder, Stimulus
from app.repositories import InMemoryInstinctTrainingExampleRepository

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _expected_synthetic_rows(config):
    """The dataset today: the synthetic seed set encoded through the ADR 0026
    contract — the byte-for-byte fallback the trainer must reproduce."""
    encoder = InstinctFeatureEncoder.from_config(config)
    return [
        (
            encoder.encode_features(ex.stimulus),
            encoder.encode_labels(ex.reactions),
            float(ex.intensity),
        )
        for ex in trainer.synthetic_examples(config)
    ]


def test_dataset_is_built_from_persisted_examples_when_present():
    config = _config()
    encoder = InstinctFeatureEncoder.from_config(config)
    repo = InMemoryInstinctTrainingExampleRepository()

    feats_a = encoder.encode_features(
        Stimulus(velocity=0.9, trajectory_toward_body=0.9, time_to_contact=0.1)
    )
    labels_a = encoder.encode_labels(("flinch",))
    feats_b = encoder.encode_features(
        Stimulus(sound_spike_intensity=0.9, unexpectedness=0.8, visibility_confidence=0.2)
    )
    labels_b = encoder.encode_labels(("freeze",))
    repo.add(InstinctTrainingExample("e1", feats_a, labels_a))
    repo.add(InstinctTrainingExample("e2", feats_b, labels_b))

    rows, source = trainer.training_rows(config, repo)

    assert source == "instinct_training_examples"
    # the rows are the PERSISTED features/labels, in order — not the synthetic seed
    assert len(rows) == 2
    assert rows[0][0] == feats_a and rows[0][1] == labels_a
    assert rows[1][0] == feats_b and rows[1][1] == labels_b
    assert len(rows) != len(trainer.synthetic_examples(config))


def test_dataset_falls_back_to_synthetic_when_the_table_is_empty():
    config = _config()

    rows, source = trainer.training_rows(config, InMemoryInstinctTrainingExampleRepository())

    assert source == "synthetic"
    assert rows == _expected_synthetic_rows(config)  # byte-identical to today


def test_dataset_falls_back_to_synthetic_with_no_repository():
    config = _config()

    rows, source = trainer.training_rows(config)

    assert source == "synthetic"
    assert rows == _expected_synthetic_rows(config)  # byte-identical to today


def test_persisted_intensity_target_reads_the_strongest_protective_reaction():
    config = _config()
    encoder = InstinctFeatureEncoder.from_config(config)
    repo = InMemoryInstinctTrainingExampleRepository()
    base = encoder.encode_features(Stimulus())

    repo.add(InstinctTrainingExample("e1", base, encoder.encode_labels(("flinch",))))
    repo.add(InstinctTrainingExample("e2", base, encoder.encode_labels(("ignore",))))

    rows, _ = trainer.training_rows(config, repo)
    intensities = [row[2] for row in rows]

    # a fired protective reaction -> full intensity; a bare `ignore` -> none.
    assert intensities[0] == 1.0
    assert intensities[1] == 0.0
