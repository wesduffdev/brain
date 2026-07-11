"""instinct_inference — load the trained instinct model and run it behind the
InstinctPredictorPort (ADR 0026).

This is the real (torch-backed) implementation of
`app.ports.instinct.InstinctPredictorPort`. `load_instinct_predictor` loads
`instinct.pt` and returns a predictor that encodes a `Stimulus` with the SAME
`InstinctFeatureEncoder` contract the trainer used and returns a reaction
probability per label plus an intensity. It predicts only — it never selects a
reaction.

Graceful degradation is the point of the seam (mirroring the outcome predictor's
shadow load, ADR 0011): torch is a training/inference-only dependency kept out of
the lean runtime, and the artifact does not exist before training. When either is
absent, `load_instinct_predictor` returns ``None`` and instinct is simply off.
A *present* artifact whose feature/label contract disagrees with the current
config is a different case: that is a stale model, rejected loudly (``ValueError``)
rather than silently paired with newer config (ADR 0026, the ADR 0008 discipline).

torch is imported lazily inside `load_instinct_predictor` (mirroring the trainer),
so this module imports with zero training deps; only an actually-loaded predictor
pulls torch in.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.ml.instinct_encoder import InstinctFeatureEncoder, Stimulus
from app.ports.instinct import InstinctPrediction


class TorchInstinctPredictor:
    """A loaded instinct predictor: encodes a stimulus and returns a reaction
    probability per label plus an intensity. Satisfies `InstinctPredictorPort`."""

    def __init__(self, model, encoder: InstinctFeatureEncoder):
        self._model = model
        self._encoder = encoder

    def predict_reactions(self, stimulus: Stimulus) -> InstinctPrediction:
        features = self._encoder.encode_features(stimulus)
        probabilities, intensity = self._model.predict_one(features)
        reactions = {
            label: float(prob)
            for label, prob in zip(self._encoder.label_names(), probabilities)
        }
        return InstinctPrediction(reactions=reactions, intensity=float(intensity))


def load_instinct_predictor(*, config, model_path: str) -> Optional[TorchInstinctPredictor]:
    """Load the instinct predictor, or ``None`` when it cannot run.

    Returns ``None`` (graceful, instinct off) when torch is not installed or the
    artifact does not exist. Raises ``ValueError`` when the artifact *is* present
    but its feature/label contract does not match ``config`` — a stale model must
    never be silently used (ADR 0026)."""
    if not Path(model_path).exists():
        return None
    try:
        import torch  # noqa: F401 — lazy: only a loaded predictor needs torch
    except ImportError:
        return None

    from app.ml.instinct_model import load_instinct_model

    model, contract = load_instinct_model(model_path)
    encoder = InstinctFeatureEncoder.from_config(config)

    if (
        tuple(contract["feature_names"]) != encoder.feature_names()
        or tuple(contract["label_names"]) != encoder.label_names()
    ):
        raise ValueError(
            "instinct artifact does not match the current config vocabulary "
            "(ADR 0026): retrain the instinct model before running it"
        )

    return TorchInstinctPredictor(model, encoder)
