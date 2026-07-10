"""train_outcome_model — trains the outcome predictor and writes the artifact.

The v0 learning loop (BRIEF §11, "Shadow Mode First"): the being's rule layer is
the source of truth, and this small net learns to imitate it. Real stored
`training_examples` are used when they exist; until the persistence + event
wiring lands (V0-6/V0-7), the trainer seeds itself from a **synthetic seed set**
derived from the config vocabulary — so the whole loop (encode -> train ->
evaluate -> persist) runs standalone, with no database.

Public surface:
  - `synthetic_examples(config)` — the config-derived seed set (pure, no torch).
  - `train(...)` / `train_and_save(...)` — train a model and (optionally) persist
    it with metrics.
  - `main()` — the `python -m app.ml.train_outcome_model` / `ml-trainer` entry.

PyTorch is imported lazily inside the training functions, so importing this
module (e.g. to reach `synthetic_examples`) never requires the training-only
dependency set.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.ml.encode_features import Example, FeatureEncoder

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_ROOT = _REPO_ROOT / "config"
_DEFAULT_MODEL_PATH = _REPO_ROOT / "models" / "outcome_predictor.pt"


# --- the synthetic seed set ------------------------------------------------
#
# Authored rules that stand in for the being's rule layer: given an object's
# properties, the action taken, and the surface it meets, what happens? These are
# the "ground truth" the net imitates in v0. They are config-derived (they read
# the real object catalog and context vocabulary), deterministic, and chosen so
# every outcome label appears in the seed set.


def _outcomes_for(properties: Set[str], action: str, context: str) -> List[str]:
    outcomes: List[str] = []
    if action in ("push", "drop") and "round" in properties:
        outcomes.append("rolls")
    if action == "drop":
        outcomes.append("falls")
    if action == "drop" and "rubbery" in properties and context == "surface_hard":
        outcomes.append("bounces")
    if action in ("push", "drop") and "heavy" in properties:
        outcomes.append("makes_noise")
    if action == "touch" and "hard" in properties and "heavy" in properties:
        outcomes.append("causes_pain")
    if action == "push" and "heavy" in properties and context == "surface_hard":
        outcomes.append("scary")
    pleasant_touch = action in ("touch", "grab") and ("soft" in properties or "warm" in properties)
    pleasant_sight = action == "look" and ("red" in properties or "blue" in properties)
    if pleasant_touch or pleasant_sight:
        outcomes.append("pleasant")
    return outcomes


def synthetic_examples(config) -> List[Example]:
    """A deterministic seed set: every real object, crossed with each action it
    affords and each surface context, labelled by the authored rules above."""
    contexts = config.outcome_context_features() or ("surface_hard",)
    examples: List[Example] = []
    for entity in config.object_catalog().values():
        props = set(entity.properties)
        for action in entity.affordances:
            for context in contexts:
                outcomes = _outcomes_for(props, action, context)
                examples.append(
                    Example(
                        properties=tuple(entity.properties),
                        action=action,
                        context=(context,),
                        outcomes=tuple(outcomes),
                    )
                )
    return examples


def load_training_examples(config) -> Optional[List[Example]]:
    """Stored training examples take priority once the DB port exists (V0-6
    persistence + V0-7 event->example wiring). There is no DB port yet, so this
    returns None and the trainer falls back to the synthetic seed set. Kept
    deliberately un-wired: the synthetic path must run without Postgres."""
    return None


# --- training --------------------------------------------------------------


def train(
    *,
    encoder: FeatureEncoder,
    examples: List[Example],
    epochs: int,
    hidden_size: int,
    learning_rate: float = 0.05,
    seed: int = 0,
):
    """Train an OutcomeModel to green on `examples`; returns (model, metrics).
    Torch is imported here so the module imports without the training deps."""
    import torch
    from torch import nn

    from app.ml.outcome_model import OutcomeModel

    torch.manual_seed(seed)

    features = torch.tensor(
        [list(encoder.encode_features(ex)) for ex in examples], dtype=torch.float32
    )
    labels = torch.tensor(
        [list(encoder.encode_labels(ex)) for ex in examples], dtype=torch.float32
    )

    model = OutcomeModel(encoder.feature_size, encoder.label_size, hidden_size)
    loss_fn = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    final_loss = 0.0
    for _ in range(max(1, int(epochs))):
        optimizer.zero_grad()
        loss = loss_fn(model(features), labels)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.item())

    metrics = _evaluate(model, features, labels, encoder.label_names())
    metrics.update(
        {"num_examples": len(examples), "epochs": int(epochs), "final_loss": final_loss}
    )
    return model, metrics


def _evaluate(model, features, labels, label_names) -> Dict:
    """Training-set fit at threshold 0.5: hamming (per-slot) and exact-match
    (whole-vector) accuracy, plus per-label accuracy. In v0 the model imitates
    rules, so this measures how well it reproduced them."""
    probabilities = model.predict(features)
    predictions = (probabilities >= 0.5).float()
    correct = (predictions == labels).float()
    return {
        "hamming_accuracy": float(correct.mean().item()) if correct.numel() else 0.0,
        "exact_match": float(correct.prod(dim=1).mean().item()) if correct.numel() else 0.0,
        "per_label": {
            name: float(correct[:, i].mean().item()) for i, name in enumerate(label_names)
        },
    }


def train_and_save(
    *,
    encoder: FeatureEncoder,
    examples: List[Example],
    output_path: str,
    metrics_path: Optional[str] = None,
    epochs: int = 300,
    hidden_size: int = 16,
    learning_rate: float = 0.05,
    seed: int = 0,
) -> Dict:
    """Train, persist the model (with its feature/label contract) to
    `output_path`, and return the metrics — writing them to `metrics_path` too
    when given."""
    from app.ml.outcome_model import save_outcome_model

    model, metrics = train(
        encoder=encoder,
        examples=examples,
        epochs=epochs,
        hidden_size=hidden_size,
        learning_rate=learning_rate,
        seed=seed,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    save_outcome_model(
        model,
        output_path,
        feature_names=encoder.feature_names(),
        label_names=encoder.label_names(),
        metrics=metrics,
    )

    if metrics_path:
        Path(metrics_path).parent.mkdir(parents=True, exist_ok=True)
        Path(metrics_path).write_text(json.dumps(metrics, indent=2, sort_keys=True))

    return metrics


def main() -> None:
    """Train on stored examples if present, else the synthetic seed set, and
    write `models/outcome_predictor.pt` + a metrics sidecar. Paths and tuning are
    config/env-driven so the container and local `make train` share this path."""
    from app.config_service import ConfigService

    config_root = os.environ.get("CONFIG_ROOT", str(_DEFAULT_CONFIG_ROOT))
    output_path = os.environ.get("MODEL_OUTPUT_PATH", str(_DEFAULT_MODEL_PATH))

    config = ConfigService.from_files(config_root)
    encoder = FeatureEncoder.from_config(config)

    examples = load_training_examples(config)
    source = "training_examples"
    if not examples:
        examples = synthetic_examples(config)
        source = "synthetic"

    params = config.outcome_training_params()
    metrics = train_and_save(
        encoder=encoder,
        examples=examples,
        output_path=output_path,
        metrics_path=output_path + ".metrics.json",
        epochs=params["epochs"],
        hidden_size=params["hidden_size"],
        learning_rate=params["learning_rate"],
        seed=params["seed"],
    )

    print(
        "trained outcome predictor "
        f"(source={source}, examples={metrics['num_examples']}, "
        f"epochs={metrics['epochs']})\n"
        f"  -> {output_path}\n"
        f"  final_loss={metrics['final_loss']:.4f} "
        f"hamming_accuracy={metrics['hamming_accuracy']:.3f} "
        f"exact_match={metrics['exact_match']:.3f}"
    )


if __name__ == "__main__":
    main()
