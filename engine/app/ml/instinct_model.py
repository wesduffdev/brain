"""InstinctModel — the being's second neural network: a tiny feed-forward net that
maps fast-sensory stimulus features to protective REACTIONS (ADR 0026).

A shared trunk (`Linear -> ReLU`) feeds two heads: a `label_head` emitting one
logit per reaction (`flinch, freeze, orient, withdraw, ignore`), and an
`intensity_head` emitting a single scalar. `predict` applies a sigmoid to each,
so the five reactions are INDEPENDENT probabilities (multi-label, not softmax — a
stimulus can be both `flinch` and `withdraw`) and `reaction_intensity` is a
scalar in `[0, 1]`. Deliberately tiny: in v0 it imitates the rule-labeled seed
set that generated its training data (ADR 0026), so the job is to exercise the
full ML loop, not to be large. It is a SEPARATE model from the outcome predictor
(not a second head) — disjoint inputs, a mixed classification+regression
objective, and an independent rollout (ADR 0026).

This module imports PyTorch at import time, so it is only pulled in by the trainer
and by shadow-mode inference — never by the lean runtime import path.
`save_instinct_model`/`load_instinct_model` persist the model *with* its
feature/label contract so a reloaded artifact carries the vocabulary it was
trained against (ADR 0026, mirroring ADR 0008).
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import torch
from torch import nn


class InstinctModel(nn.Module):
    def __init__(self, input_size: int, label_size: int, hidden_size: int = 16):
        super().__init__()
        self.input_size = input_size
        self.label_size = label_size
        self.hidden_size = hidden_size
        self.trunk = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
        )
        self.label_head = nn.Linear(hidden_size, label_size)
        self.intensity_head = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Raw logits for both heads — training uses BCEWithLogitsLoss for the
        reaction labels (and for the intensity head when configured that way) for
        numerical stability; callers wanting probabilities use `predict`."""
        hidden = self.trunk(x)
        return self.label_head(hidden), self.intensity_head(hidden)

    def predict(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """(reaction probabilities, intensity) — each a sigmoid of its head's
        logits, so reactions are independent probabilities and intensity is a
        scalar in ``[0, 1]``."""
        with torch.no_grad():
            label_logits, intensity_logit = self.forward(x)
            return torch.sigmoid(label_logits), torch.sigmoid(intensity_logit)

    def predict_one(self, features: Sequence[float]) -> Tuple[List[float], float]:
        """One stimulus's feature vector -> (a probability per reaction in
        `label_names` order, the scalar reaction_intensity). The shape inference
        consumes."""
        row = torch.tensor([list(features)], dtype=torch.float32)
        probabilities, intensity = self.predict(row)
        return probabilities[0].tolist(), float(intensity[0].item())


def save_instinct_model(
    model: InstinctModel,
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
            "label_size": model.label_size,
            "hidden_size": model.hidden_size,
            "feature_names": list(feature_names),
            "label_names": list(label_names),
            "metrics": metrics or {},
        },
        path,
    )


def load_instinct_model(path: str) -> Tuple[InstinctModel, Dict]:
    """Reload a saved model with its contract: returns the eval-ready model and a
    dict of `feature_names`/`label_names`/`metrics` so a consumer can encode
    inputs and read outputs against the exact vocabulary it was trained on
    (ADR 0026)."""
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:  # older torch has no weights_only kwarg
        checkpoint = torch.load(path, map_location="cpu")

    model = InstinctModel(
        checkpoint["input_size"],
        checkpoint["label_size"],
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
