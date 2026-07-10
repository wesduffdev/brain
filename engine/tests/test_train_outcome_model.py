"""Behavior: training the outcome predictor on a tiny synthetic set writes a
model artifact that reloads with its feature/label contract intact and predicts a
probability per outcome (ADR 0008).

PyTorch is a training-only dependency (kept out of the lean runtime image), so
this behavior is skipped where torch is not installed — the encoding contract in
`test_encode_features.py` is covered without it. Kept fast: one mini-epoch on a
handful of examples with a tiny hidden layer, into a temp path.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")  # noqa: F841 — training-only dep gate

from app.ml import train_outcome_model as trainer
from app.ml.encode_features import Example, FeatureEncoder, FeatureSpec
from app.ml.outcome_model import load_outcome_model


def _tiny_encoder():
    return FeatureEncoder(
        FeatureSpec(
            property_vocab=("round", "rubbery", "heavy"),
            action_vocab=("push", "drop"),
            context_vocab=("surface_hard",),
            label_vocab=("rolls", "bounces", "falls"),
        )
    )


def _tiny_examples():
    return [
        Example(("round", "rubbery"), "drop", ("surface_hard",), ("falls", "bounces")),
        Example(("round",), "push", (), ("rolls",)),
        Example(("heavy",), "drop", ("surface_hard",), ("falls",)),
    ]


def test_training_writes_a_reloadable_artifact_with_its_contract(tmp_path):
    out = tmp_path / "outcome_predictor.pt"
    metrics = trainer.train_and_save(
        encoder=_tiny_encoder(),
        examples=_tiny_examples(),
        output_path=str(out),
        epochs=1,
        hidden_size=4,
    )

    assert out.exists()
    assert metrics["num_examples"] == 3
    assert "final_loss" in metrics

    model, contract = load_outcome_model(str(out))
    assert contract["label_names"] == ["rolls", "bounces", "falls"]
    assert contract["feature_names"] == list(_tiny_encoder().feature_names())


def test_reloaded_model_predicts_a_probability_per_outcome(tmp_path):
    out = tmp_path / "outcome_predictor.pt"
    encoder = _tiny_encoder()
    trainer.train_and_save(
        encoder=encoder,
        examples=_tiny_examples(),
        output_path=str(out),
        epochs=1,
        hidden_size=4,
    )

    model, _ = load_outcome_model(str(out))
    probs = model.predict_one(encoder.encode_features(_tiny_examples()[0]))

    assert len(probs) == encoder.label_size
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_training_also_writes_a_metrics_sidecar(tmp_path):
    out = tmp_path / "outcome_predictor.pt"
    metrics_path = tmp_path / "outcome_predictor.pt.metrics.json"
    trainer.train_and_save(
        encoder=_tiny_encoder(),
        examples=_tiny_examples(),
        output_path=str(out),
        metrics_path=str(metrics_path),
        epochs=1,
        hidden_size=4,
    )

    assert metrics_path.exists()
    import json

    saved = json.loads(metrics_path.read_text())
    assert saved["num_examples"] == 3
