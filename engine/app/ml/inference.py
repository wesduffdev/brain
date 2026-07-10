"""inference — load the trained outcome predictor and run it in shadow mode.

This is the real (torch-backed) implementation of `app.ports.predictor.PredictorPort`
(ADR 0011). `load_predictor` loads `outcome_predictor.pt` and returns a predictor
that encodes an interaction with the SAME `FeatureEncoder` contract the trainer
used (ADR 0008) and returns an outcome probability per label. It predicts only —
it never chooses an action.

Graceful degradation is the point of the seam: torch is a training/inference-only
dependency kept out of the lean runtime, and the artifact does not exist before
training. When either is absent, `load_predictor` returns ``None`` and shadow
mode records nothing — the being's behavior is unchanged. A *present* artifact
whose feature/label contract disagrees with the current config is a different
case: that is a stale model, and it is rejected loudly (``ValueError``) rather
than silently paired with newer config (ADR 0008), because doing so would make
every prediction quietly garbage.

torch is imported lazily inside `load_predictor` (mirroring the trainer), so this
module imports with zero training deps; only an actually-loaded predictor pulls
torch in.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.ml.encode_features import Example, FeatureEncoder


class TorchOutcomePredictor:
    """A loaded outcome predictor: encodes an interaction and returns an outcome
    probability per label. Satisfies `PredictorPort`."""

    def __init__(self, model, encoder: FeatureEncoder):
        self._model = model
        self._encoder = encoder

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        features = self._encoder.encode_features(example)
        probabilities = self._model.predict_one(features)
        return {
            label: float(prob)
            for label, prob in zip(self._encoder.label_names(), probabilities)
        }


def load_predictor(*, config, model_path: str) -> Optional[TorchOutcomePredictor]:
    """Load the shadow-mode predictor, or ``None`` when it cannot run.

    Returns ``None`` (graceful, shadow off) when torch is not installed or the
    artifact does not exist. Raises ``ValueError`` when the artifact *is* present
    but its feature/label contract does not match ``config`` — a stale model must
    never be silently used (ADR 0008)."""
    if not Path(model_path).exists():
        return None
    try:
        import torch  # noqa: F401 — lazy: only a loaded predictor needs torch
    except ImportError:
        return None

    from app.ml.outcome_model import load_outcome_model

    model, contract = load_outcome_model(model_path)
    encoder = FeatureEncoder.from_config(config)

    if (
        tuple(contract["feature_names"]) != encoder.feature_names()
        or tuple(contract["label_names"]) != encoder.label_names()
    ):
        raise ValueError(
            "outcome_predictor artifact does not match the current config "
            "vocabulary (ADR 0008): retrain the model before running shadow mode"
        )

    return TorchOutcomePredictor(model, encoder)
