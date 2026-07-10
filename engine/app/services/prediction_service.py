"""PredictionService — runs the outcome predictor in shadow mode (BRIEF §11, §17).

For one interaction it encodes the being's perception + action, asks the injected
predictor for an outcome probability per label, and records a `PredictionRecord`
that sets the model's prediction beside the rule layer's expectation and the
actual observed outcome, marked right or wrong. It writes through the repository
port; it never touches the being's state, needs, emotion, or decision — the model
observes, it does not drive (ADR 0011). That is the shadow invariant: turning the
predictor on or off leaves the being's behavior byte-identical.

Correctness is exact-match at the threshold (predicts bounce, actual bounce ->
correct, BRIEF §16); `prediction_error` is the mean absolute gap between the
predicted probabilities and the actual outcome — the continuous signal a later
version feeds into curiosity, kept here so the record already carries it.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

from app.domain.interaction_event import InteractionEvent
from app.domain.prediction_record import PredictionRecord
from app.ml.encode_features import Example
from app.ports.predictor import PredictorPort
from app.ports.repositories import PredictionRecordRepository


class PredictionService:
    def __init__(
        self,
        predictor: PredictorPort,
        repository: PredictionRecordRepository,
        *,
        threshold: float = 0.5,
    ):
        self._predictor = predictor
        self._repository = repository
        self._threshold = threshold

    def record(
        self,
        event: InteractionEvent,
        *,
        properties: Sequence[str],
        action: Optional[str] = None,
        context: Sequence[str] = (),
    ) -> PredictionRecord:
        """Predict the outcomes of ``event`` from what the being perceived
        (``properties`` + the action + situational ``context``), compare the
        thresholded prediction to the actual observed outcome, and store the
        record. Returns it. Purely observational — no being state is touched.

        ``action`` is the term to encode from the model's action vocabulary (an
        object *affordance*); it differs from the event's action *name* (e.g. the
        `observe` action encodes as the `look` affordance, and free actions like
        `approach` encode as no affordance at all). It defaults to the event's
        action for callers whose action names are already affordance terms."""
        encode_action = event.action if action is None else action
        example = Example(
            properties=tuple(properties),
            action=encode_action,
            context=tuple(context),
        )
        probabilities = self._predictor.predict_outcomes(example)

        actual = tuple(event.observed_outcome)
        model_outcome = tuple(
            sorted(label for label, prob in probabilities.items() if prob >= self._threshold)
        )
        record = PredictionRecord(
            being_id=event.being_id,
            tick=event.tick,
            object_id=event.object_id,
            action=event.action,
            probabilities={label: float(prob) for label, prob in probabilities.items()},
            model_outcome=model_outcome,
            rule_expected=tuple(event.expected_outcome),
            actual_observed=actual,
            correct=set(model_outcome) == set(actual),
            prediction_error=_mean_absolute_error(probabilities, actual),
        )
        self._repository.add(record)
        return record


def _mean_absolute_error(probabilities: Dict[str, float], actual: Tuple[str, ...]) -> float:
    """Mean |probability - actual| over every label (actual is 1 if the outcome
    occurred, else 0). 0.0 for a perfectly confident, perfectly right prediction."""
    if not probabilities:
        return 0.0
    actual_set = set(actual)
    total = sum(
        abs(prob - (1.0 if label in actual_set else 0.0))
        for label, prob in probabilities.items()
    )
    return total / len(probabilities)
