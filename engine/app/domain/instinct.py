"""Instinct capture — the persisted facts of the fast pre-conceptual layer.

The instinct layer (ADR 0026) runs a small neural model per perception/approach
event and predicts, for a stimulus, the probability of each protective
**reaction** (flinch / freeze / orient / withdraw / ignore) plus a scalar
intensity. This module holds the three lasting facts that layer produces, so the
learning substrate is queryable (EVT-PERSIST, ADR 0028):

- `InstinctPrediction` — what the model saw and predicted for one stimulus.
- `InstinctReaction` — the reaction that was chosen (``triggered``) or
  suppressed for that stimulus.
- `InstinctTrainingExample` — the model-ready row derived from a prediction once
  the being's actual reaction is observed, the instinct analogue of
  `TrainingExample` (the outcome model's, ADR 0008).

``event_id`` on each is the id of the perception/approach `DomainEvent` that
prompted the instinct (ADR 0024/0027), not an ``interaction_events`` row — the
instinct layer lives on the event backbone, ahead of the decision pipeline. These
are abstract internal probabilities the being learns so it can protect itself,
never depictions of real-world harm (`docs/design_boundary.md`, ADR 0013).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

# The frozen reaction-label order (ADR 0026): independent sigmoid probabilities,
# not a softmax distribution — a stimulus can score high on several at once.
REACTION_LABELS: Tuple[str, ...] = ("flinch", "freeze", "orient", "withdraw", "ignore")


@dataclass(frozen=True)
class InstinctPrediction:
    """One instinct inference: the being's perceived fast-sensory ``features``
    (the 14-scalar vector of ADR 0026), the model's per-reaction probabilities
    (in ``REACTION_LABELS`` order), and the scalar ``reaction_intensity``."""

    being_id: str
    tick: int
    event_id: str
    features: Tuple[float, ...]
    reaction_probabilities: Tuple[float, ...]
    reaction_intensity: float


@dataclass(frozen=True)
class InstinctReaction:
    """The reaction the being had to a stimulus: which ``reaction`` at what
    ``intensity``, and whether it was ``triggered`` (past threshold) or suppressed
    (below threshold / cooled down). Selection is a consumer concern (INS-RT); this
    is only the recorded fact of it."""

    being_id: str
    tick: int
    event_id: str
    reaction: str
    intensity: float
    triggered: bool


@dataclass(frozen=True)
class InstinctTrainingExample:
    """A model-ready instinct row: the stimulus ``input_features`` the model saw
    paired with the ``output_labels`` the being actually reacted with. ``event_id``
    links it back to the perception event it was derived from."""

    event_id: str
    input_features: Tuple[float, ...]
    output_labels: Tuple[float, ...]


def instinct_training_example(
    prediction: InstinctPrediction, observed_labels: Sequence[float]
) -> InstinctTrainingExample:
    """Derive the training row for one instinct prediction from the reaction the
    being was actually observed to have.

    Pairs the exact feature vector the model saw (`prediction.features`) with the
    observed reaction labels (in ``REACTION_LABELS`` order), keyed to the same
    perception event — so the instinct trainer learns from real stimulus→reaction
    pairs, exactly as `TrainingExample` derives from an `InteractionEvent`."""
    return InstinctTrainingExample(
        event_id=prediction.event_id,
        input_features=tuple(prediction.features),
        output_labels=tuple(observed_labels),
    )
