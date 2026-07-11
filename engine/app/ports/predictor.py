"""Predictor port — the outcome-prediction seam (ADR 0011, extended by card v3).

A predictor turns one encoded interaction into an outcome probability per label.
This is a genuine seam because several implementations vary across it:

- `app.ml.inference.TorchOutcomePredictor` — the real torch-backed model loaded
  from `outcome_predictor.pt` (torch lives only there, imported lazily);
- `RuleBasedPredictor` (below) — the rule layer as a predictor, always available
  with zero dependencies, the safe baseline the neural model blends with and
  falls back to;
- `EnsemblePredictor` (below) — blends a neural predictor with the rule-based one
  by config weight and degrades to rules on a neural error;
- a fake the behavior suite drives, so all prediction logic is testable without
  torch or an artifact.

The rule-based and ensemble predictors are pure Python and live here beside the
port so the lean runtime carries them; only an actually-loaded neural predictor
pulls torch in. A predictor only *predicts* — it never chooses an action (BRIEF
§11, §12); the decision layer consumes its probabilities but the SafetyService
floor still gates every candidate, so a learned score can never bypass safety.
"""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Protocol, Sequence

from app.ml.encode_features import Example
from app.policies import ActionPolicy, PredictionBlendPolicy


class PredictorPort(Protocol):
    """Predicts outcome probabilities for one encoded interaction."""

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        """Map each outcome label to an independent probability in ``[0, 1]`` for
        ``example`` (multi-label — not a distribution over labels)."""
        ...


class RuleBasedPredictor:
    """The rule layer, exposed as a `PredictorPort` (card v3).

    Predicts the outcomes the being's own action rules (`actions.yaml`, via
    `ActionPolicy.outcomes_for`) say an action produces on an object with the
    given properties, as certain (1.0) / not (0.0) probabilities over the full
    label vocabulary. It needs no model and no torch, so it is always available:
    the safe baseline the neural model is blended with — and falls back to. An
    interaction's `action` is an object *affordance* (ADR 0011); a free action
    (no affordance) matches no rule and predicts nothing (all zeros).
    """

    def __init__(self, actions: Mapping[str, ActionPolicy], labels: Sequence[str]):
        self._labels = tuple(labels)
        self._by_affordance: Dict[str, ActionPolicy] = {
            policy.affordance: policy
            for policy in actions.values()
            if policy.affordance is not None
        }

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        policy = self._by_affordance.get(example.action)
        predicted = set(policy.outcomes_for(example.properties)) if policy is not None else set()
        return {label: 1.0 if label in predicted else 0.0 for label in self._labels}


class EnsemblePredictor:
    """Blends a neural predictor with the rule-based one by config weight, with a
    safe fallback to rules on error (card v3, extends ADR 0011).

    Per label the blended probability is
    ``neural_weight * P_neural + rule_weight * P_rule``. When the neural predictor
    is disabled (`neural_enabled` off) or absent, the rule layer carries the call
    alone. When an *enabled* neural predictor raises, the ensemble degrades to the
    rule layer if `fallback_to_rules_on_error` is set — so a model failure never
    stops the being deciding — otherwise the error propagates. It is itself a
    `PredictorPort`, so the decision layer depends only on the port, never on how
    the prediction was produced.
    """

    def __init__(
        self,
        *,
        rule: PredictorPort,
        neural: Optional[PredictorPort],
        policy: PredictionBlendPolicy,
    ):
        self._rule = rule
        self._neural = neural
        self._policy = policy

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        rule_probs = self._rule.predict_outcomes(example)
        if not self._policy.neural_enabled or self._neural is None:
            return rule_probs
        try:
            neural_probs = self._neural.predict_outcomes(example)
        except Exception:
            if self._policy.fallback_to_rules_on_error:
                return rule_probs
            raise
        labels = set(rule_probs) | set(neural_probs)
        return {
            label: self._policy.neural_weight * float(neural_probs.get(label, 0.0))
            + self._policy.rule_weight * float(rule_probs.get(label, 0.0))
            for label in labels
        }
