"""TrainingExample — a model-ready row derived from an interaction event.

What the outcome predictor learns from (BRIEF §9, ADR 0008): one interaction
encoded as a multi-hot **input** vector (object properties ++ action ++ context,
in the fixed contract order) paired with its multi-hot **output** vector (the
observed outcomes). `event_id` links the row back to the InteractionEvent it was
derived from, so a stored example is always traceable to the moment it happened.

This is the persisted aggregate the training-example repository speaks in — the
already-encoded floats, not the pre-encoding `ml.encode_features.Example`. The
encoding itself is the ADR 0008 contract and lives in `FeatureEncoder`; this type
just carries the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class TrainingExample:
    event_id: str
    input_features: Tuple[float, ...]
    output_labels: Tuple[float, ...]
