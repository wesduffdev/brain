"""Predictor port — the shadow-vs-real inference seam (ADR 0011).

A predictor turns one encoded interaction into an outcome probability per label.
This is a genuine seam because two things vary across it: a real torch-backed
predictor loaded from `outcome_predictor.pt` (`app.ml.inference`), and a fake the
behavior suite drives so shadow-mode logic is testable without torch or an
artifact. Callers (`PredictionService`) depend on this port, never on torch.

A predictor only *predicts* — it never chooses an action (BRIEF §11, §12). When
no model can be loaded (torch or artifact absent) there is simply no predictor,
and shadow mode records nothing; that graceful absence is `load_predictor`
returning ``None``, not a method on this port.
"""
from __future__ import annotations

from typing import Dict, Protocol

from app.ml.encode_features import Example


class PredictorPort(Protocol):
    """Predicts outcome probabilities for one encoded interaction."""

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        """Map each outcome label to an independent probability in ``[0, 1]`` for
        ``example`` (multi-label — not a distribution over labels)."""
        ...
