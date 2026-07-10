"""PredictionRecord — one shadow-mode prediction, kept for comparison.

When the being acts, the learned outcome predictor (BRIEF §11) predicts the
likely outcomes *alongside* the rule layer. This record captures all three views
of that one interaction so they can be compared later (shadow mode, ADR 0011):

  - `model_outcome`    — what the learned model predicted (thresholded), plus the
                          raw `probabilities` it produced per label.
  - `rule_expected`    — what the rule layer expected (the InteractionEvent's
                          expected outcome, derived from perception).
  - `actual_observed`  — what actually happened (the observed outcome).

`correct` marks whether the model's thresholded prediction matched the actual
outcome exactly (BRIEF §16: predicts bounce, actual bounce -> correct);
`prediction_error` is the continuous mismatch between the model's probabilities
and the actual outcome, the signal later versions feed into curiosity. The
prediction never influences the being's decision — the model only observes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class PredictionRecord:
    being_id: str
    tick: int
    object_id: str
    action: str
    probabilities: Dict[str, float] = field(default_factory=dict)
    model_outcome: Tuple[str, ...] = ()
    rule_expected: Tuple[str, ...] = ()
    actual_observed: Tuple[str, ...] = ()
    correct: bool = False
    prediction_error: float = 0.0

    def snapshot(self) -> Dict:
        """A plain, serializable view with stable camelCase keys, ready for the
        wire and, later, the `prediction_records` table (BRIEF §9, §15)."""
        return {
            "beingId": self.being_id,
            "tick": self.tick,
            "objectId": self.object_id,
            "action": self.action,
            "probabilities": dict(self.probabilities),
            "modelOutcome": list(self.model_outcome),
            "ruleExpected": list(self.rule_expected),
            "actualObserved": list(self.actual_observed),
            "correct": self.correct,
            "predictionError": self.prediction_error,
        }
