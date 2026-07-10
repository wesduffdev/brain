"""Behaviors: how (object properties + action + context) become the outcome
predictor's fixed feature vector, and how outcomes become its label vector.

This is the feature/label contract V0-9 must encode against *identically* to run
the model in shadow mode (ADR 0008). Every assertion is on the public surface of
`FeatureEncoder` (built from `ConfigService`), never on internal layout — the
contract is "this term lands in this slot", not "the array looks like X". These
tests need no PyTorch: encoding is pure and config-driven.
"""
from __future__ import annotations

import os

import pytest

from app.config_service import ConfigService
from app.ml.encode_features import Example, FeatureEncoder
from app.ml.train_outcome_model import synthetic_examples

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _config():
    return ConfigService.from_files(_CONFIG_ROOT)


def _encoder():
    return FeatureEncoder.from_config(_config())


def test_feature_vector_names_the_whole_vocabulary_once_each():
    # The vector is properties ++ actions ++ context — every vocab term present
    # exactly once, so the same object always encodes to the same slots.
    names = _encoder().feature_names()
    assert len(names) == len(set(names))  # no term appears twice
    assert set(names) >= {"round", "rubbery", "red"}  # object properties
    assert {"look", "touch", "push", "grab", "drop"} <= set(names)  # actions
    assert {"surface_hard", "surface_soft"} <= set(names)  # context


def test_present_properties_action_and_context_set_exactly_their_slots():
    encoder = _encoder()
    names = encoder.feature_names()
    vec = encoder.encode_features(
        Example(properties=("round", "red"), action="push", context=("surface_hard",))
    )
    assert len(vec) == encoder.feature_size
    on = {names[i] for i, v in enumerate(vec) if v == 1.0}
    assert on == {"round", "red", "push", "surface_hard"}
    assert all(v in (0.0, 1.0) for v in vec)  # multi-hot, nothing in between


def test_encoding_the_same_example_is_deterministic():
    encoder = _encoder()
    ex = Example(properties=("round", "rubbery"), action="drop", context=("surface_hard",))
    assert encoder.encode_features(ex) == encoder.encode_features(ex)


def test_labels_round_trip_the_outcome_vocabulary():
    encoder = _encoder()
    labels = encoder.label_names()
    assert set(labels) == {
        "rolls",
        "bounces",
        "falls",
        "causes_pain",
        "makes_noise",
        "pleasant",
        "scary",
    }
    y = encoder.encode_labels(Example(action="drop", outcomes=("falls", "bounces")))
    assert len(y) == encoder.label_size
    on = {labels[i] for i, v in enumerate(y) if v == 1.0}
    assert on == {"falls", "bounces"}


def test_a_term_outside_the_vocabulary_is_rejected():
    # Same discipline as the object catalog: a typo or made-up trait is caught,
    # never silently encoded to nothing.
    encoder = _encoder()
    with pytest.raises(ValueError):
        encoder.encode_features(Example(properties=("sparkly",), action="push"))


def test_synthetic_seed_set_is_config_derived_and_covers_every_outcome():
    # With no stored training data yet, the trainer seeds itself from the config
    # vocab; that seed set must exercise every outcome label so the model can
    # learn all of them.
    config = _config()
    examples = synthetic_examples(config)
    assert examples
    covered = set()
    for ex in examples:
        covered.update(ex.outcomes)
    assert covered == set(FeatureEncoder.from_config(config).label_names())
