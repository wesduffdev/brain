"""Behavior: the InstinctFeatureEncoder is the single, pure home of the frozen
14-feature instinct input contract (ADR 0026).

Like the outcome `FeatureEncoder`, it is torch-free and config-vocab driven — the
authored feature order IS the contract, so a perceived `Stimulus` always encodes
to the same 14 slots and the model's five reaction slots always mean the same
reactions. This module needs no torch, so it runs in the default (lean) suite.
"""
from __future__ import annotations

import os

import pytest

from app.config_service import ConfigService
from app.ml.instinct_encoder import InstinctFeatureEncoder, InstinctSpec, Stimulus

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

# The frozen ordered 14-feature vector and 5-label set (ADR 0026). Reordering or
# inserting a feature/label is a contract change; this pins the order.
_FROZEN_FEATURES = (
    "distance",
    "velocity",
    "acceleration",
    "trajectory_toward_body",
    "time_to_contact",
    "object_size",
    "size_change_rate",
    "unexpectedness",
    "visibility_confidence",
    "sound_spike_intensity",
    "touch_intensity",
    "current_focus_level",
    "current_stability",
    "prior_prediction_error",
)
_FROZEN_LABELS = ("flinch", "freeze", "orient", "withdraw", "ignore")


def _tiny_encoder() -> InstinctFeatureEncoder:
    return InstinctFeatureEncoder(
        InstinctSpec(
            feature_order=("distance", "velocity", "touch_intensity"),
            label_vocab=("flinch", "ignore"),
        )
    )


def test_shipped_config_freezes_the_ordered_14_feature_5_label_contract():
    encoder = InstinctFeatureEncoder.from_config(ConfigService.from_files(_CONFIG_ROOT))
    assert encoder.feature_names() == _FROZEN_FEATURES
    assert encoder.label_names() == _FROZEN_LABELS
    assert encoder.feature_size == 14
    assert encoder.label_size == 5


def test_encoder_round_trips_the_feature_vector_in_config_order():
    encoder = InstinctFeatureEncoder.from_config(ConfigService.from_files(_CONFIG_ROOT))
    stimulus = Stimulus(
        distance=0.1,
        velocity=0.9,
        acceleration=0.8,
        trajectory_toward_body=0.95,
        time_to_contact=0.05,
        object_size=0.4,
        size_change_rate=0.7,
        unexpectedness=0.6,
        visibility_confidence=0.3,
        sound_spike_intensity=0.2,
        touch_intensity=0.0,
        current_focus_level=0.5,
        current_stability=0.5,
        prior_prediction_error=0.25,
    )
    vector = encoder.encode_features(stimulus)

    # exactly 14 slots, each the scalar named at that position in config order
    assert len(vector) == 14
    expected = tuple(getattr(stimulus, name) for name in _FROZEN_FEATURES)
    assert vector == pytest.approx(expected)


def test_encode_labels_is_multi_hot_over_the_reaction_vocabulary():
    encoder = _tiny_encoder()
    assert encoder.encode_labels(("flinch",)) == (1.0, 0.0)
    assert encoder.encode_labels(("ignore",)) == (0.0, 1.0)
    assert encoder.encode_labels(("flinch", "ignore")) == (1.0, 1.0)
    assert encoder.encode_labels(()) == (0.0, 0.0)


def test_encoder_rejects_a_feature_outside_the_frozen_contract():
    with pytest.raises(ValueError):
        InstinctFeatureEncoder(InstinctSpec(feature_order=("not_a_real_feature",)))


def test_encode_labels_rejects_an_unknown_reaction():
    with pytest.raises(ValueError):
        _tiny_encoder().encode_labels(("teleport",))
