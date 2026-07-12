"""Prediction client — WHERE model inference runs (v8, ADR 0043).

The two learned models sit behind stable ports (`PredictorPort`,
`InstinctPredictorPort`). A `PredictionClient` is one object covering BOTH: it
answers `predict_outcomes` and `predict_reactions`, so a single client can stand
in for either model wherever a `PredictorPort` or an `InstinctPredictorPort` is
wanted. This is the seam that lets inference move OUT-OF-PROCESS behind the
`model-service` sidecar without touching a single caller above the ports.

Three implementations vary across it:

- `InProcessPredictionClient` — delegates to the in-process predictors already in
  the engine (torch or rules), the current behavior. A missing model degrades to a
  SAFE NULL: no outcome prediction (all-zero probabilities) / no reaction (all-zero
  `InstinctPrediction`), so it is also the safe baseline the fallback wraps.
- `HttpPredictionClient` (in `app.adapters`) — calls the sidecar over HTTP.
- `FallbackPredictionClient` — a primary (usually the HTTP client) plus a safe
  fallback; on ANY error from the primary it degrades to the fallback, so a model
  outage never stalls the sim. This mirrors the narrator's `FallbackLanguageModel`
  and the predictor ensemble's `fallback_to_rules_on_error` (ADR 0011/0022): the
  sidecar is an upgrade, never a dependency.

A client only *predicts* — it never chooses an action or a reaction, and a served
score can no more bypass the `SafetyService` floor than an in-process one can
(BRIEF §12): the floor gates candidates upstream of prediction (ADR 0009/0014).
"""
from __future__ import annotations

from typing import Dict, Optional, Protocol, Sequence

from app.ml.encode_features import Example
from app.ml.instinct_encoder import Stimulus
from app.ports.instinct import InstinctPrediction, InstinctPredictorPort
from app.ports.predictor import PredictorPort


class PredictionClient(Protocol):
    """One object covering BOTH model ports — outcome probabilities and instinct
    reactions — so inference can run in-process or behind the sidecar uniformly."""

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        ...

    def predict_reactions(self, stimulus: Stimulus) -> InstinctPrediction:
        ...


def _safe_no_reaction(labels: Sequence[str]) -> InstinctPrediction:
    """The safe baseline reaction: an independent 0.0 for every label and zero
    intensity — nothing ever crosses a firing threshold, so no reaction fires."""
    return InstinctPrediction(reactions={label: 0.0 for label in labels}, intensity=0.0)


class InProcessPredictionClient:
    """Delegates both predictions to the in-process predictors (today's behavior).

    When a model is absent (no torch / no artifact -> the injected predictor is
    ``None``) it degrades to a SAFE NULL rather than raising: an all-zero outcome
    map over `outcome_labels`, and the safe no-reaction `InstinctPrediction` over
    `instinct_labels`. That makes this class double as the safe baseline a
    `FallbackPredictionClient` degrades to.
    """

    def __init__(
        self,
        *,
        outcome: Optional[PredictorPort] = None,
        instinct: Optional[InstinctPredictorPort] = None,
        outcome_labels: Sequence[str] = (),
        instinct_labels: Sequence[str] = (),
    ) -> None:
        self._outcome = outcome
        self._instinct = instinct
        self._outcome_labels = tuple(outcome_labels)
        self._instinct_labels = tuple(instinct_labels)

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        if self._outcome is None:
            return {label: 0.0 for label in self._outcome_labels}
        return self._outcome.predict_outcomes(example)

    def predict_reactions(self, stimulus: Stimulus) -> InstinctPrediction:
        if self._instinct is None:
            return _safe_no_reaction(self._instinct_labels)
        return self._instinct.predict_reactions(stimulus)


class FallbackPredictionClient:
    """A `PredictionClient` that is TWO clients: a `primary` (usually the HTTP
    sidecar client) and a safe `fallback`. It returns the primary's result, and on
    ANY error from the primary — a raised exception, an unavailable endpoint, a bad
    HTTP status — degrades to the fallback for that SAME call, so the being always
    gets a prediction and the sim never stalls on a model outage. Deliberately
    broad (`except Exception`): any provider failure must fall back, never crash.
    """

    def __init__(self, *, primary: PredictionClient, fallback: PredictionClient) -> None:
        self._primary = primary
        self._fallback = fallback

    def predict_outcomes(self, example: Example) -> Dict[str, float]:
        try:
            return self._primary.predict_outcomes(example)
        except Exception:
            return self._fallback.predict_outcomes(example)

    def predict_reactions(self, stimulus: Stimulus) -> InstinctPrediction:
        try:
            return self._primary.predict_reactions(stimulus)
        except Exception:
            return self._fallback.predict_reactions(stimulus)
