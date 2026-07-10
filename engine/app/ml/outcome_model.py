"""OutcomeModel — the being's first neural network: a small feed-forward,
multi-label outcome predictor (BRIEF §11).

One hidden layer, then one logit per outcome; `predict` applies a sigmoid so
each outcome is an independent probability (multi-label, not softmax — a dropped
rubber ball can be falls *and* bounces *and* rolls at once). Deliberately tiny:
in v0 it is imitating the rule layer that generated its training data, so the
job is to exercise the full ML loop, not to be large.

This module imports PyTorch at import time, so it is only pulled in by the
trainer and by shadow-mode inference (V0-9) — never by the lean runtime import
path. `save_outcome_model`/`load_outcome_model` persist the model *with* its
feature/label contract so a reloaded artifact carries the vocabulary it was
trained against (ADR 0008).
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import torch
from torch import nn


class OutcomeModel(nn.Module):
    def __init__(self, input_size: int, output_size: int, hidden_size: int = 16):
        super().__init__()
        self.input_size = input_size
        self.output_size = output_size
        self.hidden_size = hidden_size
        self.net = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, output_size),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Raw logits — training uses BCEWithLogitsLoss for numerical stability;
        callers wanting probabilities use `predict`/`predict_one`."""
        return self.net(x)

    def predict(self, x: torch.Tensor) -> torch.Tensor:
        with torch.no_grad():
            return torch.sigmoid(self.forward(x))

    def predict_one(self, features: Sequence[float]) -> List[float]:
        """One interaction's feature vector -> a probability per outcome, in
        `label_names` order. The shape shadow-mode inference consumes."""
        row = torch.tensor([list(features)], dtype=torch.float32)
        return self.predict(row)[0].tolist()


def save_outcome_model(
    model: OutcomeModel,
    path: str,
    *,
    feature_names: Sequence[str],
    label_names: Sequence[str],
    metrics: Dict = None,
) -> None:
    torch.save(
        {
            "state_dict": model.state_dict(),
            "input_size": model.input_size,
            "output_size": model.output_size,
            "hidden_size": model.hidden_size,
            "feature_names": list(feature_names),
            "label_names": list(label_names),
            "metrics": metrics or {},
        },
        path,
    )


def load_outcome_model(path: str) -> Tuple[OutcomeModel, Dict]:
    """Reload a saved model with its contract: returns the eval-ready model and a
    dict of `feature_names`/`label_names`/`metrics` so a consumer can encode
    inputs and read outputs against the exact vocabulary it was trained on."""
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:  # older torch has no weights_only kwarg
        checkpoint = torch.load(path, map_location="cpu")

    model = OutcomeModel(
        checkpoint["input_size"],
        checkpoint["output_size"],
        checkpoint["hidden_size"],
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    contract = {
        "feature_names": checkpoint["feature_names"],
        "label_names": checkpoint["label_names"],
        "metrics": checkpoint.get("metrics", {}),
    }
    return model, contract
