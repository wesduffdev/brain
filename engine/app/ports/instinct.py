"""Instinct predictor port — the reaction-prediction seam (ADR 0026).

An instinct predictor turns one perceived `Stimulus` into a protective-reaction
probability per label plus a scalar reaction intensity. This is a genuine seam,
separate from `PredictorPort`, because several implementations vary across it
(ADR 0026): the real torch-backed model loaded from `instinct.pt`
(`app.ml.instinct_inference.TorchInstinctPredictor`, torch imported lazily), and
a fake the reaction consumer's (`INS-RT`) behavior suite drives with no torch and
no artifact.

Like `PredictorPort`, an instinct predictor only *predicts* — it never selects a
reaction and never bypasses safety. Reaction selection, thresholds, and cooldowns
are a downstream consumer concern (`INS-RT`); a learned instinct score can no more
buy a blocked action past the safety floor than an outcome score can (ADR
0009/0014).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from app.ml.instinct_encoder import Stimulus


@dataclass(frozen=True)
class InstinctPrediction:
    """One instinct prediction: an independent probability per reaction label
    (`flinch, freeze, orient, withdraw, ignore` — multi-label, not a
    distribution) and the scalar `reaction_intensity` in ``[0, 1]``."""

    reactions: Mapping[str, float]
    intensity: float


class InstinctPredictorPort(Protocol):
    """Predicts protective-reaction probabilities + intensity for one stimulus."""

    def predict_reactions(self, stimulus: Stimulus) -> InstinctPrediction:
        """Map the perceived ``stimulus`` to an `InstinctPrediction` — a reaction
        probability per label and a scalar intensity."""
        ...
